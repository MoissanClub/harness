"""Wrist-roll sweep at the pre-grasp beside the can: the owner watches which roll puts the palm toward the can.
Usage: python roll_sweep.py [--rolls -1.5,-1.0,-0.5,0,0.5,1.0,1.5] [--hold 3] [--dx -0.05] [--dz 0.03]"""
import sys, time
import numpy as np, cv2
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml"); cfg.cameras.head.enabled = False; cfg.arm.ik_max_pos_err = 0.035
def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
ROLLS = [float(x) for x in arg("--rolls", "-1.5,-1.0,-0.5,0,0.5,1.0,1.5", str).split(",")]; HOLD = arg("--hold", 3.0); DX = arg("--dx", -0.05); DZ = arg("--dz", 0.03)
from g1_fetch.robot import build_robot
from g1_fetch.perception.localize import can_axis_from_box
from g1_fetch.skills.common import look_for, go_home, cart_move, SkillFailed
from g1_fetch.control.robot_state import set_arm_action_service
PALM, XDIR, R = np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]), float(cfg.fridge.can_diameter_m) / 2
OUT = "/home/unitree/spike/"
cam3 = cv2.VideoCapture("/dev/video6", cv2.CAP_V4L2); cam3.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")); cam3.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cam3.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
for _ in range(8): cam3.read()
def shot(name):
    for _ in range(3): ok, fr = cam3.read()
    if ok: cv2.imwrite(OUT + "roll_" + name + ".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
rb = build_robot(cfg)
try:
    det, frame = look_for(rb, "can", max_frames=8)
    if det is None: rb.speak("No can."); sys.exit(2)
    p = can_axis_from_box(frame, det, rb.frames, cfg)
    grasp = p + np.array([DX, R + 0.01, DZ]); pre = grasp + np.array([0.0, 0.10, 0.0])
    rb.arms.enable(); rb.hands["left"].open(wait=False); go_home(rb, "left", duration=2.0)
    home_p = rb.kin.fk("left", rb.arms.measured("left"))[:3, 3]
    up = np.array([home_p[0] + 0.05, pre[1], grasp[2] + 0.12]); high = np.array([pre[0], pre[1], grasp[2] + 0.12])
    rb.speak("Roll sweep. Raising."); cart_move(rb, "left", up, XDIR, PALM, speed=0.10, tol=0.05)
    rb.speak("Reaching."); cart_move(rb, "left", high, XDIR, PALM, speed=0.08, tol=0.05)
    rb.speak("Lowering beside the can."); cart_move(rb, "left", pre, XDIR, PALM, speed=0.05, tol=0.035)
    q0 = rb.arms.cmd["left"].copy(); print("pre-grasp q", np.round(q0, 2).tolist(), "wrist roll from IK", round(float(q0[4]), 2), flush=True)
    for roll in ROLLS:
        q = q0.copy(); q[4] = roll
        rb.arms.move_to("left", q, 1.0); time.sleep(0.5)
        rb.speak("Roll %s" % (("%.1f" % roll).replace("-", "minus ").replace(".0", "")))
        time.sleep(HOLD); shot("%+.1f" % roll)
        print("roll %+.1f measured wrist %.2f" % (roll, rb.arms.measured("left")[4]), flush=True)
    rb.arms.move_to("left", q0, 1.0)
    rb.speak("Sweep done. Retreating.")
    m = rb.kin.fk("left", rb.arms.measured("left"))[:3, 3]
    cart_move(rb, "left", np.array([m[0], m[1] + 0.05, grasp[2] + 0.12]), XDIR, PALM, speed=0.08, tol=0.05)
    cart_move(rb, "left", up, XDIR, PALM, speed=0.08, tol=0.05); go_home(rb, "left", duration=2.5)
except SkillFailed as e:
    print("SKILL FAILED:", e)
finally:
    try: rb.arms.disable()
    except Exception as e: print("disable failed:", e)
    rb.close(); cam3.release(); print("arm service on ->", set_arm_action_service(True))
