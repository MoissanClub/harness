"""Tabletop see-and-grab with the left hand, reusing g1-fetch. Usage: python grab_tabletop.py [--dry]
--dry: detect, localize and check IK only (no motion). Without it: pre-grasp, approach, staged grasp, lift, retract, carry, offer, release, home."""
import sys, re, base64, time, logging
import numpy as np, cv2
sys.path.insert(0, "/home/unitree/g1-fetch"); sys.path.insert(0, "/home/unitree/harness/bench")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
from client import timed_chat
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml")
from g1_fetch.robot import build_robot
from g1_fetch.perception.detector import Detection
from g1_fetch.perception.localize import can_axis_from_box
from g1_fetch.skills import grab_can as gc
from g1_fetch.skills.common import look_for, go_home, SkillFailed
from g1_fetch.control.robot_state import set_arm_action_service
DRY = "--dry" in sys.argv
TOL = float(sys.argv[sys.argv.index("--tol") + 1]) if "--tol" in sys.argv else float(cfg.arm.ik_max_pos_err)
cfg.arm.ik_max_pos_err = TOL
OUT = "/home/unitree/spike/"
STAGES = ([0.0, 0.8, 0.0, 0.0, 0.0, 0.0], 1.0), ([0.0, 0.8, 0.9, 0.9, 0.9, 0.9], 1.5), ([0.9, 0.8, 0.9, 0.9, 0.9, 0.9], 1.0)

def no_walk_reachable(rb, side, p_goal, x_dir, max_nudge=0.0, tries=0):
    res = rb.kin.ik(side, np.asarray(p_goal, float), x_dir, q_seed=rb.arms.cmd[side], dir_weight=float(rb.cfg.arm.ik_dir_weight))
    if res.pos_err > TOL:
        raise SkillFailed(f"{side} hand cannot reach {np.round(p_goal, 3)} (err {res.pos_err:.3f} m); not walking in the stand")
    return np.asarray(p_goal, float)
gc.ensure_reachable = no_walk_reachable          # never let the skill walk

def gemma_box(color):
    small = cv2.resize(color, (480, 336), interpolation=cv2.INTER_AREA)
    cv2.imwrite(OUT + "grab_480x336.jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(open(OUT + "grab_480x336.jpg", "rb").read()).decode()
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            {"type": "text", "text": 'Detect the soda can. Output only JSON: [{"box_2d": [ymin, xmin, ymax, xmax], "label": "soda can"}] with coordinates normalized to 0-1000.'}]},
            {"role": "assistant", "content": '```json\n[\n  {"box_2d": ['}]
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 24,
                   "chat_template_kwargs": {"enable_thinking": False}, "messages": msgs, "stop": ["]"]})
    txt = r["content"]
    nums = [int(n) for n in re.findall(r"\d+", txt[txt.rindex("[") + 1:])][:4] if "[" in txt else []
    print(f"Gemma box {nums} ({r['total_s']:.2f}s)", flush=True)
    if len(nums) != 4: return None
    y1, x1, y2, x2 = nums
    return Detection("can", 1.0, (x1 / 1000 * 640, y1 / 1000 * 480, x2 / 1000 * 640, y2 / 1000 * 480), "gemma")

rb = build_robot(cfg)                            # arm service off, detector warm, camera open, loco + arms started (needs FSM 500)
try:
    hand = rb.hands["left"]
    def staged_grasp(wait=True):
        for q, dt in STAGES:
            hand.set(q); time.sleep(dt)
    hand.grasp = staged_grasp
    rb.speak("Table grab test. Looking for the can.")
    det, frame = look_for(rb, "can", max_frames=10)
    src = "yoloe"
    if det is None:
        det = gemma_box(frame.color); src = "gemma"
    if det is None:
        rb.speak("I do not see a can."); print("NO CAN"); sys.exit(2)
    p = can_axis_from_box(frame, det, rb.frames, cfg)
    if p is None:
        rb.speak("No depth on the can."); print("NO DEPTH"); sys.exit(2)
    vis = frame.color.copy(); b = det.box; cv2.rectangle(vis, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 255, 0), 2)
    cv2.imwrite(OUT + "grab_seen.jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 90])
    palm, x_dir, r = np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]), float(cfg.fridge.can_diameter_m) / 2
    hand_p = p - palm * (r + 0.01)
    res = rb.kin.ik("left", hand_p, x_dir, q_seed=rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
    print(f"CAN via {src} conf {det.conf:.2f} box {tuple(int(v) for v in det.box)}: axis pelvis {np.round(p, 3).tolist()} floor height {rb.frames.floor_height(p):.2f} m; "
          f"hand target {np.round(hand_p, 3).tolist()}; IK ok={res.ok} pos_err={res.pos_err:.3f} dir_err={getattr(res, 'dir_err', float('nan')):.3f} q={np.round(res.q, 2).tolist()}", flush=True)
    if DRY:
        rb.speak("Dry run done."); sys.exit(0)
    if res.pos_err > TOL:
        rb.speak("Out of reach."); sys.exit(3)
    rb.speak("Reaching.")
    rb.arms.enable()
    for side in ("left", "right"): rb.hands[side].open(wait=False)
    go_home(rb, "left", duration=2.0)
    t0 = time.time()
    gc.grab_can(rb, p)                            # pre-grasp, approach, staged grasp + closure check, lift, retract, carry
    closed = hand.closed_fraction()
    print(f"GRASPED: closure {closed:.2f}, {time.time()-t0:.1f}s from reach start; carrying", flush=True)
    rb.speak("I have the can.")
    time.sleep(4.0)
    rb.speak("Please take the can.")
    home_q = np.array(cfg.arm.home_q.left, dtype=float); offer = home_q.copy(); offer[0] -= 0.5; offer[3] = 0.6
    rb.arms.move_to("left", offer, 2.5); time.sleep(3.0)
    hand.set([0.0, 0.8, 0.0, 0.0, 0.0, 0.0]); time.sleep(1.0); hand.open(wait=True)
    go_home(rb, "left", duration=2.5)
    rb.speak("Done.")
except SkillFailed as e:
    print("SKILL FAILED:", e, flush=True); rb.speak("Grab failed.")
finally:
    try:
        rb.arms.disable()
    except Exception as e:
        print("disable failed:", e)
    rb.close()
    print("arm service on ->", set_arm_action_service(True))
