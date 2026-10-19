"""One parametrized tabletop grasp trial with the left hand, logged as a JSON line. Reuses g1-fetch.
Usage: python grab_loop.py [--dry] [--dx 0.0] [--dz 0.03] [--press 0.02] [--contact 0.03] [--order thumb|fingers]
                           [--tol 0.035] [--pause 4] [--no-servo] [--note text]
dx: palm centre x offset relative to the can axis (+ = palm further forward); dz: palm centre above the can mid-height;
press: slide this far past the can's near surface; contact: tracking-error rise (rad) that counts as contact.
Retreat always goes up first (never straight down into the table)."""
import sys, re, base64, time, json, logging
import numpy as np, cv2
sys.path.insert(0, "/home/unitree/g1-fetch"); sys.path.insert(0, "/home/unitree/harness/bench")
logging.basicConfig(level=logging.WARNING)
from client import timed_chat
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml")
def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
DRY = "--dry" in sys.argv; SERVO = "--no-servo" not in sys.argv
DX, DZ, PRESS, CONTACT = arg("--dx", 0.0), arg("--dz", 0.03), arg("--press", 0.02), arg("--contact", 0.03)
ORDER, TOL, PAUSE, NOTE = arg("--order", "thumb", str), arg("--tol", 0.035), arg("--pause", 4.0), arg("--note", "", str)
DIAM = arg("--diam", 0.0); PRETHUMB = "--prethumb" in sys.argv   # 0 = measure from the box and depth
COLOR = arg("--color", "", str); PREOFF = arg("--pre", 0.10)
cfg.fridge.can_diameter_m = DIAM
cfg.arm.ik_max_pos_err = TOL
cfg.cameras.head.enabled = False        # the SR300 head camera is gone; the C922 is the third-person view
from g1_fetch.robot import build_robot
from g1_fetch.perception.localize import can_axis_from_box
from g1_fetch.skills.common import look_for, go_home, cart_move, solve_pose, SkillFailed
from g1_fetch.control.robot_state import set_arm_action_service
OUT = "/home/unitree/spike/"; LOG = OUT + "grab_trials.jsonl"; STAMP = time.strftime("%H%M%S")
CAM3 = None
def cam3_open():
    global CAM3
    try:
        CAM3 = cv2.VideoCapture("/dev/video6", cv2.CAP_V4L2)
        CAM3.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")); CAM3.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); CAM3.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        for _ in range(8): CAM3.read()
    except Exception as e:
        print("cam3 open failed:", e); CAM3 = None
def cam3_shot(stage):
    """Third-person frame saved as trial_<stamp>_<stage>.jpg; returns the path or None."""
    if CAM3 is None: return None
    for _ in range(3): ok, fr = CAM3.read()
    if not ok: return None
    path = OUT + "trial_" + STAMP + "_" + stage + ".jpg"
    cv2.imwrite(path, fr, [cv2.IMWRITE_JPEG_QUALITY, 85]); trial.setdefault("cam3", []).append(path); return path
def gemma_yesno(path, question):
    small = cv2.resize(cv2.imread(path), (480, 336), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85]); b64 = base64.b64encode(buf.tobytes()).decode()
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 3,
         "chat_template_kwargs": {"enable_thinking": False}, "messages": [{"role": "user", "content": [
         {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}, {"type": "text", "text": question + " Answer with one word: yes or no."}]}]})
    return r["content"].strip().lower()

PALM, XDIR = np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]); R = DIAM / 2
STAGES = {"thumb": (([0.0, 0.8, 0, 0, 0, 0], 1.0), ([0.0, 0.8, 0.9, 0.9, 0.9, 0.9], 1.5), ([0.9, 0.8, 0.9, 0.9, 0.9, 0.9], 1.0)),
          "fingers": (([0.0, 0.0, 0.9, 0.9, 0.9, 0.9], 1.5), ([0.9, 0.8, 0.9, 0.9, 0.9, 0.9], 1.5))}[ORDER]
trial = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "params": {"dx": DX, "dz": DZ, "press": PRESS, "contact": CONTACT, "order": ORDER, "servo": SERVO, "tol": TOL, "diam": DIAM, "prethumb": PRETHUMB, "color": COLOR, "pre": PREOFF}, "note": NOTE}

def hand_meas(rb):  # real palm position from the measured joints
    return rb.kin.fk("left", rb.arms.measured("left"))[:3, 3]

def move(rb, goal, speed, tol=0.04, servo=True, label=""):
    """Cartesian move, then up to two proprioceptive corrections so the MEASURED hand reaches the goal."""
    goal = np.asarray(goal, float)
    cart_move(rb, "left", goal, XDIR, PALM, speed=speed, tol=tol)
    time.sleep(0.4)
    cmd = goal.copy()
    for i in range(2 if servo else 0):
        err = goal - hand_meas(rb)
        if np.linalg.norm(err) < 0.008: break
        cmd = cmd + err
        q, res = solve_pose(rb, "left", cmd, XDIR, PALM, q_seed=rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
        rb.arms.set_target("left", q); time.sleep(0.6)
    m = hand_meas(rb)
    print(f"{label}: goal {np.round(goal, 3).tolist()} measured {np.round(m, 3).tolist()} err {np.linalg.norm(goal - m):.3f}", flush=True)
    return m

from g1_fetch.perception.localize import median_depth
from g1_fetch.perception.detector import Detection
def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1]); x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return inter / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter + 1e-9)
def gemma_box(color_img, what):
    small = cv2.resize(color_img, (480, 336), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85]); b64 = base64.b64encode(buf.tobytes()).decode()
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            {"type": "text", "text": "Detect " + what + ". Output only JSON: [{\"box_2d\": [ymin, xmin, ymax, xmax], \"label\": \"can\"}] with coordinates normalized to 0-1000."}]},
            {"role": "assistant", "content": "```json\n[\n  {\"box_2d\": ["}]
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 24,
                   "chat_template_kwargs": {"enable_thinking": False}, "messages": msgs, "stop": ["]"]})
    txt = r["content"]; nums = [int(n) for n in re.findall(r"\d+", txt[txt.rindex("[") + 1:])][:4] if "[" in txt else []
    if len(nums) != 4: return None, r["total_s"]
    y1, x1, y2, x2 = nums
    return (x1 / 1000 * 640, y1 / 1000 * 480, x2 / 1000 * 640, y2 / 1000 * 480), r["total_s"]
def gemma_gate(color_img, question):
    small = cv2.resize(color_img, (480, 336), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85]); b64 = base64.b64encode(buf.tobytes()).decode()
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 3,
         "chat_template_kwargs": {"enable_thinking": False}, "messages": [{"role": "system", "content": "You are a robot's vision module. Image left/right are robot left/right."},
         {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}, {"type": "text", "text": question + " Answer with one word: yes or no."}]}]})
    return r["content"].strip().lower(), r["total_s"]
def detect(rb):
    det, frame = look_for(rb, "can", max_frames=8)
    if COLOR:
        dets = rb.detector.detect(frame.color); cans = [d for d in dets if d.label == "can"]
        ans, t1 = gemma_gate(frame.color, "Is there a %s can in the image?" % COLOR)
        trial["gate_%s" % COLOR] = ans
        print("Gemma gate for a %s can: %r (%.2fs); YOLOE sees %d can(s)" % (COLOR, ans, t1, len(cans)), flush=True)
        if ans.startswith("no"):
            rb.speak("I do not see a %s can." % COLOR); return None, frame
        gbox, t2 = gemma_box(frame.color, "the %s can" % COLOR)
        print("Gemma box for the %s can: %s (%.2fs)" % (COLOR, None if gbox is None else tuple(int(v) for v in gbox), t2), flush=True)
        if gbox is None:
            rb.speak("I could not locate the %s can." % COLOR); return None, frame
        SYN = {"white": {"white", "silver", "grey", "gray"}, "purple": {"purple", "violet", "magenta"}, "red": {"red"}, "green": {"green"}, "blue": {"blue"}, "black": {"black"}, "yellow": {"yellow", "gold"}, "orange": {"orange"}, "pink": {"pink"}}
        want = SYN.get(COLOR, {COLOR})
        def crop_colour(box):
            x1, y1, x2, y2 = [int(v) for v in box]; m = 10
            crop = frame.color[max(0, y1 - m):min(480, y2 + m), max(0, x1 - m):min(640, x2 + m)]
            if crop.size == 0: return ""
            ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85]); cb64 = base64.b64encode(buf.tobytes()).decode()
            rr = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 4, "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + cb64}}, {"type": "text", "text": "What is the main colour of this can? Answer with one colour word."}]}]})
            return rr["content"].strip().lower()
        colours = [(d, crop_colour(d.box)) for d in cans]
        print("colour check: %s" % [(tuple(int(v) for v in d.box), c) for d, c in colours], flush=True); trial["colour_check"] = [c for _, c in colours]
        verified = [d for d, c in colours if any(w in c for w in want)]
        if not verified:
            seen = sorted({c.split()[0] for _, c in colours if c})
            msg = "I do not see a %s can. I see %s." % (COLOR, " and ".join(seen)) if seen else "I do not see any can."
            rb.speak(msg); print("NO %s CAN (colour check); seen: %s" % (COLOR.upper(), seen)); return None, frame
        best = max(verified, key=lambda d: iou(d.box, gbox))
        det = best; src = "YOLOE box, colour verified '%s', Gemma box IoU %.2f" % (best.source if False else next(c for d, c in colours if d is best), iou(best.box, gbox))
        print("target: " + src, flush=True); trial["target_source"] = src
        vis = frame.color.copy()
        for d in cans: cv2.rectangle(vis, (int(d.box[0]), int(d.box[1])), (int(d.box[2]), int(d.box[3])), (255, 0, 0), 2)
        cv2.rectangle(vis, (int(gbox[0]), int(gbox[1])), (int(gbox[2]), int(gbox[3])), (0, 255, 0), 2)
        cv2.imwrite(OUT + "trial_" + STAMP + "_headcam_boxes.jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if det is None: return None, frame
    z = median_depth(frame, det.box, 0.5)
    if z is not None:
        w_m = det.width * z / frame.intrinsics.fx; h_m = det.height * z / frame.intrinsics.fy
        trial["can_size_m"] = [round(float(w_m), 3), round(float(h_m), 3)]
        print("can box %dx%d px at %.2f m -> width %.3f m, height %.3f m" % (det.width, det.height, z, w_m, h_m), flush=True)
    return can_axis_from_box(frame, det, rb.frames, cfg), frame

rb = build_robot(cfg)
cam3_open()
try:
    hand = rb.hands["left"]
    cam3_shot("start")
    p, frame = detect(rb)
    if p is None:
        rb.speak("No can."); trial["result"] = "no_can"; print("NO CAN"); sys.exit(2)
    trial["can_before"] = np.round(p, 3).tolist()
    if DIAM <= 0:
        w = trial.get("can_size_m", [0.066])[0]
        DIAM = 0.055 if w < 0.060 else 0.066; R = DIAM / 2; cfg.fridge.can_diameter_m = DIAM
        print("can class: %s (measured width %.3f m) -> diameter %.3f" % ("slim" if DIAM < 0.06 else "regular", w, DIAM), flush=True)
    trial["params"]["diam"] = DIAM
    grasp = p + np.array([DX, R + 0.01, DZ]); pre = grasp + np.array([0.0, PREOFF, 0.0])
    res = rb.kin.ik("left", grasp, XDIR, q_seed=rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
    print(f"can {np.round(p, 3).tolist()} (floor {rb.frames.floor_height(p):.2f} m); grasp {np.round(grasp, 3).tolist()} IK err {res.pos_err:.3f}", flush=True)
    trial["ik_err"] = round(float(res.pos_err), 4)
    if DRY: sys.exit(0)
    if res.pos_err > TOL:
        rb.speak("Out of reach."); trial["result"] = "unreachable"; sys.exit(3)
    if p[1] < 0.06:
        rb.speak("That can is too close to my centre line for my left hand. Please move it to my left."); trial["result"] = "outside_lane"; print("OUTSIDE LANE: can y %.3f" % p[1]); sys.exit(3)
    if p[1] > 0.30:
        rb.speak("That can is too far to my left. Please move it closer to my centre."); trial["result"] = "outside_lane"; print("OUTSIDE LANE: can y %.3f" % p[1]); sys.exit(3)
    rb.arms.enable(); hand.open(wait=False); rb.hands["right"].open(wait=False)
    go_home(rb, "left", duration=2.0)
    home_p = hand_meas(rb)
    up = np.array([home_p[0] + 0.05, pre[1], grasp[2] + 0.12]); high = np.array([pre[0], pre[1], grasp[2] + 0.12])
    rb.speak("Raising."); move(rb, up, 0.10, servo=False, label="up")
    rb.speak("Reaching."); move(rb, high, 0.08, servo=False, label="high")
    rb.speak("Lowering beside the can."); m_pre = move(rb, pre, 0.05, tol=TOL, servo=SERVO, label="pre")
    trial["pre_measured"] = np.round(m_pre, 3).tolist()
    cam3_shot("pregrasp")
    time.sleep(PAUSE)
    # contact-stop slide along -y, 1 cm steps, goal = can surface + press
    if PRETHUMB:
        hand.set([0.0, 0.8, 0.0, 0.0, 0.0, 0.0]); rb.speak("Thumb first."); time.sleep(1.2)
    rb.speak("Sliding."); base = rb.arms.tracking_error("left")
    cur = pre.copy(); goal_y = p[1] + R - PRESS; contact = False; step = 0; why = ""
    lag0 = float(hand_meas(rb)[1] - cur[1])
    while cur[1] > goal_y:
        cur[1] = max(goal_y, cur[1] - 0.01); step += 1
        q, res = solve_pose(rb, "left", cur, XDIR, PALM, q_seed=rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
        rb.arms.set_target("left", q); time.sleep(0.25)
        err = rb.arms.tracking_error("left"); lag = float(hand_meas(rb)[1] - cur[1]) - lag0
        if err > base + CONTACT:
            contact = True; why = "tracking error %.3f > base %.3f + %.3f" % (err, base, CONTACT); break
        if lag > 0.012:
            contact = True; why = "hand lags the command by %.3f m in y" % lag; break
    print("contact reason:", why or "none", flush=True)
    m_slide = hand_meas(rb)
    print(f"slide: steps {step} contact {contact} (err base {base:.3f} now {rb.arms.tracking_error('left'):.3f}) cmd y {cur[1]:.3f} measured {np.round(m_slide, 3).tolist()}", flush=True)
    trial.update(slide_steps=step, contact=contact, slide_measured=np.round(m_slide, 3).tolist())
    cam3_shot("slide")
    time.sleep(0.3)
    for q6, dt in (STAGES[1:] if PRETHUMB and ORDER == "thumb" else STAGES): hand.set(q6); time.sleep(dt)
    cam3_shot("closed")
    closed = hand.closed_fraction(); state = hand.state()
    trial["closure"] = round(float(closed), 3); trial["hand_state"] = np.round(state, 2).tolist()
    fingers = state[2:] if state is not None else None
    grasped = fingers is not None and all(0.15 < f < 0.82 for f in fingers)   # every finger stalled on the can, none fully closed or blocked open
    print(f"closure {closed:.2f} state {np.round(state, 2).tolist()} -> {'GRASPED' if grasped else 'MISSED'}", flush=True)
    trial["result"] = "grasped" if grasped else "missed"
    if grasped:
        rb.speak("Grasped. Lifting."); m_lift = move(rb, m_slide + np.array([0.0, 0.0, 0.06]), 0.04, servo=True, label="lift")
        time.sleep(1.0); trial["closure_after_lift"] = round(float(hand.closed_fraction()), 3); shot = cam3_shot("lifted")
        if shot:
            v = gemma_yesno(shot, "Is the robot holding the soda can in its hand, off the table?"); trial["gemma_in_hand"] = v; print("Gemma on the third-person view after the lift, can in hand:", v, flush=True)
        move(rb, m_lift + np.array([-0.12, 0.03, 0.06]), 0.06, servo=False, label="back-up")
        rb.speak("I have the can. Please take it."); time.sleep(5.0)
        hand.set([0.0, 0.8, 0, 0, 0, 0]); time.sleep(1.0); hand.open(wait=True)
    else:
        rb.speak("Missed."); hand.open(wait=True)
    # retreat: up first, then back, then home
    m = hand_meas(rb)
    move(rb, np.array([m[0], m[1] + 0.05, grasp[2] + 0.12]), 0.08, servo=False, label="retreat-up")
    move(rb, np.array([home_p[0] + 0.05, pre[1], grasp[2] + 0.12]), 0.08, servo=False, label="retreat-back")
    go_home(rb, "left", duration=2.5)
    cam3_shot("end")
    p2, _ = detect(rb)
    trial["can_after"] = None if p2 is None else np.round(p2, 3).tolist()
    print("can after:", trial["can_after"], flush=True)
except SkillFailed as e:
    print("SKILL FAILED:", e, flush=True); trial["result"] = "skill_failed: " + str(e)
finally:
    with open(LOG, "a") as f: f.write(json.dumps(trial) + "\n")
    try: rb.arms.disable()
    except Exception as e: print("disable failed:", e)
    rb.close()
    if CAM3 is not None: CAM3.release()
    print("arm service on ->", set_arm_action_service(True), "| trial logged:", json.dumps(trial), flush=True)
