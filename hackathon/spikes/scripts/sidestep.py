"""Side-step the robot in FSM 500 via g1-fetch's UnitreeLoco. Usage: python sidestep.py [--vy -0.2] [--t 0.6]  (vy < 0 = robot's right)"""
import sys, time, math
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
cfg = load_config("/home/unitree/g1-fetch/configs/pc2.yaml")
def arg(name, default):
    return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
VY, T = arg("--vy", -0.2), arg("--t", 0.6)
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(0, str(cfg.network_interface))
from g1_fetch.control.loco import UnitreeLoco
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
ac = AudioClient(); ac.SetTimeout(5.0); ac.Init()
loco = UnitreeLoco(cfg); loco.start()
p0 = loco.pose(); print("fsm", loco.fsm_id(), "pose before", p0, flush=True)
ac.TtsMaker("Stepping %s." % ("right" if VY < 0 else "left"), 1); time.sleep(1.2)
t0 = time.time()
while time.time() - t0 < T:
    loco.set_velocity(0.0, VY, 0.0); time.sleep(0.05)
loco.stop(); time.sleep(1.5)
p1 = loco.pose()
# displacement in the robot's own frame at the start
dx, dy = p1.x - p0.x, p1.y - p0.y
c, s_ = math.cos(-p0.yaw), math.sin(-p0.yaw)
bx, by = c * dx - s_ * dy, s_ * dx + c * dy
print("pose after", p1, flush=True)
print("moved in body frame: forward %+.3f m, left %+.3f m, yaw %+.1f deg" % (bx, by, math.degrees(p1.yaw - p0.yaw)), flush=True)
loco.close()
