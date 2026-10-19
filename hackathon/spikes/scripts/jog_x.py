"""Calibrate the palm's forward offset: hand parked 10 cm left of the can, palm starting 18 cm behind the can axis, stepping forward 2 cm per announced step.
Usage: python jog_x.py [--start -0.18] [--step 0.02] [--n 8] [--hold 3] [--diam 0.055]"""
import sys, time
import numpy as np, cv2
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml"); cfg.cameras.head.enabled = False; cfg.arm.ik_max_pos_err = 0.035
def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
START, STEP, N, HOLD, DIAM, DZ = arg("--start", -0.18), arg("--step", 0.02), arg("--n", 8, int), arg("--hold", 3.0), arg("--diam", 0.055), arg("--dz", 0.03)
from g1_fetch.robot import build_robot
from g1_fetch.perception.localize import can_axis_from_box
from g1_fetch.skills.common import look_for, go_home, cart_move, solve_pose, SkillFailed
from g1_fetch.control.robot_state import set_arm_action_service
PALM, XDIR, R = np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]), DIAM / 2
OUT = "/home/unitree/spike/"
cam3 = cv2.VideoCapture("/dev/video6", cv2.CAP_V4L2); cam3.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")); cam3.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cam3.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
for _ in range(8): cam3.read()
def shot(name):
    for _ in range(3): ok, fr = cam3.read()
    if ok: cv2.imwrite(OUT + "jog_" + name + ".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
def meas(rb): return rb.kin.fk("left", rb.arms.measured("left"))[:3, 3]
def goto(rb, goal, speed, servo=True):
    cart_move(rb, "left", goal, XDIR, PALM, speed=speed, tol=0.05); time.sleep(0.4)
    cmd = np.asarray(goal, float).copy()
    for _ in range(2 if servo else 0):
        err = goal - meas(rb)
        if np.linalg.norm(err) < 0.008: break
        cmd = cmd + err
        q, _ = solve_pose(rb, "left", cmd, XDIR, PALM, q_seed=rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight)); rb.arms.set_target("left", q); time.sleep(0.6)
rb = build_robot(cfg)
try:
    det, frame = look_for(rb, "can", max_frames=8)
    if det is None: rb.speak("No can."); sys.exit(2)
    p = can_axis_from_box(frame, det, rb.frames, cfg)
    print("can", np.round(p, 3).tolist(), flush=True)
    side_y = p[1] + R + 0.01 + 0.10; z = p[2] + DZ
    rb.arms.enable(); rb.hands["left"].open(wait=False); go_home(rb, "left", duration=2.0)
    home_p = meas(rb)
    rb.speak("Calibration jog. Raising."); goto(rb, np.array([home_p[0] + 0.05, side_y, z + 0.12]), 0.10, servo=False)
    rb.speak("Reaching."); goto(rb, np.array([p[0] + START, side_y, z + 0.12]), 0.08, servo=False)
    rb.speak("Lowering."); goto(rb, np.array([p[0] + START, side_y, z]), 0.05)
    rb.hands["left"].set([0.0, 0.8, 0.0, 0.0, 0.0, 0.0]); time.sleep(1.0)       # thumb opposed, like the grasp
    for i in range(N + 1):
        x = p[0] + START + i * STEP
        goto(rb, np.array([x, side_y, z]), 0.04)
        m = meas(rb); rb.speak("Step %d" % i); shot("step%d" % i)
        print("step %d: palm x offset %+.3f from the can axis; measured hand %s" % (i, m[0] - p[0], np.round(m, 3).tolist()), flush=True)
        time.sleep(HOLD)
    rb.speak("Jog done. Retreating.")
    rb.hands["left"].open(wait=False)
    m = meas(rb); goto(rb, np.array([m[0], side_y + 0.05, z + 0.12]), 0.08, servo=False)
    goto(rb, np.array([home_p[0] + 0.05, side_y, z + 0.12]), 0.08, servo=False); go_home(rb, "left", duration=2.5)
except SkillFailed as e:
    print("SKILL FAILED:", e)
finally:
    try: rb.arms.disable()
    except Exception as e: print("disable failed:", e)
    rb.close(); cam3.release(); print("arm service on ->", set_arm_action_service(True))
