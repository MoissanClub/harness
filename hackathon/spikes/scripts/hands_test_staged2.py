"""Left-hand staged grasp: thumb into opposition first, then fingers; staged release. Logs q and tau_est at ~100 Hz."""
import sys, time, csv
import numpy as np
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
cfg = load_config("/home/unitree/g1-fetch/configs/pc2.yaml")
ChannelFactoryInitialize(0, str(cfg.network_interface))
from g1_fetch.control.hand import UnitreeBraincoHand, N_FINGERS
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
SIDE = sys.argv[1] if len(sys.argv) > 1 else "left"
THUMB_PRE = [0.0, 0.8, 0.0, 0.0, 0.0, 0.0]        # thumb rotated into opposition, thumb joint still open
FINGERS = [0.0, 0.8, 0.9, 0.9, 0.9, 0.9]
GRASP = [0.9, 0.8, 0.9, 0.9, 0.9, 0.9]
RELEASE_FINGERS = [0.0, 0.8, 0.0, 0.0, 0.0, 0.0]   # fingers and thumb open first, thumb still opposed
OPEN = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
ac = AudioClient(); ac.SetTimeout(5.0); ac.Init()
def say(t): print("SAY:", t, flush=True); ac.TtsMaker(t, 1)
hand = UnitreeBraincoHand(cfg, SIDE); time.sleep(0.5)
rows = []; T0 = time.time()
def log(phase, dur):
    t0 = time.time()
    while time.time() - t0 < dur:
        m = hand._state_msg
        if m is not None:
            rows.append([round(time.time() - T0, 3), phase] + [float(m.states[i].q) for i in range(N_FINGERS)] + [float(getattr(m.states[i], "tau_est", float("nan"))) for i in range(N_FINGERS)])
        time.sleep(0.01)
say(f"Grasp test. Please place a can deep in my {SIDE} palm within fifteen seconds.")
log("open_wait", 15)
hand.set(THUMB_PRE); say("Thumb first."); log("thumb_pre", 1.0)
hand.set(FINGERS); say("Fingers."); log("fingers", 1.5)
hand.set(GRASP); say("Thumb lock."); log("closing", 2)
say("Holding for ten seconds. Test the grip."); log("hold_pull", 10)
hand.set(RELEASE_FINGERS); say("Opening fingers."); log("release_fingers", 1.5)
hand.set(OPEN); say("Thumb back. Thank you."); log("open", 1.5)
hand.close()
with open(f"/home/unitree/spike/hand_log_{SIDE}_staged2.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["t", "phase"] + [f"q{i}" for i in range(6)] + [f"tau{i}" for i in range(6)]); w.writerows(rows)
for phase in ("open_wait", "thumb_pre", "fingers", "closing", "hold_pull", "release_fingers", "open"):
    r = np.array([x[2:] for x in rows if x[1] == phase], dtype=float)
    if not len(r): continue
    q = r[:, :6]
    last = q[-1]
    print(f"{phase:15s} n={len(r):4d} end q [thumb {last[0]:.2f} aux {last[1]:.2f} idx {last[2]:.2f} mid {last[3]:.2f} ring {last[4]:.2f} pinky {last[5]:.2f}] fingers mean {np.mean(q[:, 2:]):.2f}")
    if phase == "hold_pull":
        ts = np.array([x[0] for x in rows if x[1] == phase]); t_start = ts[0]
        print("   closure per second:", [round(float(np.mean(q[(ts - t_start >= s) & (ts - t_start < s + 1)][:, 2:])), 2) for s in range(10) if ((ts - t_start >= s) & (ts - t_start < s + 1)).any()])
