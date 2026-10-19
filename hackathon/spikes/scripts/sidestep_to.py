"""Closed-loop side-step by a target lateral distance using odometry: short pulses, re-measure after each. Usage: python sidestep_to.py --dy 0.12  (+ = robot's left)"""
import sys, time, math
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
cfg = load_config("/home/unitree/g1-fetch/configs/pc2.yaml")
def arg(name, default):
    return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
DY, PULSE, VY, MAXP = arg("--dy", 0.12), arg("--pulse", 0.7), arg("--vy", 0.2), int(arg("--max", 8))
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(0, str(cfg.network_interface))
from g1_fetch.control.loco import UnitreeLoco
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
ac = AudioClient(); ac.SetTimeout(5.0); ac.Init()
loco = UnitreeLoco(cfg); loco.start()
p0 = loco.pose(); c, s_ = math.cos(-p0.yaw), math.sin(-p0.yaw)
def moved():
    p = loco.pose(); dx, dy = p.x - p0.x, p.y - p0.y
    return c * dx - s_ * dy, s_ * dx + c * dy
ac.TtsMaker("Stepping %s." % ("left" if DY > 0 else "right"), 1); time.sleep(1.2)
for i in range(MAXP):
    fx, fy = moved(); rem = DY - fy
    print("pulse %d: so far left %+.3f, forward %+.3f, remaining %+.3f" % (i, fy, fx, rem), flush=True)
    if abs(rem) < 0.03: break
    vy = VY if rem > 0 else -VY
    t0 = time.time()
    while time.time() - t0 < PULSE:
        loco.set_velocity(0.0, vy, 0.0); time.sleep(0.05)
    loco.stop(); time.sleep(1.2)
fx, fy = moved(); print("done: left %+.3f m, forward %+.3f m (target left %+.3f)" % (fy, fx, DY), flush=True)
loco.close()
