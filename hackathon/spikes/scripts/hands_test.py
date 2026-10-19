"""BrainCo right-hand test on the robot: open -> (user places a can) -> grasp -> (user pulls) -> open, logging q and tau_est at ~100 Hz."""
import sys, time, csv
import numpy as np
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
cfg = load_config("/home/unitree/g1-fetch/configs/pc2.yaml")
ChannelFactoryInitialize(0, str(cfg.network_interface))
from g1_fetch.control.hand import UnitreeBraincoHand, N_FINGERS
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
ac = AudioClient(); ac.SetTimeout(5.0); ac.Init()
def say(t):
    print("SAY:", t, flush=True); ac.TtsMaker(t, 1)
right = UnitreeBraincoHand(cfg, "right")          # starts publishing the open target at 10 Hz
time.sleep(0.5)
rows = []
def log(phase, dur):
    t0 = time.time()
    while time.time() - t0 < dur:
        m = right._state_msg
        if m is not None:
            q = [float(m.states[i].q) for i in range(N_FINGERS)]
            tau = [float(getattr(m.states[i], "tau_est", float("nan"))) for i in range(N_FINGERS)]
            rows.append([round(time.time() - T0, 3), phase] + q + tau)
        time.sleep(0.01)
T0 = time.time()
print("grasp target:", cfg.hand.grasp, flush=True)
say("Hand test. Please place a can in my right hand within eight seconds.")
log("open_wait", 8)
right.grasp(wait=False); say("Closing.")
log("closing", 3)
say("Now pull the can out slowly.")
log("hold_pull", 8)
right.open(wait=False); say("Opening. Thank you.")
log("opening", 3)
right.close()
with open("/home/unitree/spike/hand_log.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["t", "phase"] + [f"q{i}" for i in range(6)] + [f"tau{i}" for i in range(6)]); w.writerows(rows)
print(f"samples: {len(rows)}")
for phase in ("open_wait", "closing", "hold_pull", "opening"):
    r = np.array([x[2:] for x in rows if x[1] == phase], dtype=float)
    if not len(r): continue
    q, tau = r[:, :6], r[:, 6:]
    print(f"{phase:10s} n={len(r):4d} closure(idx..pinky) mean {np.mean(q[:, 2:]):.2f} max {np.max(q[:, 2:]):.2f} | thumb {np.mean(q[:, 0]):.2f} | tau mean {np.nanmean(tau, axis=0).round(2).tolist()} max {np.nanmax(tau, axis=0).round(2).tolist()}")
