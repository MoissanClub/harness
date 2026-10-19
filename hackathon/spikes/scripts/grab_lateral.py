"""Tabletop grab, lateral approach: hand 10 cm to the left of the can at mid-height + 3 cm, slide sideways onto the can, staged grasp, lift, retract.
Usage: python grab_lateral.py [--dry] [--tol 0.035] [--dz 0.03] [--pause 6] [--roll 0.0]"""
import sys, re, base64, time, logging
import numpy as np, cv2
sys.path.insert(0, "/home/unitree/g1-fetch"); sys.path.insert(0, "/home/unitree/harness/bench")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
from client import timed_chat
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml")
def arg(name, default):
    return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
DRY = "--dry" in sys.argv
TOL = arg("--tol", float(cfg.arm.ik_max_pos_err)); DZ = arg("--dz", 0.03); PAUSE = arg("--pause", 6.0); ROLL = arg("--roll", float(cfg.robot.palm_inward_wrist_roll.left))
cfg.arm.ik_max_pos_err = TOL; cfg.robot.palm_inward_wrist_roll.left = ROLL
from g1_fetch.robot import build_robot
from g1_fetch.perception.detector import Detection
from g1_fetch.perception.localize import can_axis_from_box
from g1_fetch.skills.common import look_for, go_home, cart_move, SkillFailed
from g1_fetch.control.robot_state import set_arm_action_service
OUT = "/home/unitree/spike/"
STAGES = ([0.0, 0.8, 0.0, 0.0, 0.0, 0.0], 1.0), ([0.0, 0.8, 0.9, 0.9, 0.9, 0.9], 1.5), ([0.9, 0.8, 0.9, 0.9, 0.9, 0.9], 1.0)

def gemma_box(color, what="the soda can", label="soda can"):
    small = cv2.resize(color, (480, 336), interpolation=cv2.INTER_AREA)
    cv2.imwrite(OUT + "grab_480x336.jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(open(OUT + "grab_480x336.jpg", "rb").read()).decode()
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            {"type": "text", "text": "Detect " + what + ". Output only JSON: [{\"box_2d\": [ymin, xmin, ymax, xmax], \"label\": \"" + label + "\"}] with coordinates normalized to 0-1000."}]},
            {"role": "assistant", "content": '```json\n[\n  {"box_2d": ['}]
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 24,
                   "chat_template_kwargs": {"enable_thinking": False}, "messages": msgs, "stop": ["]"]})
    txt = r["content"]; nums = [int(n) for n in re.findall(r"\d+", txt[txt.rindex("[") + 1:])][:4] if "[" in txt else []
    if len(nums) != 4: return None
    y1, x1, y2, x2 = nums
    return Detection("can" if label == "soda can" else label, 1.0, (x1 / 1000 * 640, y1 / 1000 * 480, x2 / 1000 * 640, y2 / 1000 * 480), "gemma")

rb = build_robot(cfg)
try:
    hand = rb.hands["left"]
    rb.speak("Lateral grab test. Looking for the can.")
    det, frame = look_for(rb, "can", max_frames=10); src = "yoloe"
    if det is None:
        det = gemma_box(frame.color); src = "gemma"
    if det is None:
        rb.speak("I do not see a can."); print("NO CAN"); sys.exit(2)
    p = can_axis_from_box(frame, det, rb.frames, cfg)
    if p is None:
        rb.speak("No depth on the can."); print("NO DEPTH"); sys.exit(2)
    palm, x_dir, r = np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]), float(cfg.fridge.can_diameter_m) / 2
    grasp_p = p + np.array([0.0, r + 0.01, DZ])          # palm centre beside the can axis, DZ above its mid-height
    pre_p = grasp_p + np.array([0.0, 0.10, 0.0])           # 10 cm further to the robot's left
    res_g = rb.kin.ik("left", grasp_p, x_dir, q_seed=rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
    res_p = rb.kin.ik("left", pre_p, x_dir, q_seed=rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
    print(f"CAN via {src} conf {det.conf:.2f}: axis pelvis {np.round(p, 3).tolist()} floor height {rb.frames.floor_height(p):.2f} m; "
          f"pre {np.round(pre_p, 3).tolist()} IK err {res_p.pos_err:.3f}; grasp {np.round(grasp_p, 3).tolist()} IK err {res_g.pos_err:.3f} dir_err {res_g.dir_err:.3f} q {np.round(res_g.q, 2).tolist()}", flush=True)
    if DRY:
        rb.speak("Dry run done."); sys.exit(0)
    if res_g.pos_err > TOL or res_p.pos_err > TOL:
        rb.speak("Out of reach."); print("OUT OF REACH"); sys.exit(3)
    rb.arms.enable()
    for side in ("left", "right"): rb.hands[side].open(wait=False)
    go_home(rb, "left", duration=2.0)
    home_p = rb.kin.fk("left", rb.arms.cmd["left"])[:3, 3]
    up = np.array([home_p[0] + 0.05, pre_p[1], grasp_p[2] + 0.12])        # 1. raise from the shoulder, hand high near the body
    high = np.array([pre_p[0], pre_p[1], grasp_p[2] + 0.12])              # 2. reach forward high, above the table
    rb.speak("Raising the hand.")
    cart_move(rb, "left", up, x_dir, palm, speed=0.10, tol=0.05)
    rb.speak("Reaching forward.")
    cart_move(rb, "left", high, x_dir, palm, speed=0.08, tol=0.05)
    rb.speak("Lowering beside the can.")
    cart_move(rb, "left", pre_p, x_dir, palm, speed=0.05)                 # 3. down to the pre-grasp, 10 cm left of the can
    rb.speak(f"Pausing {int(PAUSE)} seconds. Check that the palm faces the can.")
    time.sleep(PAUSE)
    print("pre-grasp measured q", np.round(rb.arms.measured("left"), 2).tolist(), "tracking err", round(rb.arms.tracking_error("left"), 3), flush=True)
    # --- visual correction: hand and can observed in the same frame, with depth ---
    from g1_fetch.perception.localize import box_to_point
    from g1_fetch.skills.common import solve_pose
    fr = rb.camera.read()
    cv2.imwrite(OUT + "pregrasp_frame.jpg", fr.color, [cv2.IMWRITE_JPEG_QUALITY, 90])
    dets2 = rb.detector.detect(fr.color)
    cans2 = sorted([d for d in dets2 if d.label == "can"], key=lambda d: -d.conf)
    can2 = can_axis_from_box(fr, cans2[0], rb.frames, cfg) if cans2 else None
    hand_det = gemma_box(fr.color, "the robot's white hand", "hand")
    hand_obs = box_to_point(fr, hand_det, rb.frames, shrink=0.5) if hand_det is not None else None
    hand_fk = rb.kin.fk("left", rb.arms.cmd["left"])[:3, 3]
    print("pre-grasp check: can now", None if can2 is None else np.round(can2, 3).tolist(), "; hand observed", None if hand_obs is None else np.round(hand_obs, 3).tolist(),
          "box", None if hand_det is None else tuple(int(v) for v in hand_det.box), "; hand FK", np.round(hand_fk, 3).tolist(), flush=True)
    vis = fr.color.copy()
    for d, col in ((cans2[0] if cans2 else None, (255, 0, 0)), (hand_det, (0, 255, 0))):
        if d is not None: cv2.rectangle(vis, (int(d.box[0]), int(d.box[1])), (int(d.box[2]), int(d.box[3])), col, 2)
    cv2.imwrite(OUT + "pregrasp_boxes.jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if can2 is not None:
        p = can2; grasp_p = p + np.array([0.0, r + 0.01, DZ]); pre_p = grasp_p + np.array([0.0, 0.10, 0.0])
    cur = hand_fk.copy()
    if can2 is not None and hand_obs is not None:
        delta = (p + np.array([0.0, r + 0.01 + 0.10, DZ])) - hand_obs
        delta[1] = 0.0
        if np.linalg.norm(delta) < 0.08:
            print("correcting hand by", np.round(delta, 3).tolist(), "(x, z)", flush=True)
            cur = cur + delta
            cart_move(rb, "left", cur, x_dir, palm, speed=0.04, tol=0.04)
        else:
            print("correction", np.round(delta, 3).tolist(), "too large, ignored", flush=True)
    # --- contact-stop slide toward the can along -y ---
    rb.speak("Sliding onto the can.")
    base_err = rb.arms.tracking_error("left")
    goal_y = p[1] + r + 0.01 - 0.01
    q_prev = rb.arms.cmd["left"].copy(); contact = False; step = 0
    while cur[1] > goal_y:
        cur = cur + np.array([0.0, -0.01, 0.0]); step += 1
        q, res = solve_pose(rb, "left", cur, x_dir, palm, q_seed=q_prev, dir_weight=float(cfg.arm.ik_dir_weight))
        rb.arms.set_target("left", q); q_prev = q
        time.sleep(0.25)
        err = rb.arms.tracking_error("left")
        if err > base_err + 0.05:
            contact = True; print("contact at step", step, "y %.3f: tracking error %.3f vs base %.3f" % (cur[1], err, base_err), flush=True); break
    print("slide done: contact=%s steps=%d hand y %.3f goal %.3f" % (contact, step, cur[1], goal_y), flush=True)
    time.sleep(0.5)
    for q, dt in STAGES:
        hand.set(q); time.sleep(dt)
    closed = hand.closed_fraction(); target = float(np.mean(np.array(cfg.hand.grasp, dtype=float)[2:]))
    print(f"closure {closed:.2f} (command {target:.2f})", flush=True)
    if closed is None or closed > target - float(cfg.hand.get("grasp_margin", 0.08)):
        rb.speak("Missed the can."); hand.open(); print("MISSED")
        cart_move(rb, "left", pre_p, x_dir, palm, speed=0.05, tol=0.04); go_home(rb, "left", duration=2.5); sys.exit(4)
    rb.speak("Grasped. Lifting.")
    lifted = cur + np.array([0.0, 0.0, 0.05])
    cart_move(rb, "left", lifted, x_dir, palm, speed=0.04, tol=0.04)
    back = np.array([lifted[0] - 0.15, lifted[1] + 0.05, lifted[2] + 0.07])  # up and back over the table edge
    cart_move(rb, "left", back, x_dir, palm, speed=0.06, tol=0.05)
    print(f"GRASPED and lifted: closure now {hand.closed_fraction():.2f}", flush=True)
    rb.speak("I have the can. Please take it.")
    time.sleep(5.0)
    hand.set([0.0, 0.8, 0.0, 0.0, 0.0, 0.0]); time.sleep(1.0); hand.open(wait=True)
    go_home(rb, "left", duration=2.5)
    rb.speak("Done.")
except SkillFailed as e:
    print("SKILL FAILED:", e, flush=True); rb.speak("Grab failed.")
finally:
    try: rb.arms.disable()
    except Exception as e: print("disable failed:", e)
    rb.close()
    print("arm service on ->", set_arm_action_service(True))
