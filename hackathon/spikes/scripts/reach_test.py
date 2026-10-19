"""Left-arm reach pose in the stand: service off, hold, move to a table-reach pose, hold 20 s for a tape measurement, return, fade out, service on."""
import sys, time
import numpy as np
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
cfg = load_config("/home/unitree/g1-fetch/configs/pc2.yaml")
ChannelFactoryInitialize(0, str(cfg.network_interface))
from g1_fetch.control.arm import UnitreeArmStreamer, ArmKinematics
from g1_fetch.control.robot_state import set_arm_action_service
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
REACH = [float(x) for x in (sys.argv[1:6] if len(sys.argv) >= 6 else [-0.5, 0.25, 0.0, 0.6, 0.0])]
ac = AudioClient(); ac.SetTimeout(5.0); ac.Init()
def say(t): print("SAY:", t, flush=True); ac.TtsMaker(t, 1)
kin = None
try:
    kin = ArmKinematics(cfg)
except Exception as e:
    print("kinematics unavailable:", e, flush=True)
def fk(q):
    if kin is None: return None
    try:
        out = kin.fk("left", np.asarray(q, dtype=float))
        return np.round(np.asarray(out), 3).tolist()
    except Exception as e:
        return f"fk failed: {e}"
arms = UnitreeArmStreamer(cfg)
t0 = time.time()
while not arms._ready() and time.time() - t0 < 5: time.sleep(0.05)
q_home = arms.measured("left").copy()
print("left measured now:", np.round(q_home, 2).tolist(), "fk:", fk(q_home), flush=True)
print("reach target:", REACH, "fk:", fk(REACH), flush=True)
say("Reach test. Switching the arm service off.")
code = set_arm_action_service(False); print("service off ->", code, flush=True)
time.sleep(0.5)
arms.start(); arms.enable()
say("Moving the left arm forward.")
arms.move_to("left", REACH, 3.0); settled = arms.wait_settled("left", tol=0.05, timeout=3.0)
q_reach = arms.measured("left").copy()
print(f"reach: settled={settled} error {arms.tracking_error('left'):.3f} measured {np.round(q_reach, 2).tolist()} tau {np.round(arms.measured_tau('left'), 2).tolist()} fk {fk(q_reach)}", flush=True)
say("Holding for twenty seconds. Please measure the height of my left hand above the floor.")
for i in range(20):
    time.sleep(1.0)
    if i == 10: say("Ten more seconds.")
print(f"after hold: error {arms.tracking_error('left'):.3f} measured {np.round(arms.measured('left'), 2).tolist()}", flush=True)
say("Returning.")
arms.move_to("left", q_home, 3.0); arms.wait_settled("left", tol=0.05, timeout=3.0)
print(f"back: error {arms.tracking_error('left'):.3f}", flush=True)
arms.disable(); time.sleep(0.5)
code = set_arm_action_service(True); print("service on ->", code, flush=True)
arms.close(); say("Reach test done.")
