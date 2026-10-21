"""Hackathon brain v2: ONE long-running process that runs the drinks-host loop on the G1 (left hand, robot in its stand, FSM 500).
IDLE > LOOK > LISTEN > UNDERSTAND > CONFIRM > LOCATE > PICK (SERVO, APPROACH) > VERIFY > LIFT > CHECK > HANDOVER (> RECOVER) > IDLE ...
Robot, cameras, detector, hand and llama-server stay warm between orders. v2 follows V2_STRATEGY.md: orders by any description of a
can (Gemma describes each detected can with its size and position, then hears the guest against that numbered list); reach by a
feasibility search over the forearm yaw on the URDF arm model with the REAL palm point (geom.py: torso bands from the meshes,
per-segment clearances, joint margins, table clearance), no lane and no --dx; the hand placed by the model, then servoed in the head
camera (hand features and can axis in one frame, a stored hand constant K); the approach sized from the measured gap with the
measured joint correction re-applied every step; corrections chosen from the finger stall pattern; the lift verified by the can
rising in the head frame; the handover inside the head camera's view. Every measured number comes from calib.json (provenance,
sha logged per order, CLI overrides logged as deviations).
Usage (PC2, g1fetch env):  python brain.py [--manual] [--probe] [--venue] [--no-preflight] [--mock] [parameters, see -h]
Keys on stdin: q quit (safe release)  a abort this order  r release the can now  p pause/resume  o record an observation
Enter starts an order (--manual/--probe). Ctrl-C / SIGTERM: safe release (hand open, arm streamer disabled, arm service back on)."""
import argparse, glob, json, math, os, re, shlex, signal, subprocess, sys, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calib as calibmod
CAL = calibmod.load()
def cv(k): return calibmod.value(CAL, k)
STAGES_THUMB = (([0.0, 0.8, 0, 0, 0, 0], 1.0), ([0.0, 0.8, 0.9, 0.9, 0.9, 0.9], 1.5), ([0.9, 0.8, 0.9, 0.9, 0.9, 0.9], 1.0))
THUMB_PRE, OPEN6 = [0.0, 0.8, 0.0, 0.0, 0.0, 0.0], [0.0] * 6
PARK_ZERO = [0.0, 0.0, 0.0, 0.0, 0.0]        # Unitree joint zero for the 5 left-arm joints (g1-docs 00_about_G1: 关节零点)
PROMPTS = {"ask": "Tell me which one you'd like.", "listening": "Listening."}
OWN_WORDS = ("holding the", "say take", "please take")       # the robot's own handover sentences, heard through the C922 (self-release on 2026-10-21)
CALIB_ARGS = {"pre": "pregrasp_standoff_m", "grasp_below": "grasp_below_mid_m", "lift": "lift_m", "K": "hand_feature_K", "pitch_max": "pitch_max_deg", "ik_tol": "ik_tol_m", "contact": "contact_rise_rad", "palm_real": "palm_real_m", "clear": "clearance_m", "near": "near_ahead_m"}


def parse():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_argument_group("grasp (defaults from calib.json; an override is logged as a deviation)")
    g.add_argument("--pre", type=float, default=cv("pregrasp_standoff_m"), help="pre-grasp standoff along the palm normal")
    g.add_argument("--grasp-below", type=float, default=cv("grasp_below_mid_m"), help="palm centre below the can mid-height")
    g.add_argument("--palm-real", type=float, default=cv("palm_real_m"), help="real palm centre along the wrist-roll axis")
    g.add_argument("--K", type=float, nargs=3, default=cv("hand_feature_K"), metavar=("D", "N", "Z"), help="hand feature constant (front along the forearm, near face along the palm normal, median z) relative to the can axis at the centred pose; none = measure only")
    g.add_argument("--servo-iters", type=int, default=3); g.add_argument("--servo-tol", type=float, default=0.01); g.add_argument("--servo-max", type=float, default=0.03)
    g.add_argument("--frames", type=int, default=2, help="head frames per measurement (median)")
    g.add_argument("--no-gemma-hand", action="store_true", help="skip Gemma's box of the robot's hand on the first servo frame (the cross-check: a disagreement over 3 cm with the depth blob aborts the servo)")
    g.add_argument("--contact", type=float, default=cv("contact_rise_rad"), help="tracking-error rise over the per-pose baseline that aborts the approach (safety)")
    g.add_argument("--lag", type=float, default=0.012, help="hand lag behind the command that aborts the approach (safety)")
    g.add_argument("--no-fix", action="store_true", help="no stall-pattern correction after a miss")
    g.add_argument("--fwd", type=float, default=0.03); g.add_argument("--up", type=float, default=0.02); g.add_argument("--back", type=float, default=0.03)
    g.add_argument("--pause", type=float, default=4.0, help="pause at the pre-grasp before the servo (owner's palm check)")
    g.add_argument("--diam", type=float, default=0.0, help="can diameter; 0 = classify from the box width (55/66 mm)")
    g.add_argument("--no-prethumb", action="store_true"); g.add_argument("--no-thumb-lock", action="store_true", help="skip the final thumb 0.9 stage")
    g.add_argument("--lift", type=float, default=cv("lift_m"))
    g.add_argument("--verify", choices=["signature", "strict"], default="signature", help="signature: thumb < 0.3 and 3 of 4 fingers in (0.25, 0.70); strict: every finger in (0.15, 0.82)")
    g.add_argument("--park", choices=["zero", "home", "release"], default="zero", help="left-arm pose between orders")
    g = ap.add_argument_group("reach (pelvis frame: x ahead, y left)")
    g.add_argument("--psi", default="-30:60:5", help="forearm yaw candidates lo:hi:step (degrees inward), visited outward from the preferred one")
    g.add_argument("--pitch-max", type=float, default=cv("pitch_max_deg")); g.add_argument("--ik-tol", type=float, default=cv("ik_tol_m"))
    g.add_argument("--clear", type=float, nargs=4, default=cv("clearance_m"), metavar=("UPPER", "FOREARM", "HAND", "RIGHT"))
    g.add_argument("--near", type=float, default=cv("near_ahead_m"), help="hard safety: nothing within this distance straight ahead at chest height")
    g = ap.add_argument_group("voice and handover")
    g.add_argument("--seconds", type=float, default=4.0); g.add_argument("--mic", default="auto"); g.add_argument("--cam3", default="auto")
    g.add_argument("--retries", type=int, default=3); g.add_argument("--assist-wait", type=float, default=8.0); g.add_argument("--hold-reminder", type=float, default=15.0)
    g.add_argument("--release-after", type=float, default=0.0, help="rehearsal: release after this many seconds (0 = only on the guest)")
    g.add_argument("--hand-q", default=None); g.add_argument("--hand-cam", choices=["head", "cam3"], default="head")
    g.add_argument("--tts-rate", type=float, default=0.07, help="seconds per character the robot speaks; no recording until 2 s after the sentence")
    g.add_argument("--tug", type=float, default=0.03, help="a stalled finger closing this much further (setpoint re-sent) on two cycles = the can was pulled")
    g = ap.add_argument_group("system")
    g.add_argument("--server", default="http://127.0.0.1:8080/v1"); g.add_argument("--g1fetch", default=os.environ.get("G1FETCH", "/home/unitree/g1-fetch"))
    g.add_argument("--runs", default=os.path.join(HERE, "runs")); g.add_argument("--manual", action="store_true")
    g.add_argument("--probe", action="store_true", help="step 1 (the kill test): pre-grasp beside a can, measure the hand and the can in the head camera, report, retreat; no approach")
    g.add_argument("--probe-can", type=int, default=0); g.add_argument("--probe-servo", action="store_true", help="--probe: also run the servo iterations (needs K)")
    g.add_argument("--air", action="store_true", help="experiment 3: plan and move to the pre-grasp of a virtual can at --air-can, 5 cm along the palm normal and back; no can needed")
    g.add_argument("--air-can", type=float, nargs=3, default=[0.38, 0.15, 0.13], metavar=("X", "Y", "Z"))
    g.add_argument("--dry", action="store_true", help="no arm motion: look, listen, locate, plan, report")
    g.add_argument("--idle", type=float, default=1.0); g.add_argument("--orders", type=int, default=0)
    g.add_argument("--venue", action="store_true"); g.add_argument("--no-preflight", action="store_true"); g.add_argument("--preflight-args", default="")
    g.add_argument("--accept-calib", action="store_true", help="run with stale calib.json entries")
    g.add_argument("--mock", action="store_true"); g.add_argument("--mock-gemma", action="store_true")
    return ap.parse_args()


P = parse()
if P.mock:
    import mock_robot; MOCK = mock_robot.install(P)
import numpy as np, cv2
import geom, motion
from gemma import Gemma, IN_HAND_Q, HUMAN_HAND_Q
if P.mock_gemma: import mock_robot; Gemma = mock_robot.mock_gemma(Gemma)
sys.path.insert(0, P.g1fetch)
if os.path.isdir(P.g1fetch): os.chdir(P.g1fetch)        # configs/pc2.yaml and the detector weights resolve from here
from g1_fetch.config import load_config
cfg = load_config(os.path.join(P.g1fetch, "configs", "pc2.yaml"))
cfg.fridge.can_diameter_m = P.diam
cfg.cameras.head.enabled = False                          # the SR300 head camera is gone; the C922 is the third-person view
from g1_fetch.robot import build_robot
from g1_fetch.perception.localize import can_axis_from_box, median_depth, box_cloud
from g1_fetch.skills.common import go_home, SkillFailed as G1SkillFailed
from g1_fetch.control.robot_state import set_arm_action_service
SkillFailed = (motion.SkillFailed, G1SkillFailed)
geom.PALM_REAL = P.palm_real; geom.TORSO_BANDS = tuple(tuple(b) for b in cv("torso_bands")); geom.PITCH_MAX_DEG = P.pitch_max; geom.IK_TOL = P.ik_tol
geom.TABLE_CLEAR = cv("table_clear_m"); geom.CLEAR_UPPER, geom.CLEAR_FOREARM, geom.CLEAR_HAND, geom.CLEAR_RIGHT = P.clear
geom.HIGH_RISE, geom.FINGERTIP, geom.PALM_HALF_HEIGHT = cv("high_rise_m"), cv("fingertip_m"), cv("palm_half_height_m")
THRESH = {"upper": P.clear[0], "forearm": P.clear[1], "hand": P.clear[2], "right": P.clear[3], "pitch": P.pitch_max, "table": cv("table_clear_m")}
_lo, _hi, _st = ([int(v) for v in P.psi.split(":")] + [5])[:3]; PSIS = list(range(_lo, _hi + 1, _st))
SIG = cv("hold_signature"); Z = np.array([0.0, 0.0, 1.0])


class Abort(Exception): pass          # quit the program (signal or 'q')
class OrderAborted(Exception): pass   # abort this order only ('a')


def atomic_write(path, data, mode="w"):
    tmp = path + ".tmp"
    with open(tmp, mode) as f: f.write(data)
    os.replace(tmp, path)


def r3(v): return None if v is None else [round(float(x), 3) for x in np.asarray(v).ravel()]
def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1]); x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


class View:
    """Status for brainview.py: runs/live/status.json plus frame.jpg, replaced atomically."""
    def __init__(self, live):
        self.live = live; os.makedirs(live, exist_ok=True); self.frame_v = 0; self.lock = threading.Lock()
        self.s = {"state": "BOOT", "order": 0, "colour": None, "message": "", "last": None, "tag": "", "events": [], "stages": [],
                  "counters": {}, "frame_v": 0, "frame_label": "", "paused": False, "note": "", "pid": os.getpid()}
        self.update()
    def update(self, **kv):
        with self.lock:
            self.s.update(kv); self.s["t"] = time.time()
            try: atomic_write(os.path.join(self.live, "status.json"), json.dumps(self.s))
            except OSError as e: print("view write failed:", e)
    def event(self, rec):
        with self.lock: self.s["events"] = (self.s["events"] + [rec])[-14:]
        self.update(last=rec, tag=rec.get("tag", ""))
    def frame(self, bgr, label=""):
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok: return
        with self.lock:
            try: atomic_write(os.path.join(self.live, "frame.jpg"), buf.tobytes(), "wb")
            except OSError as e: print("frame write failed:", e); return
            self.frame_v += 1
        self.update(frame_v=self.frame_v, frame_label=label)


class OrderLog:
    """One JSON-lines file per order (every Gemma call, stage timings, result) plus a folder of frames and frame bundles."""
    def __init__(self, session_dir, n):
        self.path = os.path.join(session_dir, "order_%02d.jsonl" % n); self.frames = os.path.join(session_dir, "order_%02d" % n)
        os.makedirs(self.frames, exist_ok=True); self.f = open(self.path, "a")
    def event(self, **rec):
        rec.setdefault("t", time.time()); self.f.write(json.dumps(rec, default=str) + "\n"); self.f.flush()
    def save(self, name, bgr):
        path = os.path.join(self.frames, name); cv2.imwrite(path, bgr, [cv2.IMWRITE_JPEG_QUALITY, 88]); return path
    def bundle(self, label, frame, frames, meta):
        """Replayable decision frame: colour JPG, depth PNG (uint16 mm), meta JSON (intrinsics, optical->pelvis, q, hand, stage)."""
        base = os.path.join(self.frames, "bundle_" + label)
        try:
            cv2.imwrite(base + "_color.jpg", frame.color, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if getattr(frame, "depth", None) is not None:
                d = np.asarray(frame.depth); d16 = (d * 1000.0).astype(np.uint16) if d.dtype != np.uint16 else d
                cv2.imwrite(base + "_depth.png", d16)
            intr = frame.intrinsics; m = dict(meta, t=time.time(), intrinsics={k: float(getattr(intr, k)) for k in ("fx", "fy", "ppx", "ppy", "width", "height") if hasattr(intr, k)}, T_optical_to_pelvis=np.round(geom.frames_T(frames), 6).tolist())
            with open(base + "_meta.json", "w") as f: json.dump(m, f, default=str)
        except Exception as e: print("bundle failed:", e)
    def close(self): self.f.close()


class Mic:
    """arecord from the C922 (plughw:N,0, 16 kHz mono), the working path on PC2."""
    def __init__(self, device="auto"):
        self.device = device if device != "auto" else self.find()
    @staticmethod
    def find():
        try: out = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5).stdout
        except Exception: out = ""
        m = re.search(r"card (\d+): [^\n]*C922", out)
        return "plughw:%s,0" % m.group(1) if m else "plughw:2,0"
    def record(self, seconds, path):
        subprocess.run(["arecord", "-q", "-D", self.device, "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(int(round(seconds))), path], check=True, timeout=seconds + 10)
        with open(path, "rb") as f: return f.read()


class Cam3:
    """The C922 as the third-person camera, opened once and kept warm; a thread keeps dequeuing frames so a shot is live."""
    def __init__(self, node="auto"):
        self.cap = None; self.lock = threading.Lock(); self.alive = False
        if node == "auto":
            ids = sorted(glob.glob("/dev/v4l/by-id/usb-046d_C922*-video-index0")); node = ids[0] if ids else "/dev/video6"
        self.node = node
        try:
            self.cap = cv2.VideoCapture(node, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")); self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            for _ in range(8): self.cap.read()
            if not self.cap.isOpened(): raise RuntimeError("not opened")
            self.alive = True; threading.Thread(target=self._pump, daemon=True).start()
        except Exception as e:
            print("cam3 open failed (%s): %s" % (node, e)); self.cap = None
    def _pump(self):
        while self.alive:
            with self.lock: ok = self.cap.grab()
            if not ok: time.sleep(0.05)
    def shot(self):
        if self.cap is None: return None
        with self.lock:
            ok = self.cap.grab(); ok, fr = self.cap.retrieve() if ok else (False, None)
        return fr if ok else None
    def close(self):
        self.alive = False; time.sleep(0.1)
        if self.cap is not None:
            with self.lock: self.cap.release()


class Brain:
    def __init__(self):
        self.view = View(os.path.join(P.runs, "live"))
        self.session = time.strftime("%Y%m%dT%H%M%S"); self.dir = os.path.join(P.runs, self.session); os.makedirs(self.dir, exist_ok=True)
        self.counters = {"orders": 0, "autonomous": 0, "honest_negatives": 0, "assisted": 0, "manual_release": 0, "failed": 0, "grasps": 0, "misses": 0, "corrections": 0}
        self.quit = self.abort = self.release_now = self.paused = self.go = False
        self.log = None; self.o = None; self.state = "BOOT"; self.stage_t0 = time.time(); self.arms_on = False; self.frame_hold = False
        self.cam_lock = threading.Lock(); self.tts_until = 0.0; self.arm_d = np.array([1.0, 0.0, 0.0])
        self.gem = Gemma(P.server, self.on_gemma)
        self.view.update(state="BOOT", message="building robot, camera, detector", counters=self.counters, session=self.session)
        t0 = time.time()
        self.rb = build_robot(cfg)                      # DDS, loco (read-only), arm streamer, hands, D435i, YOLOE; arm service off
        self.hand = self.rb.hands["left"]
        self.arm = motion.Arm(self.rb, cfg, log=self.log_move, tol=P.ik_tol, roll_inward=float(getattr(cfg.robot.palm_inward_wrist_roll, "left", 0.0)), check_abort=self.check_abort)
        self.mic = Mic(P.mic) if not P.mock else MOCK["mic"]
        self.cam3 = Cam3(P.cam3) if not P.mock else MOCK["cam3"]
        print("robot ready in %.1f s; mic %s; cam3 %s; runs %s" % (time.time() - t0, self.mic.device, getattr(self.cam3, "node", "?"), self.dir), flush=True)
        if sys.stdin is not None and sys.stdin.isatty(): threading.Thread(target=self.keys, daemon=True).start()
        threading.Thread(target=self.live_frames, daemon=True).start()

    # --- plumbing --------------------------------------------------------------------------------
    def log_move(self, **rec):
        if self.log: self.log.event(stage=self.state, **rec)
    def on_gemma(self, rec):
        if self.log: self.log.event(**rec)
        self.view.event(rec)
        print("  Gemma %s/%s: %r -> %r (%d ms)%s" % (rec["stage"], rec["kind"], rec["question"][:60], rec["answer"], rec["ms"], " ERROR " + rec["error"] if rec.get("error") else ""), flush=True)

    def set_state(self, state, note=""):
        now = time.time()
        if self.o is not None and self.state not in ("IDLE", "BOOT"):
            ms = int((now - self.stage_t0) * 1000); self.o["stages"].append({"stage": self.state, "ms": ms})
            self.log.event(ev="stage", stage=self.state, ms=ms, tag="scripted skill")
        self.state, self.stage_t0 = state, now
        print("== %s %s" % (state, note), flush=True)
        self.view.update(state=state, note=note, stages=self.o["stages"] if self.o else [], counters=self.counters, paused=self.paused)

    def say(self, text, wait=0.0):
        print("SAY:", text, flush=True)
        try: self.rb.speak(text)
        except Exception as e: print("speak failed:", e)
        self.tts_until = time.time() + P.tts_rate * len(text) + 0.5       # the sentence ends about here; no recording before it + 2 s
        if self.log: self.log.event(ev="say", stage=self.state, text=text, tag="scripted skill")
        self.view.update(message=text)
        if wait: self.sleep(wait)

    def quiet(self, extra=0.0): self.sleep(max(0.0, self.tts_until + extra - time.time()))

    def sleep(self, s):
        end = time.time() + s
        while time.time() < end:
            self.check_abort(); time.sleep(min(0.1, max(0.0, end - time.time())))

    def check_abort(self):
        if self.quit: raise Abort()
        if self.abort: self.abort = False; raise OrderAborted()

    def keys(self):
        for line in sys.stdin:
            k = line.strip().lower()
            if k == "q": print("[q] quitting after a safe release", flush=True); self.quit = True
            elif k == "a": print("[a] aborting this order", flush=True); self.abort = True
            elif k == "r": print("[r] release now", flush=True); self.release_now = True
            elif k == "p": self.paused = not self.paused; print("[p] paused" if self.paused else "[p] resumed", flush=True); self.view.update(paused=self.paused)
            elif k.startswith("o"):
                # owner's observation: "o contact=fingers pushed=2-5 grip=none height=low note=..." (DEV_WORKFLOW vocabulary)
                obs = dict(kv.split("=", 1) for kv in k[1:].split() if "=" in kv); obs["raw"] = line.strip()
                if self.log: self.log.event(ev="obs", stage=self.state, tag="owner", **obs)
                print("[o] observation logged:", obs, flush=True)
            elif k == "": self.go = True

    def live_frames(self):
        while not self.quit:
            time.sleep(0.5)
            if self.frame_hold or self.state in ("BOOT", "OFF") or not self.cam_lock.acquire(False): continue
            try:
                f = self.rb.camera.read(); self.view.frame(f.color, "live")
            except Exception as e: print("live frame failed:", e)
            finally: self.cam_lock.release()

    def head_frame(self, n=3):
        with self.cam_lock:
            for _ in range(n): f = self.rb.camera.read()
        return f

    def cam3_shot(self, stage):
        fr = self.cam3.shot()
        if fr is None: return None, None
        return fr, self.log.save("cam3_%s.jpg" % stage, fr)

    def bundle(self, label, frame, extra=None):
        """Replayable frame bundle with the arm and hand state."""
        if not self.log: return
        hs = self.hand.state()
        meta = {"stage": self.state, "label": label, "q_cmd": r3(self.arm.q_cmd()), "q_meas": r3(self.arm.q_meas()), "hand": None if hs is None else r3(hs), "psi": self.arm.psi, "n": r3(self.arm.n)}
        if extra: meta.update(extra)
        self.log.bundle(label, frame, self.rb.frames, meta)

    def arms_enable(self):
        if not self.arms_on: self.rb.arms.enable(); self.arms_on = True
    def arms_disable(self):
        if self.arms_on:
            try: self.rb.arms.disable()
            finally: self.arms_on = False

    # --- perception helpers -------------------------------------------------------------------------
    def detect(self, frame):
        t0 = time.perf_counter(); cans = sorted([d for d in self.rb.detector.detect(frame.color) if d.label == "can"], key=lambda d: d.box[0])
        self.log.event(ev="detect", stage=self.state, n=len(cans), ms=int((time.perf_counter() - t0) * 1000), boxes=[[int(v) for v in d.box] for d in cans], conf=[round(float(d.conf), 2) for d in cans], tag="scripted skill")
        return cans

    def can_point(self, frame, d):
        """Can axis point (pelvis frame: box depth = the front surface, + the classified radius), diameter class and size, or None."""
        p = can_axis_from_box(frame, d, self.rb.frames, cfg); z = median_depth(frame, d.box, 0.5)
        if p is None or not z: return None
        w_m = d.width * z / frame.intrinsics.fx; h_m = d.height * z / frame.intrinsics.fy
        diams = cv("can_diameters_m"); diam = P.diam or (diams[0] if w_m < 0.060 else diams[1])
        p = np.asarray(p, float) + np.array([diam / 2 - float(cfg.fridge.can_diameter_m) / 2, 0.0, 0.0])   # front surface -> axis (2026-10-21 root cause)
        return {"p": p, "diam": diam, "box": [int(v) for v in d.box], "z": round(float(z), 3), "size_m": [round(float(w_m), 3), round(float(h_m), 3)], "h": float(h_m),
                "size": "slim" if diam < 0.06 else "standard"}

    def table(self, frame, can):
        """Table plane from the depth band under and beside the can (pelvis frame), or None."""
        b = can["box"]; H, W = frame.depth.shape[:2]; band = (max(0, b[0] - 160), min(H - 1, b[3] + 4), min(W - 1, b[2] + 160), H - 1)
        try:
            cloud = np.asarray(box_cloud(frame, band, self.rb.frames, step=3, max_points=6000), float); z_hint = float(can["p"][2]) - can["h"] / 2
            plane = geom.table_plane(cloud, z_hint=z_hint)
        except Exception as e:
            print("  plane fit failed:", e); plane = None
        rec = None if plane is None else {"z": round(plane["z"], 3), "n": r3(plane["n"]), "n_in": plane["n_in"], "tilt_deg": round(plane["tilt_deg"], 1)}
        self.log.event(ev="plane", stage=self.state, plane=rec, z_hint=round(float(can["p"][2]) - can["h"] / 2, 3), tag="scripted skill")
        return plane

    def measure(self, tg, label, frames=None, gemma_box=False, save=True):
        """One fresh head frame: the target can (nearest box to the expected one) and the hand blob (around the real-palm model), both in
        the pelvis frame; the hand features (front along d, near face along n, median z) relative to the can axis; with K the error
        e = (axis + K) - features. Logged, bundled, shown."""
        frames = P.frames if frames is None else frames; d, n = self.arm_d, self.arm.n; cans_p, blobs, frame, dets, best = [], [], None, [], None
        for i in range(frames):
            frame = self.head_frame(1); dets = self.detect(frame)
            if dets:
                exp_uv = geom.pelvis_to_pixel(self.rb.frames, frame.intrinsics, tg["p"])
                best = min(dets, key=lambda dd: (iou(dd.box, tg["box"]) < 0.2, np.hypot(dd.center[0] - exp_uv[0], dd.center[1] - exp_uv[1]) if exp_uv else 0))
                c = self.can_point(frame, best)
                if c is not None and np.linalg.norm(c["p"] - tg["p"]) < 0.12: cans_p.append(c["p"])
            cyl = [(tg["p"], tg["diam"] / 2)] + [(o["p"], o["diam"] / 2) for o in tg.get("others", [])]
            blob = geom.hand_blob(frame, self.rb.frames, self.arm.palm_meas(), tg.get("plane"), xdir=d, ndir=n, exclude_cyl=cyl)
            if blob is not None: blobs.append(blob)
        can = np.median(np.array(cans_p), axis=0) if cans_p else None
        blob = None if not blobs else dict(blobs[-1], p=np.median(np.array([b["p"] for b in blobs]), axis=0), front=float(np.median([b["front"] for b in blobs])), near=float(np.median([b["near"] for b in blobs])))
        model = self.arm.palm_meas(); m = {"label": label, "can": can, "blob": None if blob is None else blob["p"], "model_palm": model, "n_blob": None if blob is None else blob["n"], "bbox": None if blob is None else blob["bbox"], "uv_expect": None if blob is None else blob["uv_expect"]}
        if can is not None:
            m["model_off"] = [float((model - can) @ d), float((model - can) @ n), float(model[2] - can[2])]       # model palm relative to the axis, (d, n, z)
            if blob is not None:
                f = np.array([blob["front"], blob["near"], blob["p"][2]]); axis = np.array([float(can @ d), float(can @ n), float(can[2])])
                m["feat"] = r3(f); m["off"] = r3(f - axis)                                                       # features relative to the axis = what K is at the centred pose
                m["scatter"] = r3(np.std([[b["front"], b["near"], b["p"][2]] for b in blobs], axis=0)) if len(blobs) > 1 else None
                if P.K: m["err"] = r3(axis + np.asarray(P.K) - f)                                                    # (e_d, e_n, e_z): move the hand by e_d along d, e_z up; e_n = the gap to the closure pose
        if gemma_box and frame is not None:
            hb, rec = self.gem.box(frame.color, "the robot's hand", stage=self.state, media="head")
            if hb is not None:
                try:
                    from g1_fetch.perception.detector import Detection
                    from g1_fetch.perception.localize import box_to_point
                    hp = box_to_point(frame, Detection("hand", 1.0, hb, "gemma"), self.rb.frames, shrink=0.5)
                except Exception: hp = None
                m["gemma_hand"] = None if hp is None else np.asarray(hp, float); m["gemma_box"] = [int(v) for v in hb]
                if hp is not None and blob is not None: m["gemma_vs_blob"] = round(float(np.linalg.norm(np.asarray(hp) - blob["p"])), 3)
        rec = {k: (r3(v) if isinstance(v, np.ndarray) else v) for k, v in m.items()}
        self.log.event(ev="measure", stage=self.state, tag="sensor gate", **rec)
        txt = "%s: can %s hand feat %s (%s pts) model palm %s | off(feat-axis) %s | model_off %s" % (label, r3(can), m.get("feat"), m["n_blob"], r3(model), m.get("off"), m.get("model_off"))
        if "err" in m: txt += " | err (e_d, e_n, e_z) %s" % m["err"]
        if "gemma_vs_blob" in m: txt += " | gemma hand vs blob %.3f" % m["gemma_vs_blob"]
        print("  " + txt, flush=True)
        if frame is not None and save:
            self.bundle(label, frame, {"can": r3(can), "measure": rec})
            vis = frame.color.copy()
            for dd in dets: cv2.rectangle(vis, (int(dd.box[0]), int(dd.box[1])), (int(dd.box[2]), int(dd.box[3])), (0, 255, 0) if dd is best else (255, 128, 0), 2)
            if blob is not None:
                cv2.rectangle(vis, (blob["bbox"][0], blob["bbox"][1]), (blob["bbox"][2], blob["bbox"][3]), (0, 0, 255), 2); cv2.circle(vis, tuple(blob["uv_expect"]), 5, (255, 0, 0), -1)
            if m.get("gemma_box"): cv2.rectangle(vis, (m["gemma_box"][0], m["gemma_box"][1]), (m["gemma_box"][2], m["gemma_box"][3]), (0, 255, 255), 1)
            lab = "%s err d %.3f n %.3f z %.3f" % ((label,) + tuple(m["err"])) if "err" in m else ("%s off %s" % (label, m["off"]) if "off" in m else "%s: %s" % (label, "no can" if can is None else "hand not seen"))
            cv2.putText(vis, lab, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            self.log.save("measure_%s.jpg" % label, vis); self.view.frame(vis, lab)
        self.view.event({"ev": "measure", "stage": self.state, "kind": "head camera", "question": "hand features vs the can axis (%s)" % label, "answer": str(m.get("err") or m.get("off") or "not measured"), "ms": 0, "tag": "sensor gate", "t": time.time()})
        return m

    # --- states ----------------------------------------------------------------------------------
    def idle(self):
        self.set_state("IDLE"); self.frame_hold = False; self.go = False
        self.view.update(colour=None, message="", stages=[], counters=self.counters)
        t_end = time.time() + P.idle
        while not self.quit:
            if getattr(self.mic, "done", False): self.quit = True; break
            if (P.manual or P.probe or P.air) and not self.go and not P.mock and sys.stdin is not None and sys.stdin.isatty(): time.sleep(0.1); continue
            if self.paused: time.sleep(0.2); continue
            if time.time() < t_end: time.sleep(0.05); continue
            return True
        return False

    def look(self):
        """LOOK: fresh head frame, YOLOE can boxes, one short Gemma description per crop plus the measured size and position."""
        self.set_state("LOOK"); self.frame_hold = True
        frame = self.head_frame(); cans = self.detect(frame)
        if P.mock_gemma: mock_robot.pending_descriptions(cans, frame)
        scene = []
        for i, d in enumerate(cans):
            x1, y1, x2, y2 = [int(v) for v in d.box]; m = 10
            crop = frame.color[max(0, y1 - m):min(frame.color.shape[0], y2 + m), max(0, x1 - m):min(frame.color.shape[1], x2 + m)]
            desc = self.gem.describe_crop(crop, media="can %d" % i)[0] if crop.size else "unknown can"
            cp = self.can_point(frame, d)
            scene.append({"i": i, "desc": desc, "box": [int(v) for v in d.box], "conf": round(float(d.conf), 2), "det": d, "size": None if cp is None else cp["size"], "p": None if cp is None else r3(cp["p"])})
        pos = {1: [""], 2: ["on the left", "on the right"], 3: ["on the left", "in the middle", "on the right"]}.get(len(scene), ["number %d" % (i + 1) for i in range(len(scene))])
        for s, pw in zip(scene, pos):
            s["words"] = ", ".join(w for w in (s["desc"], s["size"] or "", pw) if w)          # e.g. "silver chi, slim, on the left"
        vis = frame.color.copy()
        for s in scene:
            b = s["box"]; cv2.rectangle(vis, (b[0], b[1]), (b[2], b[3]), (255, 128, 0), 2); cv2.putText(vis, "%d %s" % (s["i"] + 1, s["desc"]), (b[0], max(14, b[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 128, 0), 2)
        label = "%d can(s): %s" % (len(scene), "; ".join("%d %s" % (s["i"] + 1, s["words"]) for s in scene))
        self.log.save("look.jpg", vis); self.view.frame(vis, label); self.bundle("look", frame, {"scene": [{k: v for k, v in s.items() if k != "det"} for s in scene]})
        self.log.event(ev="scene", stage=self.state, cans=[{k: v for k, v in s.items() if k != "det"} for s in scene], tag="Gemma decision")
        self.o["scene"] = [s["words"] for s in scene]
        print("  scene: " + label, flush=True)
        return scene

    def listen(self, scene):
        """LISTEN + UNDERSTAND: TTS prompt, 4 s clip, Gemma hears the guest against the numbered descriptions. `none` once: the honest
        negative and another listen; twice: the ambiguity question; then give up."""
        words = [s["words"] for s in scene]; short = [s["desc"] for s in scene]; nones = 0
        for attempt in range(P.retries):
            self.set_state("LISTEN", "attempt %d" % (attempt + 1))
            if attempt == 0: self.say(PROMPTS["ask"])
            elif nones >= 2 and len(short) >= 2: self.say("The %s one, or the %s one?" % (short[0], short[1]))
            elif nones == 1: self.say("I do not see that. I see %s." % " and ".join(short))
            else: self.say("Please say it again.")
            self.quiet(); self.say(PROMPTS["listening"]); self.quiet()
            clip = os.path.join(self.log.frames, "order_%d.wav" % (attempt + 1)); t0 = time.time()
            try: wav = self.mic.record(P.seconds, clip)
            except Exception as e:
                print("record failed:", e); self.log.event(ev="error", stage=self.state, error="record: %s" % e); self.say("My microphone failed.", wait=1.5); continue
            self.log.event(ev="record", stage=self.state, seconds=P.seconds, bytes=len(wav), ms=int((time.time() - t0) * 1000), path=clip, tag="scripted skill")
            self.set_state("UNDERSTAND")
            idx, ans, rec = self.gem.hear_choice(wav, words)
            self.o.setdefault("heard", []).append(ans)
            if idx is not None: return idx, "ok"
            if "none" in ans or ans.strip() == "0": nones += 1
        return None, ("none" if nones else "unclear")

    def confirm(self, desc):
        self.set_state("CONFIRM", desc); self.o["colour"] = desc; self.view.update(colour=desc)
        self.say("The %s one. Coming up." % desc, wait=1.0)

    def plan(self, tg):
        """Reach plan (geom.plan_reach): the real palm at the can axis minus (r + 1 cm) along the palm normal, grasp_below under the
        mid-height; psi outward from the preferred yaw; every pose checked. Logs every candidate."""
        if not tg.get("plane"): return {"reason": "no_table"}                          # the grasp height comes from the table plane, never from the box-centre depth
        mid_z = tg["plane"]["z"] + tg["h"] / 2; table_z = tg["plane"]["z"]
        target = np.array([tg["p"][0], tg["p"][1], mid_z - P.grasp_below])
        right_q = None
        try: right_q = np.asarray(self.rb.arms.measured("right"), float)
        except Exception: pass
        others = [np.asarray(o["p"], float) for o in tg.get("others", [])]
        plan, tried = geom.plan_reach(target, tg["diam"] / 2, table_z=table_z, q_seed=self.arm.q_cmd(), right_q=right_q, pre=P.pre, thresholds=THRESH, psis=PSIS)
        if plan is not None and others:                                    # the hand must stay 2 cm off the other cans along pre -> grasp
            for o in others:
                box = np.array([[o[0] - tg["diam"] / 2 - 0.06, o[0] + tg["diam"] / 2 + 0.10], [o[1] - tg["diam"] / 2 - 0.03, o[1] + tg["diam"] / 2 + 0.03], [o[2] - 0.10, o[2] + 0.10]])
                if geom.segment_box_clearance(plan["pre"], plan["grasp"], box) <= 0.0: plan = None; tried.append({"psi": None, "ok": False, "why": "neighbour"}); break
        summary = [{"psi": t["psi"], "ok": t["ok"], "why": t.get("why", ""), "pitch": None if t.get("pitch") is None else round(t["pitch"], 1)} for t in tried]
        if plan is None:
            why = [t.get("why", "") for t in tried]; reason = "neighbour" if any(w == "neighbour" for w in why) else ("torso" if any(("upper" in w or "forearm" in w or "hand" in w) for w in why) else ("table" if any("table" in w for w in why) else "unreachable"))
            self.log.event(ev="plan", stage=self.state, ok=False, reason=reason, target=r3(target), tried=summary, tag="scripted skill")
            print("  no feasible reach (%s): %s" % (reason, summary[:6]), flush=True); return {"reason": reason}
        plan["target"] = target; plan["table_z"] = table_z
        self.log.event(ev="plan", stage=self.state, ok=True, psi=plan["psi"], pitch=round(plan["pitch"], 1), target=r3(target), grasp=r3(plan["grasp"]), pre=r3(plan["pre"]), high=r3(plan["high"]), checks={k: {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in c.items()} for k, c in plan["checks"].items()}, tried=summary, tag="scripted skill")
        c = plan["checks"]["grasp"]
        print("  plan: psi %d pitch %.1f; grasp %s pre %s; clearances upper %.3f forearm %.3f hand %.3f right %s table %s; %d psis tried, accepted %s" % (plan["psi"], plan["pitch"], r3(plan["grasp"]), r3(plan["pre"]), c["upper"], c["forearm"], c["hand"], None if "right" not in c else round(c["right"], 3), None if c.get("table") is None else round(c["table"], 3), len(tried), [t["psi"] for t in tried if t["ok"]]), flush=True)
        return plan

    def locate(self, idx, scene):
        """LOCATE: fresh frame, the chosen can matched to the new boxes, its axis, diameter, the table plane, the hard safety, the plan."""
        self.set_state("LOCATE", scene[idx]["desc"]); self.frame_hold = True
        frame = self.head_frame(); cans = self.detect(frame); want = scene[idx]
        if not cans: self.say("I lost sight of the cans."); self.o["result"] = "no_can"; return None
        match = max(cans, key=lambda d: iou(d.box, want["box"]))
        if iou(match.box, want["box"]) < 0.2:                                  # the cans moved: describe again and match by words
            descs = []
            for d in cans:
                x1, y1, x2, y2 = [int(v) for v in d.box]; crop = frame.color[max(0, y1 - 10):y2 + 10, max(0, x1 - 10):x2 + 10]
                descs.append(self.gem.describe_crop(crop)[0] if crop.size else "")
            same = [d for d, c in zip(cans, descs) if c == want["desc"] or set(c.split()) & set(want["desc"].split()) - {"can", "soda"}]
            if not same: self.say("I cannot find the %s one any more." % want["desc"]); self.o["result"] = "lost"; return None
            match = same[0]
        tg = self.can_point(frame, match)
        if tg is None: self.say("I see the %s one but I cannot measure where it is." % want["desc"], wait=3.0); self.o["result"] = "no_depth"; return None
        tg["desc"] = want["desc"]; tg["others"] = [c for c in (self.can_point(frame, d) for d in cans if d is not match) if c is not None]
        if geom.obstacle_ahead(frame, self.rb.frames, x_max=P.near, z_lo=0.15, y_half=0.12):
            self.log.event(ev="safety", stage=self.state, reason="obstacle within %.2f m ahead" % P.near, tag="sensor gate")
            self.say("Something is too close in front of me. Please step back.", wait=4.0); self.o["result"] = "blocked"; return None
        tg["plane"] = self.table(frame, tg)
        self.bundle("locate", frame, {"target": r3(tg["p"]), "diam": tg["diam"], "plane": None if tg["plane"] is None else round(tg["plane"]["z"], 3)})
        vis = frame.color.copy()
        for d in cans: cv2.rectangle(vis, (int(d.box[0]), int(d.box[1])), (int(d.box[2]), int(d.box[3])), (0, 255, 0) if d is match else (255, 128, 0), 3 if d is match else 2)
        label = "%s -> axis x %.2f y %.2f z %.2f, %s mm, table z %s" % (want["desc"], tg["p"][0], tg["p"][1], tg["p"][2], int(tg["diam"] * 1000), "?" if tg["plane"] is None else "%.3f" % tg["plane"]["z"])
        self.log.save("locate.jpg", vis); self.view.frame(vis, label)
        print("  target %s at pelvis %s, box %s, %.2f m, width %.3f m -> diameter %.3f; plane %s" % (want["desc"], r3(tg["p"]), tg["box"], tg["z"], tg["size_m"][0], tg["diam"], None if tg["plane"] is None else round(tg["plane"]["z"], 3)), flush=True)
        self.log.event(ev="target", stage=self.state, desc=want["desc"], p=r3(tg["p"]), diam=tg["diam"], box=tg["box"], z=tg["z"], size_m=tg["size_m"], n_cans=len(cans), tag="scripted skill")
        self.o["target"] = {"p": r3(tg["p"]), "diam": tg["diam"], "box": tg["box"], "z": tg["z"], "size_m": tg["size_m"], "desc": want["desc"]}
        plan = self.plan(tg)
        if "psi" not in plan:
            msg = {"unreachable": "The %s one is out of my reach. Please move it a little closer to me.", "torso": "The %s one is too close to my body for my left hand. Please move it a little to my left or further away.",
                   "neighbour": "The %s one has another can too close beside it. Please move it a little.", "table": "The %s one is too low for my hand. Please move it closer.",
                   "no_table": "I cannot see the table under the %s one. Please move it a little."}[plan["reason"]] % want["desc"]
            self.say(msg, wait=4.0); self.o["result"] = "no_plan_" + plan["reason"]; return None
        tg["plan"] = plan; self.o["plan"] = {"psi": plan["psi"], "pitch": round(plan["pitch"], 1), "checks": {k: round(v, 3) for k, v in plan["checks"]["grasp"].items() if isinstance(v, float)}}
        self.tg_last = tg
        return tg

    def to_pregrasp(self, tg):
        """Raise from the park pose (position only), reach forward high, lower beside the can at the planned pre-grasp."""
        plan = tg["plan"]; self.arm.psi, self.arm.n, self.arm_d = plan["psi"], plan["n"], plan["d"]; self.grasp_z = plan["grasp"][2]; self.high_z = plan["high"][2]
        self.arms_enable(); self.hand.open(wait=False); self.rb.hands["right"].open(wait=False)
        go_home(self.rb, "left", duration=2.0)                                  # v1's verified order: tuck first, then raise from the shoulder
        home = self.arm.palm_cmd(); self.home_x = float(home[0]); self.pre = plan["pre"]
        self.say("Raising.")                                                     # straight up beside the body, never over the midline
        for up in (np.array([home[0] + cv("raise_ahead_m"), max(plan["pre"][1], cv("raise_side_y_m")), plan["high"][2]]), np.array([home[0] + cv("raise_ahead_m"), max(float(home[1]), cv("raise_side_y_m")), plan["high"][2]])):
            try: self.arm.goto(up, 0.10, "up", psi="free", correct=0); break
            except motion.SkillFailed as e: print("  up waypoint %s skipped: %s" % (r3(up), e), flush=True)
        else: raise motion.SkillFailed("no raise waypoint solves")
        self.say("Reaching."); self.arm.goto(plan["high"], 0.08, "high", correct=0)   # inward at height, above the cans
        self.say("Lowering beside the can."); m_pre = self.arm.goto(plan["pre"], 0.05, "pre", correct=2)
        self.o["pre_measured"] = r3(m_pre); self.cam3_shot("pregrasp")
        return m_pre

    def servo(self, tg, iters=None):
        """SERVO: hand features and can axis in one head frame; correct (e_d, e_z) with clipped nudges until both are under the
        tolerance on two frames (budget 3). Without K it measures only. Returns the last measurement."""
        self.set_state("SERVO"); iters = P.servo_iters if iters is None else iters; last = None; good = 0; it = 0
        for it in range(iters + 1):
            m = self.measure(tg, "servo%d" % it, gemma_box=(not P.no_gemma_hand) and it == 0); last = m
            if m.get("can") is not None: tg["p"] = np.array([m["can"][0], m["can"][1], tg["p"][2]])
            if it == 0 and m.get("gemma_vs_blob") is not None and m["gemma_vs_blob"] > 0.03:
                print("  servo: Gemma's hand box and the depth blob disagree by %.3f m: no servo, the model places the hand" % m["gemma_vs_blob"], flush=True)
                self.log.event(ev="servo", stage=self.state, it=0, aborted="gemma_vs_blob %.3f" % m["gemma_vs_blob"], tag="sensor gate"); break
            if "err" not in m: break
            e = np.array(m["err"])
            self.view.event({"ev": "servo", "stage": "SERVO", "kind": "iteration %d" % it, "question": "hand error (d, n, z)", "answer": "%.3f %.3f %.3f m" % tuple(e), "ms": 0, "tag": "sensor gate", "t": time.time()})
            if abs(e[0]) < P.servo_tol and abs(e[2]) < P.servo_tol:
                good += 1
                if good >= 2 or it == iters: break
                continue
            good = 0
            if it == iters: break
            delta = self.arm_d * float(np.clip(e[0], -P.servo_max, P.servo_max)) + Z * float(np.clip(e[2], -P.servo_max, P.servo_max))
            self.log.event(ev="servo", stage=self.state, it=it, err=r3(e), delta=r3(delta), tag="sensor gate")
            print("  servo %d: correcting by %s" % (it, r3(delta)), flush=True); self.arm.nudge(delta, "servo%d" % it)
        self.o["servo"] = {"iters": it, "err": last.get("err") if last else None, "off": last.get("off") if last else None, "model_off": last.get("model_off") if last else None, "converged": good >= 1}
        return last

    def approach(self, tg, m):
        """APPROACH along +n in two halves of 1 cm steps with the measured correction re-applied every step. The distance comes from
        the model (the closure pose minus the measured palm along n: the model's lateral error is millimetres after the correction,
        while the hand's near face is hidden by the can from the head camera near closure, so e_n is logged, not used). A fresh
        measurement between halves (can moved > 1.5 cm = pushed: abort; the d alignment re-corrected). Tracking-error and lag rises
        are safety aborts. Returns 'ok' | 'pushed' | 'aborted'."""
        self.set_state("APPROACH"); n = self.arm.n
        if not P.no_prethumb: self.hand.set(THUMB_PRE); self.say("Thumb first."); self.sleep(1.2)
        self.say("Approaching."); base = self.arm.tracking(); steps = 0; why = ""
        remaining = float((tg["plan"]["grasp"] - self.arm.palm_meas()) @ n)
        for h in range(2):
            seg = max(0.0, remaining) / (2 - h)
            while seg > 0.004:
                self.check_abort(); step = min(cv("approach_step_m"), seg); before = self.arm.palm_meas()
                meas, te = self.arm.step_along(n, step, "ap%d" % steps); steps += 1
                moved = float((meas - before) @ n); seg -= step; remaining -= step
                self.log.event(ev="ap_step", stage=self.state, step=steps, moved=round(moved, 4), remaining=round(remaining, 4), tracking=round(te, 4), base=round(base, 4), q_cmd=r3(self.arm.q_cmd()), q_meas=r3(self.arm.q_meas()), tag="scripted skill")
                if te > base + max(P.contact, base):      # >= 2x the baseline (V2_STRATEGY): safety abort
                    why = "tracking error %.3f over base %.3f" % (te, base); break
                if step - moved > P.lag: why = "hand lagged the step by %.3f m" % (step - moved); break
            if why: break
            if h == 0:
                mm = self.measure(tg, "half")
                if mm.get("can") is not None:
                    moved_can = float(np.linalg.norm(mm["can"][:2] - tg["p"][:2]))
                    if moved_can > 0.015: why = "can moved %.3f m" % moved_can; self.log.event(ev="approach", stage=self.state, steps=steps, result="pushed", why=why, tag="sensor gate"); return "pushed"
                    tg["p"] = np.array([mm["can"][0], mm["can"][1], tg["p"][2]])
                remaining = float((tg["plan"]["grasp"] - self.arm.palm_meas()) @ n)
                if "err" in mm and P.servo_tol < abs(mm["err"][0]) < P.servo_max: self.arm.nudge(self.arm_d * mm["err"][0], "half-fix-d"); self.counters["corrections"] += 1
        self.m_slide = self.arm.palm_meas()
        final = self.measure(tg, "end", save=True); gap = float((tg["plan"]["grasp"] - self.m_slide) @ n)
        res = "ok" if not why else "aborted"
        if why and gap < 0.02: res = "ok"                                                # the safety stop fired at the can: we are there
        print("  approach: %d steps, %s (%s), remaining gap %s" % (steps, res, why or "no abort", None if gap is None else round(gap, 3)), flush=True)
        self.o.update(slide_steps=steps, approach=res, approach_why=why, gap=gap, slide_measured=r3(self.m_slide))
        self.log.event(ev="approach", stage=self.state, steps=steps, result=res, why=why, gap=gap, tag="scripted skill")
        self.cam3_shot("slide"); self.sleep(0.3)
        return res

    def close_hand(self):
        stages = STAGES_THUMB[1:] if not P.no_prethumb else STAGES_THUMB
        if P.no_thumb_lock: stages = stages[:-1]
        for q6, dt in stages:
            self.hand.set(q6); self.sleep(dt)
            st = self.hand.state(); self.log.event(ev="hand", stage=self.state, cmd=q6, state=None if st is None else np.round(st, 2).tolist(), tag="sensor gate")
        self.cam3_shot("closed")

    def stall_pattern(self):
        """grasped / forward (thumb 0.9, fingers stalled: the can is ahead of the palm) / low (pinky 0.9 alone) / empty (all 0.9) / partial."""
        st = self.hand.state()
        if st is None: return "unknown", None
        thumb, fingers = float(st[0]), [float(v) for v in st[2:]]; stalled = [SIG[1] < f < SIG[2] for f in fingers]
        if thumb < SIG[0] and sum(stalled) >= 3: pat = "grasped"
        elif thumb >= 0.82 and sum(stalled) >= 3: pat = "forward"
        elif fingers[3] >= 0.82 and all(stalled[:3]): pat = "low"
        elif not any(stalled): pat = "empty"
        else: pat = "partial"
        return pat, np.round(st, 2).tolist()

    def pick(self, tg):
        """PICK: pre-grasp, SERVO, APPROACH, close, stall pattern -> one mapped correction, then VERIFY."""
        self.set_state("PICK"); self.at_offer = False
        self.to_pregrasp(tg); self.sleep(P.pause)
        m = self.servo(tg)
        res = self.approach(tg, m)
        if res != "ok":
            self.log.event(ev="stall", stage=self.state, pattern=res, tag="sensor gate"); self.counters["misses"] += 1; return False
        self.close_hand(); pat, st = self.stall_pattern()
        self.log.event(ev="stall", stage=self.state, pattern=pat, hand=st, tag="sensor gate"); print("  stall pattern: %s %s" % (pat, st), flush=True)
        if pat in ("forward", "low", "empty") and not P.no_fix:
            if pat == "empty":
                mm = self.measure(tg, "empty")
                if mm.get("can") is not None and np.linalg.norm(mm["can"][:2] - tg["p"][:2]) > 0.02:
                    self.log.event(ev="stall", stage=self.state, pattern="pushed", tag="sensor gate"); return self.verify()
                fix = -self.arm_d * P.back
            else: fix = self.arm_d * P.fwd if pat == "forward" else Z * P.up
            self.say("Adjusting."); self.hand.set(THUMB_PRE); self.sleep(1.0)
            self.arm.nudge(fix, "fix-" + pat); self.counters["corrections"] += 1
            self.close_hand(); pat2, st2 = self.stall_pattern()
            self.log.event(ev="stall", stage=self.state, pattern=pat2, hand=st2, after=pat, fix=r3(fix), tag="sensor gate")
            print("  after the %s correction: %s %s" % (pat, pat2, st2), flush=True); self.o["fix"] = {"pattern": pat, "after": pat2}
        return self.verify()

    def verify(self):
        """Grasp verified by the hold signature (thumb < 0.3 and at least 3 of 4 fingers in (0.25, 0.70)) or the strict rule."""
        self.set_state("VERIFY"); closed = float(self.hand.closed_fraction()); state = self.hand.state()
        fingers = list(state[2:]) if state is not None else None
        if P.verify == "strict": stalled = [0.15 < f < 0.82 for f in fingers] if fingers else []; grasped = bool(fingers) and all(stalled)
        else: stalled = [SIG[1] < f < SIG[2] for f in fingers] if fingers else []; grasped = bool(fingers) and float(state[0]) < SIG[0] and sum(stalled) >= 3
        self.o["closure"] = round(closed, 3); self.o["hand_state"] = None if state is None else np.round(state, 2).tolist()
        self.counters["grasps" if grasped else "misses"] += 1
        print("  closure %.2f state %s -> %s" % (closed, self.o["hand_state"], "GRASPED" if grasped else "MISSED"), flush=True)
        self.log.event(ev="verify", stage=self.state, closure=self.o["closure"], hand_state=self.o["hand_state"], grasped=grasped, rule=P.verify, stalled=stalled, tag="sensor gate")
        self.view.event({"ev": "verify", "stage": "VERIFY", "kind": "hold signature", "question": "thumb < %.2f and 3 of 4 fingers in (%.2f, %.2f)?" % tuple(SIG), "answer": "yes, grasped" if grasped else "no, missed", "ms": 0, "tag": "sensor gate", "t": time.time()})
        return grasped

    def lift(self, tg):
        """LIFT with correction; the head camera must see the can's point rise by lift +- 2 cm, otherwise it is a miss."""
        self.set_state("LIFT"); self.say("Grasped. Lifting.")
        before = None
        try:
            f0 = self.head_frame(1); d0 = self.detect(f0); b0 = max(d0, key=lambda d: iou(d.box, tg["box"])) if d0 else None
            before = self.can_point(f0, b0) if b0 is not None else None
        except Exception as e: print("  lift pre-check failed:", e)
        self.m_lift = self.arm.goto(self.m_slide + Z * P.lift, 0.04, "lift", correct=2); self.sleep(0.8)
        self.o["closure_after_lift"] = round(float(self.hand.closed_fraction()), 3); rise = None
        try:
            f1 = self.head_frame(1); d1 = self.detect(f1); ref = tg["box"] if before is None else before["box"]
            near = [d for d in d1 if iou(d.box, [ref[0] - 50, ref[1] - 90, ref[2] + 50, ref[3] + 20]) > 0.05]
            after = self.can_point(f1, max(near, key=lambda d: iou(d.box, ref))) if near else None
            if before is not None and after is not None: rise = float(after["p"][2] - before["p"][2])
            self.bundle("lift", f1, {"rise": rise})
            self.view.frame(f1.color, "after the lift: can rose %s" % (None if rise is None else "%.3f m" % rise))
        except Exception as e: print("  lift check failed:", e)
        seen = None if rise is None else bool(abs(rise - P.lift) <= cv("lift_rise_tol_m"))
        self.o["lift_rise"] = None if rise is None else round(rise, 3); self.o["lift_seen"] = seen
        self.log.event(ev="lift_check", stage=self.state, rise=self.o["lift_rise"], seen=seen, tag="sensor gate")
        print("  lift check: can rose %s -> %s" % (self.o["lift_rise"], {True: "seen", False: "NOT with the hand: a miss", None: "not measured"}[seen]), flush=True)
        return seen is not False

    def check(self):
        """Third-person Gemma yes/no after the lift: advisory only."""
        self.set_state("CHECK"); fr, path = self.cam3_shot("lifted")
        if fr is None: self.o["gemma_in_hand"] = None; return
        v, ans, rec = self.gem.yesno(fr, IN_HAND_Q, "CHECK", media=path, tag="Gemma advisory")
        self.o["gemma_in_hand"] = ans

    def offer_pose(self):
        """The calibrated offer delta from the lifted hand, moved forward / toward the midline / up until the real palm projects inside
        the head camera's view and the IK solves."""
        base = self.m_lift + np.asarray(cv("offer_delta_m"), float); intr = self.rb.camera.intrinsics if hasattr(self.rb.camera, "intrinsics") else self.head_frame(1).intrinsics
        sx, sy, sz = cv("offer_search_m")
        cands = sorted([np.array([dx, dy, dz]) for dx in np.arange(0.0, sx + 1e-9, 0.05) for dy in np.arange(0.0, sy - 1e-9, -0.05) for dz in np.arange(0.0, sz + 1e-9, 0.04)], key=lambda d: float(np.linalg.norm(d)))
        for d in cands:
            c = base + d
            try: self.arm.solve(c, "free")
            except motion.SkillFailed: continue
            if geom.in_view(self.rb.frames, intr, c, margin=0.12):
                self.log.event(ev="offer", stage=self.state, p=r3(c), in_view=True, delta=r3(d), tag="scripted skill"); print("  offer pose %s in view (delta %s)" % (r3(c), r3(d)), flush=True); return c
        self.log.event(ev="offer", stage=self.state, p=r3(base), in_view=False, tag="scripted skill"); print("  offer pose: none in view, using the base pose", flush=True)
        return base

    def new_cluster(self, frame, can_p, ref):
        """Depth points within 6 cm of the held can that were not there in the reference frame (the guest's hand arriving)."""
        uv = geom.pelvis_to_pixel(self.rb.frames, frame.intrinsics, can_p)
        if uv is None: return 0, np.zeros((0, 3))
        pts, uu, vv = geom.cloud_in_window(frame, self.rb.frames, uv[0], uv[1], 110, 90, 3)
        if pts.shape[0] == 0: return 0, pts[:0]
        near = pts[np.linalg.norm(pts - can_p, axis=1) < cv("cluster_radius_m")]
        if ref is None or ref.shape[0] == 0: return int(near.shape[0]), near
        dmin = np.min(np.linalg.norm(near[:, None, :] - ref[None, ::4, :], axis=2), axis=1) if near.shape[0] else np.zeros(0)
        return int(np.sum(dmin > 0.02)), near

    def handover(self):
        """Offer the can inside the head camera's view; release on the tug (a stalled finger closing P.tug further on two cycles with the
        setpoint re-sent), a new depth cluster at the can on two frames confirmed by one Gemma yes/no, a let-go transcript (never within
        2 s of the robot's own sentence), the r key, or --release-after."""
        self.set_state("HANDOVER"); self.release_now = False
        if not self.at_offer: self.arm.goto(self.offer_pose(), 0.06, "offer", psi="free", correct=0)
        self.say("I have the can. Please take it.", wait=1.5)
        st0 = self.hand.state(); held = list(st0[2:]) if st0 is not None else None
        can_p = self.arm.palm_meas() + self.arm.n * 0.04; ref = None
        try:
            f = self.head_frame(1); _, ref = self.new_cluster(f, can_p, None); self.bundle("offer", f, {"can_p": r3(can_p)})
        except Exception as e: print("  reference frame failed:", e)
        t0 = time.time(); last_reminder = t0; cluster_run = 0; tug_run = 0; it = 0; how = None
        while how is None:
            self.check_abort(); it += 1
            if self.release_now: how = "operator"; break
            self.hand.set([0.9, 0.8] + [0.88 if it % 2 else 0.9] * 4)                     # fresh setpoint each cycle: a stalled BrainCo finger ignores a repeated target
            time.sleep(0.4); st = self.hand.state()
            if st is not None: self.log.event(ev="hold", stage=self.state, it=it, hand=np.round(st, 2).tolist(), tag="sensor gate")
            if held is not None and st is not None:
                tug_run = tug_run + 1 if any(float(st[2 + i]) - held[i] > P.tug for i in range(4)) else 0
                if tug_run >= 2: how = "taken"; self.log.event(ev="taken", stage=self.state, held=held, now=np.round(st, 2).tolist(), tag="sensor gate"); break
            if P.release_after and time.time() - t0 > P.release_after: how = "timer"; break
            if P.hand_cam == "head":
                f = self.head_frame(1); fr = f.color; path = self.log.save("hold_%02d.jpg" % it, fr)
                try:
                    n_new, _ = self.new_cluster(f, can_p, ref); cluster_run = cluster_run + 1 if n_new >= 80 else 0
                    self.log.event(ev="cluster", stage=self.state, it=it, new_points=n_new, run=cluster_run, tag="sensor gate")
                except Exception as e: print("  cluster check failed:", e); cluster_run = 0
                self.view.frame(fr, "handover: new points near the can, run %d" % cluster_run)
                if cluster_run >= 2:
                    v, ans, rec = self.gem.yesno(fr, P.hand_q or HUMAN_HAND_Q, "HANDOVER", media=path)
                    if v: how = "vision"; break
                    cluster_run = 0
            else:
                fr, path = self.cam3_shot("hold_%02d" % it)
                if fr is not None:
                    v, ans, rec = self.gem.yesno(fr, P.hand_q or HUMAN_HAND_Q, "HANDOVER", media=path); cluster_run = cluster_run + 1 if v else 0
                    if cluster_run >= 2: how = "vision"; break
            if it % 2 == 0 and time.time() > self.tts_until + 2.0:                        # never record near the robot's own sentence
                clip = os.path.join(self.log.frames, "hold_%02d.wav" % it)
                try:
                    wav = self.mic.record(2.0, clip)
                    heard, ans, rec = self.gem.heard_take_it(wav)
                    if heard and not any(w in ans for w in OWN_WORDS): how = "voice"; break
                except Exception as e: print("record failed:", e)
            if time.time() - last_reminder > P.hold_reminder:
                self.say("I am holding the can. Take it, or say take it."); last_reminder = time.time()
        self.o["release"] = how; self.o["hold_s"] = round(time.time() - t0, 1)
        self.log.event(ev="release", stage=self.state, how=how, hold_s=self.o["hold_s"], iterations=it, tag="sensor gate" if how in ("vision", "taken") else "scripted skill")
        print("  release: %s after %.1f s" % (how, self.o["hold_s"]), flush=True)
        self.hand.set(THUMB_PRE); self.sleep(1.0); self.hand.open(wait=True)
        self.say("Enjoy." if how in ("vision", "voice", "taken") else "Released.")
        return how

    def assist(self, desc):
        """After the misses: hold the open hand out at the offer pose and ask the guest to place the can; verify by the signature."""
        self.set_state("RECOVER", "assist"); self.hand.set(THUMB_PRE); self.sleep(0.8)
        if self.arms_on:
            m = self.arm.palm_meas(); self.arm.goto(m - self.arm.n * cv("retreat_out_m") + Z * max(0.0, self.high_z - m[2]), 0.08, "assist-up", psi="free", correct=0)
        else:
            self.arms_enable(); go_home(self.rb, "left", duration=2.0); home = self.arm.palm_cmd()
            self.arm.goto(np.array([home[0] + 0.05, self.pre[1], self.high_z]), 0.10, "assist-raise", psi="free", correct=0)
        self.m_lift = self.arm.palm_meas() - Z * P.lift; self.m_lift = self.arm.goto(self.offer_pose(), 0.06, "assist-offer", psi="free", correct=0); self.at_offer = True
        self.say("I missed. Please place the %s one in my hand." % desc, wait=P.assist_wait)
        self.close_hand()
        return self.verify()

    def retreat(self):
        """Up first (above the measured table edge), then back over the edge (position only), then home, then park."""
        self.set_state("RECOVER", "retreat")
        try:
            if self.arms_on:
                m = self.arm.palm_meas(); hz = max(getattr(self, "high_z", m[2] + 0.12), m[2])
                for goal, label in ((m - self.arm.n * cv("retreat_out_m") + Z * (hz - m[2]), "retreat-up"), (np.array([getattr(self, "home_x", 0.18) + cv("raise_ahead_m"), max(m[1], cv("raise_side_y_m")), hz]), "retreat-back")):
                    try: self.arm.goto(goal, 0.08, label, psi="free", correct=0)
                    except motion.SkillFailed as e: print("  %s skipped: %s" % (label, e), flush=True); self.log.event(ev="error", stage=self.state, error="%s: %s" % (label, e))
                go_home(self.rb, "left", duration=2.5)
        finally:
            self.park()

    def park(self):
        if P.park == "release": self.arms_disable(); return
        try:
            self.arms_enable()
            q = PARK_ZERO if P.park == "zero" else list(cfg.arm.home_q.left)
            self.rb.arms.move_to("left", np.array(q, float), 2.5); self.rb.arms.wait_settled("left", tol=0.08, timeout=3.0)
            self.log.event(ev="park", stage=self.state, pose=P.park, q=q, tag="scripted skill") if self.log else None
        except Exception as e:
            print("park failed:", e); self.arms_disable()

    def recover_fast(self):
        try: self.hand.set(THUMB_PRE); time.sleep(0.8); self.hand.open(wait=True)
        except Exception as e: print("hand open failed:", e)
        try: self.park()
        except Exception as e: print("park failed:", e)

    # --- one order ---------------------------------------------------------------------------------
    def order(self):
        if not self.idle(): return
        self.counters["orders"] += 1; n = self.counters["orders"]
        self.log = OrderLog(self.dir, n); self.o = {"n": n, "t": time.strftime("%Y-%m-%d %H:%M:%S"), "result": None, "assisted": False, "stages": [], "release": None}
        self.view.update(order=n, events=[], stages=[])
        self.log.event(ev="order", n=n, params={k: getattr(P, k) for k in ("pre", "grasp_below", "palm_real", "K", "servo_iters", "servo_tol", "psi", "clear", "pitch_max", "ik_tol", "contact", "lag", "lift", "verify", "seconds", "probe", "air", "no_gemma_hand")}, session=self.session, tag="scripted skill")
        self.log.event(ev="calib", calib_sha=CAL["_sha256"], git=calibmod.git_sha(), dirty=calibmod.git_dirty(), tag="scripted skill")
        for key, c, v in calibmod.deviations(CAL, P, CALIB_ARGS): self.log.event(ev="deviation", key=key, calib=c, cli=v, tag="scripted skill")
        try:
            if P.air: return self.air()
            scene = self.look()
            if not scene: self.say("I do not see any can on the table.", wait=4.0); return self.finish("no_can")
            if P.probe: return self.probe(scene)
            idx, how = self.listen(scene)
            if idx is None:
                if how == "none": self.say("Sorry. Let us try another order.", wait=2.0); return self.finish("refused")
                self.say("Sorry, I did not catch which can you want."); return self.finish("no_choice")
            self.confirm(scene[idx]["desc"])
            tg = self.locate(idx, scene)
            if tg is None: return self.finish(self.o["result"])
            if P.dry:
                self.say("Dry run. I would pick the %s one, %d centimetres ahead and %d to my left, forearm yaw %d degrees." % (tg["desc"], round(tg["p"][0] * 100), round(tg["p"][1] * 100), tg["plan"]["psi"]), wait=4.0)
                return self.finish("dry")
            grasped = self.pick(tg) and self.lift(tg)
            if not grasped:
                self.say("Missed. Let me try once more."); self.hand.open(wait=True); self.retreat()
                tg = self.locate(idx, scene)
                grasped = tg is not None and self.pick(tg) and self.lift(tg)
                if not grasped:
                    if tg is not None: self.hand.open(wait=True)
                    grasped = self.assist(scene[idx]["desc"])
                    if not grasped:
                        self.say("Sorry, I could not hold the can. Let us try another order."); self.hand.open(wait=True); self.retreat(); return self.finish("missed")
                    self.o["assisted"] = True
            self.check()
            self.handover()
            try: self.retreat()
            except (OrderAborted, Abort): raise
            except Exception as e: print("retreat failed after the handover:", e, flush=True); self.log.event(ev="error", stage=self.state, error="retreat: %s" % e); self.recover_fast()
            return self.finish("assisted" if self.o["assisted"] else "success")
        except OrderAborted:
            self.say("Order cancelled."); self.recover_fast(); return self.finish("aborted")
        except SkillFailed as e:
            print("SKILL FAILED:", e, flush=True); self.say("I could not complete that reach."); self.log.event(ev="error", stage=self.state, error="skill: %s" % e); self.recover_fast(); return self.finish("skill_failed: %s" % e)
        except Abort: raise
        except Exception as e:
            traceback.print_exc(); self.say("Something went wrong. Resetting."); self.log.event(ev="error", stage=self.state, error=traceback.format_exc()); self.recover_fast(); return self.finish("error: %s" % e)

    def probe(self, scene):
        """--probe (the kill test, experiment 2): the chosen can, the plan, the pre-grasp at the model, 5 measurements of the hand
        features and the can (plus Gemma's hand box with --gemma-hand), optionally the servo iterations, then retreat. No approach."""
        idx = min(max(0, P.probe_can), len(scene) - 1); tg = self.locate(idx, scene)
        if tg is None: return self.finish(self.o["result"])
        self.set_state("PICK", "probe"); self.to_pregrasp(tg); self.say("Measuring."); self.sleep(P.pause)
        m = self.measure(tg, "probe", frames=max(5, P.frames), gemma_box=not P.no_gemma_hand)
        if P.probe_servo and P.K: self.servo(tg)
        self.o["probe"] = {k: (r3(v) if isinstance(v, np.ndarray) else v) for k, v in m.items() if k in ("can", "blob", "model_palm", "off", "model_off", "feat", "err", "n_blob", "scatter", "gemma_vs_blob")}
        if "off" in m: self.say("Measured. Fingertip %d, near face %d, height %d millimetres from the can axis; the model palm %d, %d, %d." % tuple(round(v * 1000) for v in (list(m["off"]) + list(m["model_off"]))), wait=3.0)
        else: self.say("I could not see my hand and the can together.", wait=2.0)
        self.retreat(); return self.finish("probe")

    def air(self):
        """--air (experiment 3): plan for a virtual can, move high, pre-grasp, 5 cm along the palm normal in 1 cm corrected steps, back,
        and retreat; log the tracking baseline per pose and the measured palm per step. No can on the table."""
        tg = {"p": np.asarray(P.air_can, float), "diam": 0.066, "h": 0.122, "box": [0, 0, 1, 1], "others": [], "desc": "air target",
              "plane": {"z": float(P.air_can[2]) - 0.061, "n": np.array([0.0, 0.0, 1.0]), "d": float(P.air_can[2]) - 0.061, "n_in": 0, "tilt_deg": 0.0}}   # a virtual table 6.1 cm under the virtual can's axis
        self.set_state("LOCATE", "air"); plan = self.plan(tg)
        if "psi" not in plan: self.say("No plan for the air target."); return self.finish("air_no_plan")
        tg["plan"] = plan; self.set_state("PICK", "air"); self.to_pregrasp(tg); self.say("Pre-grasp. Baseline."); self.sleep(P.pause)
        base = self.arm.tracking(); self.log.event(ev="baseline", stage=self.state, tracking=round(base, 4), tag="sensor gate"); print("  tracking baseline %.3f" % base, flush=True)
        try: self.measure(tg, "air")
        except Exception as e: print("  measure in air failed:", e)
        for k in range(5):
            m, te = self.arm.step_along(plan["n"], 0.01, "air%d" % k); self.log.event(ev="ap_step", stage=self.state, step=k, measured=r3(m), tracking=round(te, 4), base=round(base, 4), q_cmd=r3(self.arm.q_cmd()), q_meas=r3(self.arm.q_meas()), tag="scripted skill")
        print("  5 cm along n: measured palm %s (planned grasp %s)" % (r3(self.arm.palm_meas()), r3(plan["grasp"])), flush=True); self.sleep(1.0)
        for k in range(5): self.arm.step_along(-plan["n"], 0.01, "back%d" % k)
        self.retreat(); return self.finish("air")

    def finish(self, result):
        self.o["result"] = result; self.o["stages"].append({"stage": self.state, "ms": int((time.time() - self.stage_t0) * 1000)})
        autonomous = result == "success" and self.o.get("release") in ("vision", "voice", "taken")
        if autonomous: self.counters["autonomous"] += 1
        elif result == "refused": self.counters["honest_negatives"] += 1
        elif result == "assisted": self.counters["assisted"] += 1
        elif result == "success": self.counters["manual_release"] += 1
        elif result not in ("probe", "dry", "air"): self.counters["failed"] += 1
        self.o["autonomous"] = autonomous; self.o["total_ms"] = sum(s["ms"] for s in self.o["stages"])
        self.log.event(ev="result", **{k: v for k, v in self.o.items() if k != "n"}, tag="scripted skill")
        with open(os.path.join(self.dir, "orders.jsonl"), "a") as f: f.write(json.dumps(self.o, default=str) + "\n")
        print("== RESULT order %d: %s (autonomous %s) in %.1f s; counters %s" % (self.o["n"], result, autonomous, self.o["total_ms"] / 1000, self.counters), flush=True)
        self.view.update(counters=self.counters, stages=self.o["stages"], last_result=result)
        self.log.close(); self.log = None; self.o = None; self.frame_hold = False
        return result

    def shutdown(self):
        print("== shutting down: hand open, arm streamer off, arm service on", flush=True)
        self.state = "OFF"; self.view.update(state="OFF", message="brain stopped")
        for step in (lambda: self.hand.set(THUMB_PRE), lambda: time.sleep(0.8), lambda: self.hand.open(wait=True), self.arms_disable, self.rb.close, self.cam3.close):
            try: step()
            except Exception as e: print("shutdown step failed:", e)
        try: print("arm service on ->", set_arm_action_service(True), flush=True)
        except Exception as e: print("arm service switch failed:", e)
        if self.log: self.log.close()


def run_preflight():
    cmd = [sys.executable, os.path.join(HERE, "preflight.py"), "--json", "--server", P.server, "--g1fetch", P.g1fetch, "--runs", P.runs] + (["--venue"] if P.venue else []) + (["--mock"] if P.mock else []) + shlex.split(P.preflight_args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    try: rep = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        print(r.stdout, r.stderr); print("preflight produced no report; refusing to start (use --no-preflight to override)"); sys.exit(1)
    print(rep.get("table", ""))
    if not rep.get("ok"):
        print("PREFLIGHT FAILED: %s. Fix it or start with --no-preflight." % ", ".join(c["name"] for c in rep["checks"] if c["status"] == "FAIL")); sys.exit(1)


def main():
    print(calibmod.table(CAL), flush=True)
    st = calibmod.stale(CAL)
    if st and not P.accept_calib: print("STALE calibration entries: %s. Re-measure, or start with --accept-calib." % st); sys.exit(1)
    dev = calibmod.deviations(CAL, P, CALIB_ARGS)
    if dev: print("CLI overrides of calib.json (logged as deviations):", dev, flush=True)
    if not P.no_preflight: run_preflight()
    brain = Brain()
    def on_signal(signum, frame):
        brain.quit = True; raise Abort()
    for s in (signal.SIGINT, signal.SIGTERM): signal.signal(s, on_signal)
    try:
        if P.park != "release": brain.park(); print("left arm parked (%s)" % P.park, flush=True)
        brain.say("Ready.")
        while not brain.quit and (not P.orders or brain.counters["orders"] < P.orders): brain.order()
    except Abort: print("abort requested", flush=True)
    finally:
        for s in (signal.SIGINT, signal.SIGTERM): signal.signal(s, signal.SIG_IGN)
        brain.shutdown()


if __name__ == "__main__":
    main()
