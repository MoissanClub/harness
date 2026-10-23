"""Teach the reach. The owner moves the left arm by hand; this logs the measured left-arm joints at 50 Hz (joints.jsonl) and, once a
second plus on every typed label, one head-camera frame (poses.jsonl + a bundle) with the real-palm FK, the forearm yaw and pitch, the
v2 planner's pose checks and the hand blob found in depth near the FK palm (the camera check of the palm model).

Without --soft nothing is published (read-only). With --soft (robot in FSM 500, in its stand, locomotion keeps balancing) the left arm
goes compliant through g1-fetch's arm streamer on rt/arm_sdk: the arm service g1_arm_example is switched off, the weight ramps to 1
holding the measured pose, then on `soft` the left shoulder and elbow kp ramp to 0 with the command following the measured pose
(kp 0, dq 0, tau 0, kd 1.5 from g1-fetch: tau = -kd * dq, no gravity support: the arm sags when released). The wrist roll stays at
g1-fetch's kp_wrist (the real palm centre sits on the roll axis, so the roll does not move it); the right arm and the waist hold.
Commands (type and Enter): soft | <label> (while soft: holds, says "Hands away", records after 3 s, keeps holding) | stiff (hold where it is) | home (from stiff: slow move to g1-fetch home_q, release, service on, exit)
| q (soft -> stiff, then asks for home) | quit! (exit at once, nothing moves; the arm is left to the controller: hold it first)
| any other text = label the held pose. Ctrl-C = stiff.
Usage (PC2, g1fetch env): python teach_reach.py OUT_DIR [--soft] [--mock] [--every 1.0]"""
import argparse, json, os, signal, sys, threading, time, traceback
import numpy as np, cv2
ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--every", type=float, default=1.0)
ap.add_argument("--soft", action="store_true", help="take the left arm through rt/arm_sdk and make it compliant on `soft`")
ap.add_argument("--mock", action="store_true", help="with --soft: g1-fetch's MockArmStreamer, no arm service switch, no TTS, no FSM check (desk check)")
ap.add_argument("--soft-ramp", type=float, default=2.0); ap.add_argument("--stiff-ramp", type=float, default=1.0)
ap.add_argument("--home-speed", type=float, default=0.3, help="rad/s of the largest joint on the way home")
ap.add_argument("--settle", type=float, default=1.5, help="with --every 0: seconds between a label and its frames (the held arm settles)")
ap.add_argument("--frames", type=int, default=3, help="with --every 0: frames per label, 0.3 s apart (their scatter)")
ap.add_argument("--brain", default=os.path.expanduser("~/harness/hackathon/brain")); ap.add_argument("--g1fetch", default=os.path.expanduser("~/g1-fetch"))
A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
sys.path[:0] = [A.g1fetch, A.brain]; os.chdir(A.g1fetch)
import geom
from g1_fetch.config import load_config
from g1_fetch.frames import Frames
from g1_fetch.perception.camera import make_camera
from g1_fetch.control.arm import MOTOR_IDX, WAIST_YAW
from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
cfg = load_config("configs/pc2.yaml"); ChannelFactoryInitialize(0, str(cfg.network_interface))
sub = ChannelSubscriber("rt/lowstate", LowState_); sub.Init()
r3 = lambda v: [round(float(x), 4) for x in v]
S = {"q": None, "waist": None, "mode": None, "t": 0.0, "stop": False, "cmds": []}; lock = threading.Lock()
EV = open(os.path.join(A.out, "events.jsonl"), "a")
def event(**k): k["t"] = round(time.time(), 3); EV.write(json.dumps(k) + "\n"); EV.flush()


def joints():
    with open(os.path.join(A.out, "joints.jsonl"), "a") as f:
        while not S["stop"]:
            m = sub.Read(0.05)
            if m is None: continue
            q = [m.motor_state[i].q for i in MOTOR_IDX["left"]]
            with lock: S.update(q=q, waist=float(m.motor_state[WAIST_YAW].q), mode=int(m.mode_machine), t=time.time())
            f.write(json.dumps({"t": round(time.time(), 3), "q": r3(q), "arm": ARM.state if ARM else "off"}) + "\n"); time.sleep(0.02)


def keys():
    for line in sys.stdin:
        with lock: S["cmds"].append(line.strip())


class Arm:
    """The left arm through g1-fetch's streamer. States: stiff (kp 60 holding), soft (kp 0, command = measured), released."""
    def __init__(self):
        self.state = "off"; self.say = print
        if not A.mock:
            from g1_fetch.control.loco import UnitreeLoco
            loco = UnitreeLoco(cfg); loco.start()
            try: fsm = loco.fsm_id()
            finally: loco.close()
            if fsm != 500: sys.exit("FSM %s, not 500: R1+X on the remote first (robot in its stand). Nothing was enabled." % fsm)
            try:
                from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
                ac = AudioClient(); ac.SetTimeout(5.0); ac.Init(); self.say = lambda t: (print("SAY:", t, flush=True), ac.TtsMaker(t, 1))
            except Exception as e: print("TTS unavailable:", e)
            from g1_fetch.control.robot_state import set_arm_action_service
            from g1_fetch.control.arm import UnitreeArmStreamer
            self.service = set_arm_action_service; print("arm service off ->", self.service(False), flush=True); event(ev="service", on=False)
            self.s = UnitreeArmStreamer(cfg)
        else:
            from g1_fetch.control.arm import MockArmStreamer
            self.service = lambda on: 0
            self.s = MockArmStreamer(cfg, q_init={"left": np.array(S["q"]), "right": np.zeros(5)})
        self.kp_full = float(cfg.arm.kp); self.home_q = np.array(cfg.arm.home_q.left, float)
        self.s.start(); self.s.enable(); self.state = "stiff"; event(ev="enabled", q=r3(self.meas()))
        self.say("My left arm is on and holding. Hold it, then type soft.")
        threading.Thread(target=self._follow, daemon=True).start()

    def meas(self): return np.asarray(self.s.measured("left"), float).copy()

    def _pin(self):
        """Command = measured (the wrist keeps its held target): nothing pulls the arm anywhere."""
        with self.s._lock:
            m = np.asarray(self.s.measured("left"), float).copy(); m[4] = self.s.target["left"][4]
            self.s.target["left"] = m; self.s.cmd["left"] = m.copy()

    def _follow(self):
        while self.state != "released":
            if self.state == "soft": self._pin()
            time.sleep(0.02)

    def soft(self):
        if self.state != "stiff": print("soft: only from stiff (now %s)" % self.state); return
        self.say("Soft in two seconds. Hold my arm."); time.sleep(1.0)
        self.state = "soft"; n = max(1, int(A.soft_ramp * 50))
        for i in range(n): self.s.set_gain("left", self.kp_full * (1 - (i + 1) / n)); time.sleep(0.02)
        event(ev="soft", q=r3(self.meas())); print("SOFT: left shoulder and elbow kp 0 (wrist roll held)", flush=True)

    def stiff(self):
        if self.state != "soft": print("stiff: already %s" % self.state); return
        self._pin(); self.state = "stiffening"; n = max(1, int(A.stiff_ramp * 50))
        for i in range(n): self.s.set_gain("left", self.kp_full * (i + 1) / n); time.sleep(0.02)
        self.state = "stiff"; event(ev="stiff", q=r3(self.meas())); self.say("Stiff. I hold here.")

    def home(self):
        if self.state != "stiff": print("home: type stiff first (now %s)" % self.state); return
        d = float(np.max(np.abs(self.home_q - self.s.cmd["left"]))); dur = max(1.5, d / A.home_speed)
        self.say("Going home. Hands off my arm."); time.sleep(2.5); event(ev="home", q=r3(self.meas()), dist=round(d, 3), dur=round(dur, 1))
        self.s.move_to("left", self.home_q, dur); self.s.wait_settled("left", 0.05, 3.0)
        err = float(np.max(np.abs(self.meas() - self.home_q))); print("home: largest joint error %.3f rad" % err, flush=True)
        self.s.disable(); self.state = "released"; print("arm service on ->", self.service(True), flush=True)
        self.s.close(); event(ev="released", err=round(err, 3)); self.say("Home. My arm is released.")


ARM = None
threading.Thread(target=joints, daemon=True).start()
t0 = time.time()
while S["q"] is None:
    if time.time() - t0 > 5: sys.exit("no rt/lowstate in 5 s: robot on? interface %s?" % cfg.network_interface)
    time.sleep(0.05)
frames = Frames(cfg); cam = make_camera(cfg)


def level_table(fr):
    """Tables are level: the table is the modal height of the depth points in front (the floor and anything 30 cm up dropped), as a
    level plane. The first frames after the camera opens are not usable (Oct 23: 0.187 m and a 13-16 deg RANSAC fit vs 0.043 seconds later)."""
    pts, _, _ = geom.cloud_in_window(fr, frames, 320, 300, 280, 170, 4)
    pts = pts[(pts[:, 2] > -0.60) & (pts[:, 2] < 0.30) & (pts[:, 0] > 0.20)] if pts.shape[0] else pts
    if pts.shape[0] < 200: return None
    hist, e = np.histogram(pts[:, 2], bins=np.arange(-0.60, 0.305, 0.005)); i = int(hist.argmax())
    near = pts[np.abs(pts[:, 2] - (e[i] + e[i + 1]) / 2) < 0.015]; z0 = float(np.median(near[:, 2]))
    return {"n": np.array([0.0, 0.0, 1.0]), "d": z0, "z": z0, "n_in": int(near.shape[0]), "tilt_deg": 0.0}


t0 = time.time(); f0 = cam.read()
while time.time() - t0 < 2.0: f0 = cam.read()                              # let the D435i settle before the first table measurement
plane = level_table(f0); tz = None if plane is None else plane["z"]
print("table (level, modal height) from depth: %s; waist %.3f; mode_machine %s" % ("none" if plane is None else "z %.3f (n %d)" % (tz, plane["n_in"]), S["waist"], S["mode"]), flush=True)
event(ev="start", soft=A.soft, mock=A.mock, table_z=tz, q=r3(S["q"]))
if A.soft: ARM = Arm()
signal.signal(signal.SIGINT, lambda *a: S["cmds"].append("stiff" if ARM else "q"))
threading.Thread(target=keys, daemon=True).start()
print("Commands: soft | stiff | home | q | quit! | <label>" if A.soft else "Read-only. Type a label at each held pose; q to quit.", flush=True)
log_path = os.path.join(A.out, "poses.jsonl"); n = sum(1 for _ in open(log_path)) if os.path.exists(log_path) else 0   # a restart into the same folder continues the numbering
log = open(log_path, "a"); last = 0.0


def record(label):
    global n
    for _ in range(2): fr = cam.read()
    with lock: q, waist, tq = np.array(S["q"]), S["waist"], S["t"]
    pl = level_table(fr) or plane; tz = None if pl is None else pl["z"]         # the table from this pose's own frame
    s = geom.arm_segments(q); c = geom.pose_checks(q, tz); d = s["d"]; nd = np.cross(d, [0.0, 0.0, 1.0]); nd = nd / (np.linalg.norm(nd) or 1.0)
    b = geom.hand_blob(fr, frames, s["palm"], pl, xdir=d, ndir=nd)
    n += 1; name = "pose_%04d" % n
    rec = {"i": n, "t": round(fr.t, 3), "q_age_ms": round((fr.t - tq) * 1000), "label": label, "arm": ARM.state if ARM else "off", "q": r3(q), "waist": round(waist, 4),
           "palm": r3(s["palm"]), "elbow": r3(s["elbow"]), "wrist": r3(s["wrist"]), "tip": r3(s["tip"]), "d": r3(d),
           "psi": round(float(c["psi"]), 1), "pitch": round(float(c["pitch"]), 1), "clear": {k: round(float(c[k]), 3) for k in ("upper", "forearm", "hand")},
           "margin_rad": round(float(c["margin"]), 3), "table_z": None if tz is None else round(tz, 3), "palm_above_table": None if tz is None else round(float(s["palm"][2]) - tz, 3)}
    if b is not None:
        rec["blob"] = {"p": r3(b["p"]), "front": round(b["front"], 4), "near": round(b["near"], 4), "n": b["n"], "bbox": b["bbox"], "win_edge_px": b["win_edge_px"], "radius_cut": b["radius_cut"],
                       "zmin": round(b["zmin"], 4), "off_p_minus_palm": r3(b["p"] - s["palm"]), "front_minus_palm_along_d": round(b["front"] - float(s["palm"] @ d), 4)}
    log.write(json.dumps(rec) + "\n"); log.flush()
    img = fr.color.copy()
    for p, col in ((s["palm"], (0, 255, 0)), (s["tip"], (255, 0, 0)), (s["wrist"], (0, 255, 255))):
        uv = geom.pelvis_to_pixel(frames, fr.intrinsics, p)
        if uv is not None: cv2.circle(img, (int(uv[0]), int(uv[1])), 6, col, 2)
    if b is not None: x1, y1, x2, y2 = b["bbox"]; cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
    cv2.imwrite(os.path.join(A.out, name + ".jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if fr.depth is not None: cv2.imwrite(os.path.join(A.out, name + "_depth.png"), np.clip(fr.depth * 1000, 0, 65535).astype(np.uint16))
    json.dump({"intrinsics": {"fx": fr.intrinsics.fx, "fy": fr.intrinsics.fy, "cx": fr.intrinsics.cx, "cy": fr.intrinsics.cy},
               "T_optical_to_pelvis": np.asarray(geom.frames_T(frames)).round(6).tolist(), "q": r3(q), "label": label}, open(os.path.join(A.out, name + "_meta.json"), "w"))
    bl = "blob none" if b is None else "blob n %d off %s front-palm %+.3f edge %d" % (b["n"], r3(b["p"] - s["palm"]), rec["blob"]["front_minus_palm_along_d"], b["win_edge_px"])
    print("%s%s %s palm %s psi %+.0f pitch %+.0f above table %s | clear u %.3f f %.3f h %.3f margin %.2f | %s" % (
        name, "" if label is None else " [%s]" % label, rec["arm"], r3(s["palm"]), c["psi"], c["pitch"], rec["palm_above_table"], c["upper"], c["forearm"], c["hand"], c["margin"], bl), flush=True)


try:
    while not S["stop"]:
        with lock: cmds, S["cmds"] = S["cmds"], []
        label = None
        for cmd in cmds:
            if cmd == "quit!": print("quit!: exiting now; nothing moves" + ("; the arm is left to the controller" if ARM and ARM.state != "released" else ""), flush=True); S["stop"] = True
            elif ARM and cmd == "soft": ARM.soft()
            elif ARM and cmd == "stiff": ARM.stiff()
            elif ARM and cmd == "home":
                ARM.home(); S["stop"] = True
            elif cmd == "q":
                if not ARM or ARM.state in ("released", "off"): S["stop"] = True
                else:
                    if ARM.state == "soft": ARM.stiff()
                    print("Holding. Type home (hands off) to go home and release, or quit! to exit holding.", flush=True)
            else: label = cmd or "mark"
            if ARM and A.every <= 0 and cmd in ("soft", "stiff"):
                print({"soft": ">> SOFT. Move the hand to the pose, then type its label: the arm holds by itself, then take your hands away.", "stiff": ">> HOLDING. Type a label to record (hands away), soft for the next pose, or home (hands away)."}.get(ARM.state if ARM.state in ("soft", "stiff") else "", ""), flush=True)
        if S["stop"]: break
        if A.every <= 0:
            if label is None: time.sleep(0.02); continue
            wait = A.settle
            if ARM and ARM.state == "soft":                                   # a label while soft: hold here first, then hands away
                ARM.stiff(); ARM.say("Hands away."); wait = max(A.settle, 3.0)
            elif ARM and ARM.state != "stiff": print(">> not recorded: the arm is %s" % ARM.state, flush=True); continue
            print(">> recording %s in %.1f s: take your hands and arms 30 cm away from the robot's arm" % (label, wait), flush=True); time.sleep(wait)
            for k in range(A.frames): record(label); time.sleep(0.3)
            print(">> %s done; the arm holds. Hold the forearm and type soft for the next pose, or home to finish (hands away)." % label, flush=True); continue
        if label is None and time.time() - last < A.every: time.sleep(0.02); continue
        last = time.time(); record(label)
except Exception:
    traceback.print_exc()
    if ARM and ARM.state == "soft": ARM.stiff()
    print("ERROR: the arm holds where it is. Type home (hands off) or quit!", flush=True)
    while ARM and ARM.state != "released":
        with lock: cmds, S["cmds"] = S["cmds"], []
        if "home" in cmds: ARM.home()
        elif "quit!" in cmds: break
        time.sleep(0.05)
S["stop"] = True; cam.close(); event(ev="exit", poses=n, arm=ARM.state if ARM else "off"); print("saved %d poses to %s" % (n, A.out), flush=True)
