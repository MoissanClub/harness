"""Arm ownership test in the stand: service switch timing, arm_sdk hold, a small right-arm motion, fade-out, service back on."""
import sys, time
import numpy as np
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
cfg = load_config("/home/unitree/g1-fetch/configs/pc2.yaml")
ChannelFactoryInitialize(0, str(cfg.network_interface))
from g1_fetch.control.arm import UnitreeArmStreamer
from g1_fetch.control.robot_state import set_arm_action_service
from g1_fetch.control.loco import UnitreeLoco
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
ac = AudioClient(); ac.SetTimeout(5.0); ac.Init()
def say(t): print("SAY:", t, flush=True); ac.TtsMaker(t, 1)
loco = UnitreeLoco(cfg); loco.start(); print("fsm_id", loco.fsm_id(), flush=True)
arms = UnitreeArmStreamer(cfg)
t0 = time.time()
while not arms._ready() and time.time() - t0 < 5: time.sleep(0.05)
q_before = {s: arms.measured(s).copy() for s in ("left", "right")}
print("measured before:", {s: np.round(v, 2).tolist() for s, v in q_before.items()}, flush=True)
say("Arm test. Switching the arm service off.")
t = time.perf_counter(); code = set_arm_action_service(False); dt_off = time.perf_counter() - t
time.sleep(1.0)
q_after = {s: arms.measured(s).copy() for s in ("left", "right")}
print(f"ServiceSwitch off -> code {code} in {dt_off*1000:.0f} ms; pose jump max {max(np.max(np.abs(q_after[s]-q_before[s])) for s in q_after):.3f} rad", flush=True)
arms.start()
say("Holding the pose.")
arms.enable()                       # 2 s ramp, holds measured
errs = []
for i in range(40):
    errs.append((arms.tracking_error("left"), arms.tracking_error("right"))); time.sleep(0.1)
print(f"hold 4 s: tracking error max left {max(e[0] for e in errs):.3f} right {max(e[1] for e in errs):.3f} rad; tau right {np.round(arms.measured_tau('right'), 2).tolist()}", flush=True)
say("Raising the right arm a little.")
q_r = arms.cmd["right"].copy(); q_up = q_r.copy(); q_up[0] -= 0.3
arms.move_to("right", q_up, 2.0); settled = arms.wait_settled("right", tol=0.05, timeout=2.0)
err_up = arms.tracking_error("right")
print(f"raised: settled={settled} tracking error {err_up:.3f} rad measured {np.round(arms.measured('right'), 2).tolist()}", flush=True)
time.sleep(1.0)
arms.move_to("right", q_r, 2.0); arms.wait_settled("right", tol=0.05, timeout=2.0)
print(f"back: tracking error {arms.tracking_error('right'):.3f} rad", flush=True)
say("Releasing the arms.")
arms.disable()
time.sleep(0.5)
t = time.perf_counter(); code = set_arm_action_service(True); dt_on = time.perf_counter() - t
time.sleep(1.0)
q_end = {s: arms.measured(s).copy() for s in ("left", "right")}
print(f"ServiceSwitch on -> code {code} in {dt_on*1000:.0f} ms; pose jump max {max(np.max(np.abs(q_end[s]-q_after[s])) for s in q_end):.3f} rad; fsm_id {loco.fsm_id()}", flush=True)
arms.close(); loco.close()
say("Arm test done.")
