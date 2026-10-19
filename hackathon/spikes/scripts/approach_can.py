"""Step the robot (FSM 500) until the target can is detected inside the left hand's lane. Usage: python approach_can.py [--color white] [--max 10]
Lane: can 10-25 cm left of centre (aim 17), 32-40 cm ahead (aim 36). Exit 0 when in lane, 2 if never seen, 3 if max steps."""
import sys, re, base64, time, math
import numpy as np, cv2
sys.path.insert(0, "/home/unitree/g1-fetch"); sys.path.insert(0, "/home/unitree/harness/bench")
from client import timed_chat
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml"); cfg.cameras.head.enabled = False
def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
COLOR, MAXIT = arg("--color", "", str), int(arg("--max", 10))
Y_LO, Y_HI, Y_AIM, X_LO, X_HI, X_AIM = 0.10, 0.25, 0.17, 0.32, 0.40, 0.36
from g1_fetch.robot import build_robot
from g1_fetch.perception.detector import Detection
from g1_fetch.perception.localize import can_axis_from_box
from g1_fetch.control.robot_state import set_arm_action_service
OUT = "/home/unitree/spike/"
def b64_of(color_img):
    small = cv2.resize(color_img, (480, 336), interpolation=cv2.INTER_AREA); ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf.tobytes()).decode()
def gemma_box(color_img, what):
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64_of(color_img)}},
            {"type": "text", "text": "Detect " + what + ". Output only JSON: [{\"box_2d\": [ymin, xmin, ymax, xmax], \"label\": \"can\"}] with coordinates normalized to 0-1000."}]},
            {"role": "assistant", "content": "```json\n[\n  {\"box_2d\": ["}]
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 24, "chat_template_kwargs": {"enable_thinking": False}, "messages": msgs, "stop": ["]"]})
    txt = r["content"]; nums = [int(n) for n in re.findall(r"\d+", txt[txt.rindex("[") + 1:])][:4] if "[" in txt else []
    if len(nums) != 4: return None
    y1, x1, y2, x2 = nums; return (x1 / 1000 * 640, y1 / 1000 * 480, x2 / 1000 * 640, y2 / 1000 * 480)
def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1]); x2, y2 = min(a[2], b[2]), min(a[3], b[3]); inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return inter / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter + 1e-9)
SYN = {"white": {"white", "silver", "grey", "gray"}, "purple": {"purple", "violet", "magenta"}, "red": {"red"}, "green": {"green"}, "blue": {"blue"}, "black": {"black"}, "yellow": {"yellow", "gold"}, "orange": {"orange"}, "pink": {"pink"}}
def crop_colour(color_img, box):
    x1, y1, x2, y2 = [int(v) for v in box]; m = 10
    crop = color_img[max(0, y1 - m):min(480, y2 + m), max(0, x1 - m):min(640, x2 + m)]
    if crop.size == 0: return ""
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85]); b64 = base64.b64encode(buf.tobytes()).decode()
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 4, "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}, {"type": "text", "text": "What is the main colour of this can? Answer with one colour word."}]}]})
    return r["content"].strip().lower()
def find_target(rb, frame):
    cans = [d for d in rb.detector.detect(frame.color) if d.label == "can"]
    if not COLOR:
        return (max(cans, key=lambda d: d.conf) if cans else None), cans
    want = SYN.get(COLOR, {COLOR})
    verified = []
    for d in cans:
        c = crop_colour(frame.color, d.box); d.source = "colour:" + c
        if any(w in c for w in want): verified.append(d)
    print("   cans and their colours: %s" % [(tuple(int(v) for v in d.box), d.source) for d in cans], flush=True)
    if verified: return max(verified, key=lambda d: d.conf), cans
    return None, cans
def pulse(rb, vx, vy, t=0.6):
    t0 = time.time()
    while time.time() - t0 < t:
        rb.loco.set_velocity(vx, vy, 0.0); time.sleep(0.05)
    rb.loco.stop(); time.sleep(1.2)
def step_by(rb, dx, dy):
    """One odometry-checked step: up to 3 pulses toward (dx, dy) in the body frame at the start."""
    p0 = rb.loco.pose(); c, s_ = math.cos(-p0.yaw), math.sin(-p0.yaw)
    def moved():
        p = rb.loco.pose(); ex, ey = p.x - p0.x, p.y - p0.y; return c * ex - s_ * ey, s_ * ex + c * ey
    for _ in range(3):
        fx, fy = moved(); rx, ry = dx - fx, dy - fy
        if abs(rx) < 0.02 and abs(ry) < 0.02: break
        vx = 0.2 * np.sign(rx) if abs(rx) >= 0.02 else 0.0; vy = 0.2 * np.sign(ry) if abs(ry) >= 0.02 else 0.0
        pulse(rb, vx, vy, 0.6)
    fx, fy = moved(); print("   stepped forward %+.3f, left %+.3f (asked %+.3f, %+.3f)" % (fx, fy, dx, dy), flush=True)
rb = build_robot(cfg)
P_START = rb.loco.pose()
def moved_total(rb):
    p = rb.loco.pose(); return p.x - P_START.x, p.y - P_START.y
try:
    rb.speak("Looking for the %s can." % (COLOR or "can"))
    seen = False
    for it in range(MAXIT):
        for _ in range(3): frame = rb.camera.read()
        det, cans = find_target(rb, frame)
        p = can_axis_from_box(frame, det, rb.frames, cfg) if det is not None else None
        vis = frame.color.copy()
        for d in cans: cv2.rectangle(vis, (int(d.box[0]), int(d.box[1])), (int(d.box[2]), int(d.box[3])), (255, 0, 0), 2)
        if det is not None: cv2.rectangle(vis, (int(det.box[0]), int(det.box[1])), (int(det.box[2]), int(det.box[3])), (0, 255, 0), 3)
        cv2.imwrite(OUT + "approach_%d.jpg" % it, vis, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if det is not None and (det.box[0] < 5 or det.box[2] > 635):
            dy = 0.08 if det.box[0] < 5 else -0.08
            print("it %d: %s can touches the image edge; stepping %s to see it fully" % (it, COLOR or "target", "left" if dy > 0 else "right"), flush=True)
            rb.speak("Stepping %s." % ("left" if dy > 0 else "right")); step_by(rb, 0.0, dy); continue
        if p is None:
            # not seen: step toward an image edge where any can box touches, else toward the left
            dy = 0.08
            if cans:
                edge_left = any(d.box[0] < 5 for d in cans); edge_right = any(d.box[2] > 635 for d in cans)
                dy = 0.08 if edge_left or not edge_right else -0.08
            print("it %d: target not seen (%d can boxes); stepping %s" % (it, len(cans), "left" if dy > 0 else "right"), flush=True)
            rb.speak("Stepping %s." % ("left" if dy > 0 else "left" if dy > 0 else "right")); step_by(rb, 0.0, dy); continue
        seen = True
        in_lane = Y_LO <= p[1] <= Y_HI and X_LO <= p[0] <= X_HI
        print("it %d: %s can at pelvis %s (box %s) -> %s" % (it, COLOR or "target", np.round(p, 3).tolist(), tuple(int(v) for v in det.box), "IN LANE" if in_lane else "adjust"), flush=True)
        if in_lane:
            rb.speak("The %s can is in reach." % (COLOR or "")); print("IN LANE"); sys.exit(0)
        # The ROBOT must move opposite to the can's apparent error: a can too close (x < aim) needs a step BACK,
        # a can too far right (y < aim) needs a step RIGHT. (The first version had these signs inverted.)
        dy = float(np.clip(-(Y_AIM - p[1]), -0.12, 0.12)) if not (Y_LO <= p[1] <= Y_HI) else 0.0
        dx = float(np.clip(-(X_AIM - p[0]), -0.10, 0.10)) if not (X_LO <= p[0] <= X_HI) else 0.0
        # safety: never step forward while anything is within 0.30 m ahead in the lower half of the depth image, or the can is nearer than the lane minimum
        band = frame.depth[240:, 160:480]; near = float(np.percentile(band[band > 0], 5)) if (band > 0).any() else 9.9
        if dx > 0 and (p[0] < X_LO or near < 0.30):
            print("   forward step vetoed: can at %.2f m, nearest depth ahead %.2f m" % (p[0], near), flush=True); dx = 0.0
        total = math.hypot(*moved_total(rb))
        if total > 0.30:
            print("TOTAL DISPLACEMENT CAP %.2f m reached" % total, flush=True); rb.speak("I have moved as far as I am allowed."); sys.exit(3)
        if abs(dy) >= 0.02: rb.speak("Stepping %s." % ("left" if dy > 0 else "right")); step_by(rb, 0.0, dy)
        elif abs(dx) >= 0.02: rb.speak("Stepping %s." % ("forward" if dx > 0 else "back")); step_by(rb, dx, 0.0)
        else:
            print("   no safe step available; stopping", flush=True); rb.speak("I cannot adjust safely."); sys.exit(3)
    print("MAX STEPS" if seen else "NEVER SEEN"); sys.exit(3 if seen else 2)
finally:
    rb.close(); set_arm_action_service(True)
