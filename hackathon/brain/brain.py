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
Keys (one meaning in every state): Enter starts the next order (--manual/--probe/--air). q, a, Ctrl-C, SIGTERM, SIGHUP: stop. Any motion
freezes at its next target and the arm holds; the brain says the way home and runs it only on y; the program ends once the arm is home.
y runs the move the brain has just announced (the way home, a servo correction in the probe). quit! (or quit) exits without moving or
releasing anything (only with the robot in damping, L2+B). r releases the can (handover). o k=v ... logs an observation. L2+B on the
remote is the emergency stop. Every stop, refusal or failure with the arm out ends in that hold; the probe ends in it too. The arm is
released only at home (g1-fetch then ramps the arm_sdk weight to 0)."""
import argparse, glob, json, math, os, re, shlex, signal, subprocess, sys, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calib as calibmod
CAL = calibmod.load()
def cv(k): return calibmod.value(CAL, k)
STAGES_THUMB = (([0.0, 0.8, 0, 0, 0, 0], 1.0), ([0.0, 0.8, 0.9, 0.9, 0.9, 0.9], 1.5), ([0.9, 0.8, 0.9, 0.9, 0.9, 0.9], 1.0))
THUMB_PRE, OPEN6 = [0.0, 0.8, 0.0, 0.0, 0.0, 0.0], [0.0] * 6
PROMPTS = {"ask": "Tell me which one you'd like.", "listening": "Listening."}
OWN_WORDS = ("holding the", "say take", "please take")       # the robot's own handover sentences, heard through the C922 (self-release on 2026-10-21)
CALIB_ARGS = {"pre": "pregrasp_standoff_m", "grasp_below": "grasp_below_mid_m", "lift": "lift_m", "K": "hand_feature_K", "pitch_max": "pitch_max_deg", "ik_tol": "ik_tol_m", "contact": "contact_rise_rad", "palm_real": "palm_real_m", "clear": "clearance_m", "near": "near_ahead_m", "speed": "speed_scale",
              "table_edge": "table_edge_m", "fingertip": "fingertip_m", "palm_half": "palm_half_height_m", "floor_margin": "table_floor_margin_m"}


def edge_arg(s):
    v = float(s)
    if not 0.30 <= v <= 0.55: raise argparse.ArgumentTypeError("--table-edge %r is outside 0.30-0.55 m (pelvis x of the table's near edge: chest-to-edge + 0.08)" % s)
    return v


def ranged(name, lo, hi):
    def f(s):
        v = float(s)
        if not lo <= v <= hi: raise argparse.ArgumentTypeError("%s %r is outside %.3f-%.3f" % (name, s, lo, hi))
        return v
    return f


def speed_arg(s):
    v = float(s)
    if not 0.0 < v <= 1.0: raise argparse.ArgumentTypeError("--speed must be in (0, 1], got %r" % s)    # '05' is 5x, 0 divides, negative is undefined in g1-fetch
    return v


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
    g.add_argument("--lag", type=float, default=0.012, help="cumulative lag of the measured palm behind the commanded approach advance that aborts the approach (safety)")
    g.add_argument("--no-fix", action="store_true", help="no stall-pattern correction after a miss")
    g.add_argument("--fwd", type=float, default=0.03); g.add_argument("--up", type=float, default=0.02); g.add_argument("--back", type=float, default=0.03)
    g.add_argument("--pause", type=float, default=4.0, help="pause at the pre-grasp before the servo (owner's palm check)")
    g.add_argument("--diam", type=float, default=0.0, help="can diameter; 0 = classify from the box width (55/66 mm)")
    g.add_argument("--no-prethumb", action="store_true"); g.add_argument("--no-thumb-lock", action="store_true", help="skip the final thumb 0.9 stage")
    g.add_argument("--lift", type=float, default=cv("lift_m"))
    g.add_argument("--verify", choices=["signature", "strict"], default="signature", help="signature: thumb < 0.3 and 3 of 4 fingers in (0.25, 0.70); strict: every finger in (0.15, 0.82)")
    g.add_argument("--park", choices=["home"], default="home", help="the left arm between orders: held at g1-fetch home_q (real palm beside the hip, below the table top); released at home when the program ends")
    g.add_argument("--speed", type=speed_arg, default=cv("speed_scale"), help="in (0, 1]: scales every Cartesian speed, the approach steps and the joint step per target (0.5 = half speed); an override is logged as a deviation")
    g.add_argument("--model-grasp", action="store_true", help="allow a pick without the hand constant K: the hand closes on the model gap alone (logged as a deviation; the kill test measures K)")
    g.add_argument("--pre-offset", type=float, default=0.0, help="the pre-grasp moved this far back along the forearm (logged as a deviation): an error for the servo to remove (the servo-residual block)")
    g.add_argument("--pre-stop", type=float, default=0.02, help="a corrected pre-grasp further than this from its goal refuses the move (the run plan's stop rule)")
    g.add_argument("--table-edge", type=edge_arg, default=cv("table_edge_m"), help="pelvis x of the table's near edge (the owner's tape, 0.30-0.55); required before the arm is enabled: every raise, retreat and home path is refused if the hand below the table top + 3 cm would pass edge - 2 cm")
    g.add_argument("--fingertip", type=ranged("--fingertip", 0.06, 0.16), default=cv("fingertip_m"), help="the open fingertips ahead of the palm centre (the owner's tape; the keep-out's and the table floor's hand); an override is logged")
    g.add_argument("--palm-half-height", dest="palm_half", type=ranged("--palm-half-height", 0.03, 0.06), default=cv("palm_half_height_m"), help="palm centre line to the hand's lowest edge (the owner's tape); an override is logged")
    g.add_argument("--floor-margin", type=ranged("--floor-margin", 0.0, 0.05), default=cv("table_floor_margin_m"), help="the open hand's lowest point stays this far above the fitted table (0.02 for the kill test: no correction near the table); an override is logged")
    g.add_argument("--no-grasp", action="store_true", help="never close on a can: an order stops before the pick (every run-plan command)")
    g.add_argument("--blind-max", type=ranged("--blind-max", 0.01, 0.5), default=0.08, help="the 0.30 m rule also refuses when one connected region of invalid depth (the arm's own silhouette left out) covers more than this fraction of the frame; set from the no-motion block's 'largest blind region' + 0.05, logged")
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
    g.add_argument("--air", action="store_true", help="experiment 3, no can: the 0.30 m rule and the table height checked on a head frame, then the pre-grasp of a virtual can at --air-can, 5 cm along the palm normal in corrected steps and back")
    g.add_argument("--air-can", type=float, nargs=2, default=[0.38, 0.15], metavar=("X", "Y"), help="virtual can axis, pelvis frame")
    g.add_argument("--table-z", "--air-table", dest="air_table", type=ranged("--table-z", -0.25, 0.20), default=None, help="the taped table height in the pelvis frame (top above the floor minus 0.84 m), required to enable the arm: the start-up home check; the floor is on the higher of it and the fitted plane, which must agree with it within 2 cm; --air: the table under the virtual can")
    g.add_argument("--air-margin", type=float, default=0.03, help="--air: the virtual can's axis at table + 0.061 + this (0 = a pre-grasp bound by the table floor, as in the kill test)")
    g.add_argument("--dry", action="store_true", help="no arm motion at all (no park, no enable): look, listen, locate, plan, report")
    g.add_argument("--idle", type=float, default=1.0); g.add_argument("--orders", type=int, default=0)
    g.add_argument("--venue", action="store_true"); g.add_argument("--no-preflight", action="store_true"); g.add_argument("--preflight-args", default="")
    g.add_argument("--accept-calib", action="store_true", help="run with stale calib.json entries")
    g.add_argument("--expect-calib", default=None, metavar="SHA16", help="refuse to start unless calib.json has this sha16 and the brain tree is clean (every run-plan command)")
    g.add_argument("--wait-reminder", type=float, default=30.0, help="seconds between the spoken reminders while the arm holds and waits for y")
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
geom.HIGH_RISE, geom.FINGERTIP, geom.PALM_HALF_HEIGHT = cv("high_rise_m"), P.fingertip, P.palm_half
geom.HAND_BACK, geom.HAND_HALF_THICK = cv("hand_back_m"), cv("hand_half_thickness_m")
THRESH = {"upper": P.clear[0], "forearm": P.clear[1], "hand": P.clear[2], "right": P.clear[3], "pitch": P.pitch_max, "table": cv("table_clear_m")}
_lo, _hi, _st = ([int(v) for v in P.psi.split(":")] + [5])[:3]; PSIS = list(range(_lo, _hi + 1, _st))
SIG = cv("hold_signature"); Z = np.array([0.0, 0.0, 1.0])
FLOOR_MARGIN, JOINT_STEP, GAP_AGREE = P.floor_margin, cv("joint_step_rad"), cv("visual_gap_agree_m")
NO_TABLE_Z = 0.0                      # before any table is known, "below the table top" means below the pelvis origin (home palm z -0.17)


class Stopped(BaseException): pass    # any stop (a, q, Ctrl-C, SIGTERM, SIGHUP, quit!) or a refused re-check: the arm holds where it is (BaseException: no broad except swallows it)


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
                  "counters": {}, "frame_v": 0, "frame_label": "", "note": "", "pid": os.getpid()}
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
        # the only flags the keys and the signals write: stops (a counter), quit_now, answer (y), go (Enter), release_now (r)
        self.stops = 0; self.armed = 0; self.quit_now = False; self.answer = None; self.go = self.release_now = False
        self.log = None; self.o = None; self.state = "BOOT"; self.stage_t0 = time.time(); self.arms_on = False; self.frame_hold = False
        self.cam_lock = threading.Lock(); self.tts_until = 0.0; self.arm_d = np.array([1.0, 0.0, 0.0]); self.view_off = False
        self.gem = Gemma(P.server, self.on_gemma)
        self.view.update(state="BOOT", message="building robot, camera, detector", counters=self.counters, session=self.session)
        t0 = time.time()
        self.rb = build_robot(cfg)                      # DDS, loco (read-only), arm streamer, hands, D435i, YOLOE; arm service off
        self.hand = self.rb.hands["left"]
        self.arm = motion.Arm(self.rb, cfg, log=self.log_move, tol=P.ik_tol, speed_scale=P.speed, roll_inward=float(getattr(cfg.robot.palm_inward_wrist_roll, "left", 0.0)), check_abort=self.check_abort, joint_step=JOINT_STEP, rest_tol=cv("pre_rest_tol_m"))
        self.home_q = np.array(cfg.arm.home_q.left, float); self.home_palm = self.arm.palm(self.home_q)
        self.held = None; self.waiting = None; self.wait_enter = False; self.reminder_t = 0.0    # written by the main loop only
        self.raise_trail = []; self.retreat_ref = None; self.table_z = None; self.high_z = None; self.up_yaw = None
        self.mock_keys = [k for k in os.environ.get("BRAIN_MOCK_KEYS", "").split(",") if k] if P.mock else []
        print("speeds (x%.2f): raise %.3f, high %.3f, lower %.3f, corrections %.3f, approach steps %.3f m/s; joint step %.3f rad per 20 ms target" % (
              P.speed, 0.10 * P.speed, 0.08 * P.speed, 0.05 * P.speed, self.arm.corr_speed * P.speed, self.arm.step_speed * P.speed, self.arm.joint_cap()), flush=True)
        hs = geom.arm_segments(self.home_q)
        print("home_q %s (g1-fetch config): real palm %s, fingertips %s; check against the run plan's expected line before any motion" % (r3(self.home_q), r3(self.home_palm), r3(hs["tip"])), flush=True)
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
        if P.mock and os.environ.get("BRAIN_MOCK_ABORT_AT") == state: mock_robot.note_key("a"); self.key("a")   # check.py: the operator's a at this state
        self.view.update(state=state, note=note, stages=self.o["stages"] if self.o else [], counters=self.counters)
        if self.o is not None and state != "IDLE": self.check_abort()                     # every stage of an order starts by checking for a stop

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
        """Before every streamed target and in every wait: a stop typed since the current move began (the order's start, or the y that
        confirmed it) freezes the arm where it is; quit! freezes it in every state."""
        if self.quit_now or self.stops > self.armed: raise Stopped()

    def stop_key(self, what):
        """q, a, Ctrl-C, SIGTERM and SIGHUP: one meaning in every state. Any motion freezes at its next target and the arm holds there;
        the brain then says the way home and runs it only on y; the program ends once the arm is home. L2+B stays the emergency stop."""
        self.stops += 1
        print("[%s] stop: the arm holds where it is; the brain says the way home and runs it only on y; the program then ends at home" % what, flush=True)

    def keys(self):
        for line in sys.stdin: self.key(line)
        print("== THE KEYBOARD CLOSED (end of input): q, y and quit! no longer reach the brain; Ctrl-C still stops; to exit holding: L2+B, then kill %d" % os.getpid(), flush=True)

    def key(self, line):
        """One meaning per key: Enter starts the next order (idle, --manual/--probe/--air); q / a stop (stop_key); y runs the move the
        brain has just announced and is waiting for; quit! (or quit) exits without moving or releasing anything; r releases the can
        (handover); o k=v ... logs an observation. Anything else is answered with this list."""
        try:
            raw = line.strip(); k = raw.lower()
            if k in ("quit!", "quit"):
                print("[%s] exiting WITHOUT moving or releasing the arm: only with the robot in damping (L2+B)" % raw, flush=True); self.quit_now = True
            elif k in ("q", "a"): self.stop_key(k)
            elif k == "y":
                if self.waiting: self.answer = "y"; print("[y] running %s" % self.waiting, flush=True)
                else: print("[y] ignored: nothing is waiting for y", flush=True)
            elif k == "r": print("[r] release the can now", flush=True); self.release_now = True
            elif k.startswith("o") and (len(k) == 1 or k[1] == " "):
                obs = dict(kv.split("=", 1) for kv in k[1:].split() if "=" in kv); obs["raw"] = raw
                if self.log: self.log.event(ev="obs", stage=self.state, tag="owner", obs=obs); where = "order %s" % (self.o or {}).get("n")
                else:
                    with open(os.path.join(self.dir, "observations.jsonl"), "a") as f: f.write(json.dumps(dict(obs=obs, t=time.time(), after_order=self.counters["orders"])) + "\n")
                    where = "observations.jsonl (after order %d)" % self.counters["orders"]
                print("[o] observation logged in %s: %s" % (where, obs), flush=True)
            elif k == "":
                if self.wait_enter: self.go = True
                else: print("[enter] ignored: no order is waiting for Enter", flush=True)
            else: print("[%s] not a key. Enter = next order; q, a, Ctrl-C = stop and hold; y = run what I announced; quit! = exit holding (after L2+B); o k=v = note" % raw, flush=True)
        except Exception as e: print("[key] %r not handled: %s" % (line, e), flush=True)

    def live_frames(self):
        while not self.view_off:
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
        if P.dry: raise RuntimeError("--dry: the arm must not be enabled")
        if P.table_edge is None and not P.mock: raise motion.SkillFailed("no table edge (--table-edge, the owner's tape): the arm is not enabled")
        if P.air_table is None and not P.mock: raise motion.SkillFailed("no table height (--table-z, the owner's tape): the arm is not enabled")
        if not self.arms_on: self.rb.arms.enable(); self.arms_on = True
    def arms_disable(self):
        if self.arms_on:
            try: self.rb.arms.disable()
            finally: self.arms_on = False

    # --- hold: the arm holds until the operator's y ---------------------------------------------------------
    def hold(self, why):
        """The arm holds where it is (the streamer keeps its last target): after any stop, refusal or failure with the arm out, and at the
        end of a probe. Nothing moves until the brain has said the way home and the operator has typed y (hold_loop)."""
        try: palm = r3(self.arm.palm_meas())
        except Exception: palm = None
        self.held = {"why": why, "palm": palm, "t": time.time()}
        if self.log: self.log.event(ev="held", stage=self.state, why=why, palm=palm, tag="scripted skill")
        print("  HOLD: %s; the arm holds at %s" % (why, palm), flush=True)

    def mock_key(self):
        """--mock: the scripted operator (BRAIN_MOCK_KEYS, one key whenever the brain waits); with none left: L2+B, then quit!."""
        k = self.mock_keys.pop(0) if self.mock_keys else "quit!"
        print("[mock operator] %s" % k, flush=True); mock_robot.note_key(k); self.key("" if k == "enter" else k)

    def wait_y(self, what, sentence):
        """Say what y will run, then wait: True on y; False on quit!, or on a stop typed during the wait (the announced move is dropped,
        the arm keeps holding and the caller says the way home). The sentence is repeated every --wait-reminder s."""
        self.say(sentence); self.waiting = what; self.answer = None; self.reminder_t = time.time(); s0 = self.stops
        try:
            while not self.quit_now and self.stops == s0:
                if self.answer == "y": return True
                if P.mock: self.mock_key(); continue
                if time.time() - self.reminder_t > P.wait_reminder: self.say(sentence); self.reminder_t = time.time()
                time.sleep(0.1)
            if not self.quit_now: print("  stop typed while waiting: %s is not run; the arm keeps holding" % what, flush=True)
            return False
        finally: self.waiting = None; self.answer = None

    def hold_loop(self):
        """While held: plan the way home from where the arm is and say it; y runs it, announced; any stop or failure on the way holds the
        arm again and the new way home is said; quit! returns with the arm holding. True when the arm is home, False on quit!."""
        while self.held and not self.quit_now:
            try: segs = self.plan_retreat()
            except motion.SkillFailed as e:
                print("  no safe way home: %s" % e, flush=True)
                if self.log: self.log.event(ev="way_home", ok=False, why=str(e), tag="scripted skill")
                self.wait_y("nothing (no safe way home)", "I have no safe way home. Hold my arm, press L2 plus B, then type quit with an exclamation mark.")
                continue
            text = self.describe_retreat(segs); print("  the way home: %s; y runs it" % text, flush=True)
            if self.log: self.log.event(ev="way_home", ok=True, plan=text, ends=[r3(self.arm.palm(qs[-1])) for _, _, qs in segs], tag="scripted skill")
            if not self.wait_y("the way home: %s" % text, "The way home: %s. Press y to run it." % text): continue   # quit! ends the loop; a stop says it again
            self.armed = self.stops; self.held = None                # only stops typed from now on stop this way home
            try:
                st = self.hand.state()
                if st is not None and float(np.max(st)) > 0.3: self.say("Opening my hand."); self.hand.set(THUMB_PRE); time.sleep(0.8); self.hand.open(wait=True)
            except Exception as e: print("hand open failed:", e)
            if self.run_retreat(segs): return True
        return False

    # --- perception helpers -------------------------------------------------------------------------
    def ahead_clear(self, frame, where):
        """The hard safety on one head frame (ROBOT_RULES): nothing within --near straight ahead at chest height, and enough valid depth
        to tell (fail-closed: an empty or mostly invalid depth frame refuses, V2_REVIEW round 2). Refuses aloud and returns False."""
        own = []
        if self.arms_on:                                                   # the robot's own left arm (measured joints) does not count
            s = geom.arm_segments(self.arm.q_meas()); own = [(s["upper"], s["elbow"], 0.07), (s["elbow"], s["wrist"], 0.07), (s["wrist"], s["tip"], 0.08)]
        blocked, why, info = geom.obstacle_ahead(frame, self.rb.frames, x_max=P.near, z_lo=0.15, y_half=0.12, own=own)
        inval = (~(np.asarray(frame.depth)[::4, ::4] > 0)).astype(np.uint8)          # invalid depth (0 or NaN), at a quarter of the resolution
        for a, b, r in own:                                                # only the arm's own projected silhouette is not counted as blind
            ua, ub = geom.pelvis_to_pixel(self.rb.frames, frame.intrinsics, a), geom.pelvis_to_pixel(self.rb.frames, frame.intrinsics, b)
            if ua is None or ub is None: continue
            za = max(0.15, float(self.rb.frames.pelvis_to_optical(np.asarray(a, float))[2])); zb = max(0.15, float(self.rb.frames.pelvis_to_optical(np.asarray(b, float))[2]))
            w = int(round((r + 0.02) * frame.intrinsics.fx / min(za, zb) / 4.0))
            cv2.line(inval, (int(ua[0] / 4), int(ua[1] / 4)), (int(ub[0] / 4), int(ub[1] / 4)), 0, max(1, 2 * w))
        nlab, lab, stats, _ = cv2.connectedComponentsWithStats(inval, connectivity=4)
        info["blind"] = round(0.0 if nlab <= 1 else float(stats[1:, cv2.CC_STAT_AREA].max()) / inval.size, 3)
        if not blocked and info["blind"] > P.blind_max:
            blocked, why = True, "one region of %.0f%% of the frame has no depth (over --blind-max %.0f%%): cannot see ahead (something inside the camera's minimum range?)" % (info["blind"] * 100, P.blind_max * 100)
        if self.log: self.log.event(ev="safety_check", stage=self.state, where=where, blocked=blocked, why=why, tag="sensor gate", **info)
        print("  safety (%s): %s; valid depth %.0f%%, largest blind region %.0f%%, %d points in the zone (%d on my own arm, not counted)" % (where, why or "clear", info["valid"] * 100, info["blind"] * 100, info["n_zone"], info["n_own_arm"]), flush=True)
        if blocked:
            if self.log: self.log.event(ev="safety", stage=self.state, reason=why, tag="sensor gate")
            self.say("Something is too close in front of me. Please step back." if "within" in why else "I cannot see well enough in front of me. I stop.", wait=4.0)
        return not blocked

    def clear_or_hold(self, where):
        """The 0.30 m rule again right before a forward move: a refusal, or a camera that cannot be read, holds the arm where it is (no
        forward motion, no automatic retreat; the way home runs only on y)."""
        try: ok = self.ahead_clear(self.head_frame(1), where)
        except Stopped: raise
        except Exception as e: print("  safety (%s): the head camera failed: %s" % (where, e), flush=True); ok = False
        if ok: return
        self.hold("the 0.30 m rule before %s" % where); raise Stopped()

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
        """Table plane from the depth band beside and under the can (pelvis frame), or None. The band starts at the can's mid-height row:
        with the can a few cm from the table's near edge the rows under its base see mostly the floor (geom.table_plane fits only near
        the base height and only level planes, so the can's own side does not count)."""
        b = can["box"]; H, W = frame.depth.shape[:2]; band = (max(0, b[0] - 160), min(H - 1, (b[1] + b[3]) // 2), min(W - 1, b[2] + 160), H - 1)
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
        frames = P.frames if frames is None else frames; d, n = self.arm_d, self.arm.n; cans_p, blobs, frame, dets, best = [], [], None, [], None; views = []
        for i in range(frames):
            frame = self.head_frame(1); dets = self.detect(frame)
            if dets:
                exp_uv = geom.pelvis_to_pixel(self.rb.frames, frame.intrinsics, tg["p"])
                best = min(dets, key=lambda dd: (iou(dd.box, tg["box"]) < 0.2, np.hypot(dd.center[0] - exp_uv[0], dd.center[1] - exp_uv[1]) if exp_uv else 0))
                c = self.can_point(frame, best)
                if c is not None and np.linalg.norm(c["p"] - tg["p"]) < 0.12: cans_p.append(c["p"])
            cyl = [(tg["p"], tg["diam"] / 2)] + [(o["p"], o["diam"] / 2) for o in tg.get("others", [])]
            blob = geom.hand_blob(frame, self.rb.frames, self.arm.palm_meas(), tg.get("plane"), xdir=d, ndir=n, exclude_cyl=cyl)
            if blob is not None:
                blobs.append(blob); Hh, Ww = frame.color.shape[:2]; u1, v1, u2, v2 = blob["bbox"]
                views.append(min(u1, v1, Ww - 1 - u2, Hh - 1 - v2) >= 8 and blob.get("win_edge_px", 99) >= 8 and not blob.get("radius_cut"))
        can = np.median(np.array(cans_p), axis=0) if cans_p else None
        blob = None if not blobs else dict(blobs[-1], p=np.median(np.array([b["p"] for b in blobs]), axis=0), front=float(np.median([b["front"] for b in blobs])), near=float(np.median([b["near"] for b in blobs])))
        model = self.arm.palm_meas(); m = {"label": label, "can": can, "blob": None if blob is None else blob["p"], "model_palm": model, "n_blob": None if blob is None else blob["n"], "bbox": None if blob is None else blob["bbox"], "uv_expect": None if blob is None else blob["uv_expect"]}
        if blob is not None and frame is not None:                         # a hand cut off by the image border, the window or the radius gives biased features: measured, not used
            H, W = frame.color.shape[:2]; u1, v1, u2, v2 = blob["bbox"]; m["edge_px"] = int(min(u1, v1, W - 1 - u2, H - 1 - v2)); m["win_edge_px"] = blob.get("win_edge_px"); m["radius_cut"] = blob.get("radius_cut")
            m["in_view"] = bool(views) and all(views) and len(blobs) == frames      # every frame's blob, not only the last (V2_REVIEW round 3)
            m["frames_in_view"] = "%d of %d" % (sum(views), frames)
        if can is not None:
            m["model_off"] = [round(float((model - can) @ d), 4), round(float((model - can) @ n), 4), round(float(model[2] - can[2]), 4)]       # model palm relative to the axis, (d, n, z)
            if blob is not None:
                f = np.array([blob["front"], blob["near"], blob["p"][2]]); axis = np.array([float(can @ d), float(can @ n), float(can[2])])
                m["feat"] = r3(f); m["off"] = r3(f - axis)                                                       # features relative to the axis = what K is at the centred pose
                if float(f[1] - axis[1]) > -(tg["diam"] / 2 + 0.005): m["in_view"] = False; m["near_inside_can"] = True   # the "near face" inside the can: can points in the blob
                m["scatter"] = r3(np.std([[b["front"], b["near"], b["p"][2]] for b in blobs], axis=0)) if len(blobs) > 1 else None
                if P.K and m.get("in_view", True): m["err"] = r3(axis + np.asarray(P.K) - f)                       # (e_d, e_n, e_z): move the hand by e_d along d, e_z up; e_n = the gap to the closure pose
        if gemma_box and frame is not None:
            hb, rec = self.gem.box(frame.color, "the robot's hand", stage=self.state, media="head"); m["gemma_box"] = None
            if hb is not None:
                try:
                    from g1_fetch.perception.detector import Detection
                    from g1_fetch.perception.localize import box_to_point
                    hp = box_to_point(frame, Detection("hand", 1.0, hb, "gemma"), self.rb.frames, shrink=0.5)
                except Exception: hp = None
                m["gemma_hand"] = None if hp is None else np.asarray(hp, float); m["gemma_box"] = [int(v) for v in hb]
                if hp is not None and blob is not None: m["gemma_vs_blob"] = round(float(np.linalg.norm(np.asarray(hp) - blob["p"])), 3)   # logged: two different hand points
                if blob is not None:                                       # the cross-check: how much of Gemma's hand box lies on the depth blob's box
                    g, b = [float(v) for v in hb], [float(v) for v in blob["bbox"]]
                    inter = max(0.0, min(g[2], b[2]) - max(g[0], b[0])) * max(0.0, min(g[3], b[3]) - max(g[1], b[1]))
                    m["gemma_on_blob"] = round(min(inter / max(1.0, (g[2] - g[0]) * (g[3] - g[1])), inter / max(1.0, (b[2] - b[0]) * (b[3] - b[1]))), 2)   # both ways
        rec = {k: (r3(v) if isinstance(v, np.ndarray) else v) for k, v in m.items()}
        self.log.event(ev="measure", stage=self.state, tag="sensor gate", **rec)
        edge = "" if blob is None else ", margins image %s px window %s px%s" % (m.get("edge_px"), m.get("win_edge_px"), ", front at the radius" if m.get("radius_cut") else "")
        seen = "hand not seen" if blob is None else ("" if m.get("in_view", True) else ", NEAR FACE INSIDE THE CAN: not used" if m.get("near_inside_can") else ", AT THE IMAGE EDGE: not used" if m.get("edge_px", 99) < 8
                                                       else ", AT THE WINDOW EDGE (%s frames in view): not used" % m.get("frames_in_view"))
        txt = "%s: can %s hand feat %s (%s pts%s%s) model palm %s | off(feat-axis) %s | model_off %s | scatter %s" % (label, r3(can), m.get("feat"), m["n_blob"], edge, seen, r3(model), m.get("off"), m.get("model_off"), m.get("scatter"))
        if "err" in m: txt += " | err (e_d, e_n, e_z) %s" % m["err"]
        if gemma_box and m.get("gemma_box") is None: txt += " | gemma hand box: none"
        if "gemma_on_blob" in m: txt += " | gemma hand box on the blob %.0f%% (points %.3f apart)" % (m["gemma_on_blob"] * 100, m.get("gemma_vs_blob", -1))
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
        """Between orders, the arm at home (or off): any stop or quit! ends the run; with --manual/--probe/--air a fresh Enter starts
        the next order (an Enter typed before this point does not count)."""
        self.set_state("IDLE"); self.frame_hold = False; self.go = False
        self.view.update(colour=None, message="", stages=[], counters=self.counters)
        t_end = time.time() + P.idle; manual = P.manual or P.probe or P.air
        self.wait_enter = manual and ((not P.mock and sys.stdin is not None and sys.stdin.isatty()) or bool(P.mock and os.environ.get("BRAIN_MOCK_ENTER")))
        try:
            while True:
                if self.quit_now or self.stops: return False
                if getattr(self.mic, "done", False): return False
                if self.wait_enter and not self.go: time.sleep(0.1); continue
                if time.time() < t_end: time.sleep(0.05); continue
                return True
        finally: self.wait_enter = False

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

    def plan(self, tg, pre=None):
        """Reach plan (geom.plan_reach): the real palm at the can axis minus (r + 1 cm) along the palm normal, grasp_below under the
        mid-height; psi outward from the preferred yaw; every pose (the pre-grasp `pre` out, each 1 cm approach pose, the high waypoint)
        checked. Logs every candidate."""
        pre = P.pre if pre is None else pre
        if not tg.get("plane"): return {"reason": "no_table"}                          # the grasp height comes from the table plane, never from the box-centre depth
        mid_z = tg["plane"]["z"] + tg["h"] / 2; table_z = tg["plane"]["z"]
        target = np.array([tg["p"][0], tg["p"][1], mid_z - P.grasp_below])
        right_q = None
        try: right_q = np.asarray(self.rb.arms.measured("right"), float)
        except Exception: pass
        others = [np.asarray(o["p"], float) for o in tg.get("others", [])]
        plan, tried = geom.plan_reach(target, tg["diam"] / 2, table_z=table_z, q_seed=self.arm.q_cmd(), right_q=right_q, pre=pre, thresholds=THRESH, psis=PSIS, axis_off=cv("palm_to_axis_m"))
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
        H, W = frame.color.shape[:2]; bx = match.box
        if min(bx[0], bx[1], W - 1 - bx[2], H - 1 - bx[3]) <= 2:              # cut off by the image border: the size, axis and height would be wrong
            self.log.event(ev="safety", stage=self.state, reason="can box at the image border", box=[int(v) for v in bx], tag="sensor gate")
            self.say("The %s one is at the edge of my view. Please move it a little toward my centre." % want["desc"], wait=4.0); self.o["result"] = "at_edge"; return None
        tg = self.can_point(frame, match)
        if tg is None: self.say("I see the %s one but I cannot measure where it is." % want["desc"], wait=3.0); self.o["result"] = "no_depth"; return None
        tg["desc"] = want["desc"]; tg["others"] = [c for c in (self.can_point(frame, d) for d in cans if d is not match) if c is not None]
        if not self.ahead_clear(frame, "locate"): self.o["result"] = "blocked"; return None
        tg["plane"] = self.table(frame, tg)
        if tg["plane"] is not None and P.air_table is not None and abs(tg["plane"]["z"] - P.air_table) > 0.02:
            print("  the table plane %.3f and the tape %.3f are more than 2 cm apart: no motion" % (tg["plane"]["z"], P.air_table), flush=True)
            self.say("The table I see is not where the tape says. I stop.", wait=3.0); self.o["result"] = "table_mismatch"; return None
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
        tg["plan"] = plan; self.table_z = plan.get("table_z"); self.o["plan"] = {"psi": plan["psi"], "pitch": round(plan["pitch"], 1), "checks": {k: round(v, 3) for k, v in plan["checks"]["grasp"].items() if isinstance(v, float)}}
        self.tg_last = tg
        return tg

    def to_pregrasp(self, tg):
        """Raise from the park pose (position only), reach forward high, lower beside the can at the planned pre-grasp."""
        plan = tg["plan"]; self.arm.psi, self.arm.n, self.arm_d = plan["psi"], plan["n"], plan["d"]; self.grasp_z = plan["grasp"][2]; self.high_z = plan["high"][2]
        self.arms_enable(); self.hand.open(wait=False); self.rb.hands["right"].open(wait=False)
        if not self.at_home() and not self.go_home(): raise motion.SkillFailed("the arm is not at home and the way home is refused")   # v1's order: tuck first
        home = self.home_palm; self.home_x = float(home[0]); self.pre = plan["pre"]      # waypoints from home_q's palm: the streamer may hold a sagged home (g1-fetch enable)
        self.retreat_ref = (np.array([tg["p"][0], tg["p"][1], plan["grasp"][2]]), tg["diam"] / 2)
        segs, y = self.plan_raise(self.arm.q_cmd(), plan["pre"][1])             # both lines of the raise solved and keep-out checked before anything moves
        self.say("Raising.")                                                     # straight up beside the body, never over the midline
        self.arm.open_trail()                                                    # every target of the raise is recorded AS IT STREAMS (round 2 blocker 2)
        try:
            for label, goal, qs in segs: self.arm.run_path(qs, goal, label)
        finally: self.raise_trail = self.arm.close_trail()                       # any stop: the sent prefix is retraced from where it stopped
        self.up_pos, self.up_yaw = segs[-1][1].copy(), self.arm.yaw_now()      # the retreat comes back here at the transit height
        self.sag_baseline("up")
        self.clear_or_hold("high"); self.say("Reaching."); self.arm.goto(plan["high"], 0.08, "high", correct=0)   # inward at height, above the cans; uncorrected: the sag baseline
        self.sag_baseline("high")
        self.arm.table_floor = max(plan["table_z"], P.air_table if P.air_table is not None else plan["table_z"]) + FLOOR_MARGIN   # the higher of the fitted and the taped table
        print("  table floor: the open hand's lowest point stays above z %.3f (the higher of the fitted plane %.3f and the tape %s, + %.3f)" % (
              self.arm.table_floor, plan["table_z"], "-" if P.air_table is None else "%.3f" % P.air_table, FLOOR_MARGIN), flush=True)
        pre = np.asarray(plan["pre"], float) - self.arm_d * P.pre_offset
        if P.pre_offset: print("  pre-grasp offset %.3f m back along the forearm (--pre-offset, a logged deviation): the servo's error to remove" % P.pre_offset, flush=True)
        self.clear_or_hold("pre"); self.say("Lowering beside the can."); m_pre = self.arm.goto(pre, 0.05, "pre", correct=4, ff=True)   # the sag fed forward, then corrected
        self.o["pre_measured"] = r3(m_pre); self.o["pre_err"] = round(self.arm.last["err"], 4); self.cam3_shot("pregrasp")
        if self.arm.last.get("blocked"): raise motion.SkillFailed("pre-grasp: %s (contact?)" % self.arm.last["blocked"])
        if self.arm.last["err"] > P.pre_stop: raise motion.SkillFailed("pre-grasp: the measured palm is %.3f m from its goal (stop over %.3f)" % (self.arm.last["err"], P.pre_stop))
        return m_pre

    def plan_raise(self, q0, pre_y, table_top=None, high_z=None):
        """The raise, every target solved and keep-out checked before anything moves: first up raise_back_m behind the hip to the table
        top + 3 cm (the open fingers pass the table-top height behind the edge), then to the raise waypoint raise_ahead_m ahead of the hip
        at the high waypoint's height, both from home_q's palm; y = max(the pre-grasp's y, raise_side_y_m), else max(home y, raise_side_y_m):
        the first candidate whose two lines both pass. Used by the pick, the --dry line and the assist. Returns ([(label, goal, qs)], y) or
        raises SkillFailed with the arm still."""
        home = self.home_palm; tz = self.table_top() if table_top is None else table_top; hz = self.high_z if high_z is None else high_z; errs = []
        step = 0.10 * P.speed * self.arm.step_s
        for y in (max(pre_y, cv("raise_side_y_m")), max(float(home[1]), cv("raise_side_y_m"))):
            low, up = np.array([home[0] - cv("raise_back_m"), y, tz + 0.03]), np.array([home[0] + cv("raise_ahead_m"), y, hz])
            try:
                qa = [q for q, _ in self.arm.path(self.arm.palm(q0), low, "free", None, step, q_start=q0)]
                qb = [q for q, _ in self.arm.path(low, up, "free", None, step, q_start=qa[-1])]
                self.keepout(qa, "up-low"); self.keepout(qb, "up")
                print("  raise: up-low %s then up %s (candidate y %.3f)" % (r3(low), r3(up), y), flush=True)
                return [("up-low", low, qa), ("up", up, qb)], y
            except motion.SkillFailed as e: errs.append("y %.3f: %s" % (y, e)); print("  raise candidate y %.3f refused: %s" % (y, e), flush=True)
        raise motion.SkillFailed("no raise solves (%s)" % "; ".join(errs))

    def sag_baseline(self, label):
        """The uncorrected move's error = the arm's sag at that pose (Tuesday: 1.9-2.6 cm at the raise, 2.5-4.7 cm at the high waypoint)."""
        last = self.arm.last; s = float(last.get("err", 0.0)); self.o.setdefault("sag", {})[label] = round(s, 4)
        self.log.event(ev="sag", stage=self.state, label=label, err=round(s, 4), vector=r3(np.asarray(last["goal"]) - np.asarray(last["measured"])), tracking=round(self.arm.tracking(), 4), tag="sensor gate")
        print("  sag baseline at %s: %.3f m (recorded; over 0.07 stops), tracking %.3f rad" % (label, s, self.arm.tracking()), flush=True)
        if s > 0.07: raise motion.SkillFailed("the sag at %s is %.3f m (over 0.07: the model disagrees with the arm)" % (label, s))

    def servo(self, tg, iters=None):
        """SERVO: hand features and can axis in one head frame; correct (e_d, e_z) with clipped nudges until both are under the
        tolerance on two frames (budget 3). Without K it measures only. Returns the last measurement."""
        self.set_state("SERVO"); iters = P.servo_iters if iters is None else iters; last = None; good = 0; it = 0; n_corr = 0
        for it in range(iters + 1):
            m = self.measure(tg, "servo%d" % it, gemma_box=(not P.no_gemma_hand) and it == 0); last = m
            if m.get("can") is not None: tg["p"] = np.array([m["can"][0], m["can"][1], tg["p"][2]])
            if it == 0 and not P.no_gemma_hand and m.get("in_view") and m.get("gemma_on_blob") is None:          # no box (server down, timeout): fails, not skipped
                print("  servo: Gemma returned no box of my hand: the cross-check cannot run, no approach", flush=True)
                self.log.event(ev="servo", stage=self.state, it=0, aborted="no gemma box", tag="sensor gate")
                raise motion.SkillFailed("Gemma returned no box of my hand: the cross-check cannot run")
            if it == 0 and m.get("in_view", True) and m.get("gemma_on_blob") is not None and m["gemma_on_blob"] < 0.5:     # a cut-off blob is not used anyway
                print("  servo: only %.0f%% of Gemma's hand box lies on the depth blob: the hand measurement is not trusted, no approach" % (m["gemma_on_blob"] * 100), flush=True)
                self.log.event(ev="servo", stage=self.state, it=0, aborted="gemma_on_blob %.2f" % m["gemma_on_blob"], tag="sensor gate")
                raise motion.SkillFailed("Gemma's hand box and the depth blob disagree (%.0f%% overlap)" % (m["gemma_on_blob"] * 100))
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
            print("  servo %d: correcting by %s" % (it, r3(delta)), flush=True)
            if P.probe:                                                         # the servo block: nothing moves after the probe without y
                text = "%d millimetres along my forearm and %d up" % (round(float(delta @ self.arm_d) * 1000), round(float(delta[2]) * 1000))
                self.hold("the servo correction waits for y")
                if not self.wait_y("the correction: %s" % text, "Correcting %s. Press y to run it." % text): raise Stopped()
                self.held = None; self.armed = self.stops
            self.clear_or_hold("servo %d" % it); self.say("Correcting."); self.arm.nudge(delta, "servo%d" % it); n_corr += 1; self.counters["corrections"] += 1
            if self.arm.last.get("blocked"): raise motion.SkillFailed("servo %d: %s (contact?)" % (it, self.arm.last["blocked"]))
        self.o["servo"] = {"iters": it, "corrections": n_corr, "err": last.get("err") if last else None, "off": last.get("off") if last else None, "model_off": last.get("model_off") if last else None, "converged": good >= 1}
        return last

    def closure_pose(self, tg):
        """The closure pose from the LATEST measured can axis (x, y from the head camera) at the plan's grasp height (table plane + h/2 -
        grasp_below): the palm centre r + palm_to_axis from the axis, against the palm normal."""
        return np.array([tg["p"][0], tg["p"][1], tg["plan"]["grasp"][2]]) - self.arm.n * (tg["diam"] / 2 + cv("palm_to_axis_m"))

    def visual_gap(self, m):
        """From a measurement with K and at least 300 hand points: the near face's remaining distance to the closure pose = K's standoff +
        e_n, with the measured palm at that moment (None otherwise). Near closure the can hides the near face (its points are excluded
        with the can's), which only makes this read long."""
        if m is None or "err" not in m or (m.get("n_blob") or 0) < 300 or not m.get("in_view", True): return None
        return (cv("pregrasp_standoff_m") + float(m["err"][1]), self.arm.palm_meas())

    def visual_ok(self, tg):
        """A visual reading is taken only while the near face is clear of the can (model gap >= 2 cm): nearer, the can hides the near
        face and the reading is long (the mock: 1.2 cm at closure). Later readings are logged, the gap is the last clear one minus the
        measured advance."""
        return float((self.closure_pose(tg) - self.arm.palm_meas()) @ self.arm.n) >= 0.02

    def gap_now(self, tg, vis=None):
        """(gap, model gap, visual gap): the model gap = (closure pose from the measured can axis - measured palm) along n; the visual
        gap = the last clear visual reading minus the measured advance since. The gap is the LARGER of the two when they agree within
        visual_gap_agree_m; with no visual gap, or a disagreement, it is None: the hand does not close (V2_REVIEW round 2 must-fix).
        --model-grasp (a logged deviation) closes on the model gap alone."""
        n = self.arm.n; pm = self.arm.palm_meas(); g_model = float((self.closure_pose(tg) - pm) @ n)
        g_vis = None if vis is None else vis[0] - float((pm - vis[1]) @ n)
        if g_vis is None: return (g_model if P.model_grasp else None), g_model, g_vis
        return (max(g_model, g_vis) if abs(g_vis - g_model) <= GAP_AGREE else None), g_model, g_vis

    def approach(self, tg, m):
        """APPROACH along +n to the closure pose in 1 cm steps, each re-applying the measured joint correction (motion.step_along). The
        gap is MEASURED: the closure pose from the latest measured can axis minus the measured palm, and the visual near-face gap from
        the last reading taken clear of the can; the LARGER counts and only while they agree within visual_gap_agree_m (no visual gap,
        or a disagreement: no close; --model-grasp closes on the model alone). Half way, a fresh measurement: the can moved > 1.5 cm =
        pushed (abort); the can axis updated. The hand closes only when the measured gap is under 1 cm. A tracking-error rise to 2x the
        baseline, a cumulative lag of P.lag behind the commanded advance, or an advance beyond the standoff + 1.5 cm is an ABORT: no
        close (V2_STRATEGY: tracking error and lag are aborts only). Returns 'ok' | 'pushed' | 'aborted'."""
        self.set_state("APPROACH"); n = self.arm.n; why = ""; steps = 0; adv_cmd = 0.0; half = False
        vis = self.visual_gap(m) if self.visual_ok(tg) else None; gap, g_model, g_vis = self.gap_now(tg, vis); g0 = gap
        def fmt(v): return "-" if v is None else "%.3f" % v
        if gap is None:
            why = "no measured gap to close on (model %.3f, visual %s%s)" % (g_model, fmt(g_vis), "" if g_vis is None else ": they disagree by more than %.3f" % GAP_AGREE)
            print("  approach: %s: no approach, no close" % why, flush=True); self.o.update(slide_steps=0, approach="aborted", approach_why=why, gap=None, gap_model=round(g_model, 4), gap_visual=None if g_vis is None else round(g_vis, 4))
            self.log.event(ev="approach", stage=self.state, steps=0, result="aborted", why=why, gap=None, gap_model=round(g_model, 4), gap_visual=None if g_vis is None else round(g_vis, 4), tag="scripted skill")
            self.m_slide = self.arm.palm_meas(); return "aborted"
        if not P.no_prethumb: self.check_abort(); self.hand.set(THUMB_PRE); self.say("Thumb first."); self.sleep(1.2)
        self.say("Approaching."); base = self.arm.tracking(); start = self.arm.palm_meas(); sag_ref = self.arm.sag()
        print("  approach: start gap %.3f (model %.3f, visual %s), tracking base %.3f" % (gap, g_model, fmt(g_vis), base), flush=True)
        while gap is not None and gap > 0.004 and steps < 12:
            self.check_abort(); self.clear_or_hold("approach step %d" % (steps + 1)); step = min(cv("approach_step_m"), gap)
            if adv_cmd + step > P.pre + P.pre_offset + 0.015: why = "the approach would advance %.3f m, beyond the standoff + 1.5 cm" % (adv_cmd + step); break
            before = self.arm.palm_meas(); adv_cmd += step
            meas, te = self.arm.step_along(n, step, "ap%d" % steps, target=start + n * adv_cmd, sag_ref=sag_ref); steps += 1          # on the line from the start
            moved = float((meas - before) @ n); lag = adv_cmd - float((meas - start) @ n); gap, g_model, g_vis = self.gap_now(tg, vis)
            self.log.event(ev="ap_step", stage=self.state, step=steps, moved=round(moved, 4), gap=None if gap is None else round(gap, 4), gap_model=round(g_model, 4), gap_visual=None if g_vis is None else round(g_vis, 4),
                           lag=round(lag, 4), tracking=round(te, 4), base=round(base, 4), q_cmd=r3(self.arm.q_cmd()), q_meas=r3(self.arm.q_meas()), tag="scripted skill")
            print("  ap%d: moved %.3f, gap %s (model %.3f, visual %s), lag %.3f, tracking %.3f (base %.3f)" % (steps, moved, fmt(gap), g_model, fmt(g_vis), lag, te, base), flush=True)
            if te > base + max(P.contact, base): why = "tracking error %.3f over 2x the base %.3f" % (te, base); break
            if lag > P.lag: why = "the hand lags the commanded advance by %.3f m" % lag; break
            if gap is not None and not half and g0 - gap >= g0 / 2 and gap > 0.004:
                half = True; clear = self.visual_ok(tg); mm = self.measure(tg, "half")
                if mm.get("can") is not None:
                    moved_can = float(np.linalg.norm(np.asarray(mm["can"][:2]) - tg["p"][:2]))
                    if moved_can > 0.015:
                        why = "can moved %.3f m" % moved_can; self.log.event(ev="approach", stage=self.state, steps=steps, result="pushed", why=why, tag="sensor gate")
                        print("  approach: %s: pushed" % why, flush=True); self.o.update(slide_steps=steps, approach="pushed", approach_why=why); return "pushed"
                    tg["p"] = np.array([mm["can"][0], mm["can"][1], tg["p"][2]])
                # no d re-correction here: K holds at the standoff where it was measured; nearer the can the visible hand changes (mock: the
                # fingertip feature drifted 1.9 cm with the hand still), so e_d at half way is logged for diagnosis only
                v2 = self.visual_gap(mm) if clear else None; vis = v2 if v2 is not None else vis; gap, g_model, g_vis = self.gap_now(tg, vis)
        self.m_slide = self.arm.palm_meas()
        final = self.measure(tg, "end", save=True)                          # logged: at closure the can hides the near face (reads long)
        gap, g_model, g_vis = self.gap_now(tg, vis)
        if why: res = "aborted"
        elif gap is None: res = "aborted"; why = "the visual gap %s disagrees with the model %.3f" % (fmt(g_vis), g_model) if g_vis is not None else "no visual gap"
        elif gap < 0.01: res = "ok"
        else: res = "aborted"; why = "the measured gap %.3f m did not close" % gap
        print("  approach: %d steps, %s (%s), measured gap %s (model %.3f, visual %s)" % (steps, res, why or "closing", fmt(gap), g_model, fmt(g_vis)), flush=True)
        self.o.update(slide_steps=steps, approach=res, approach_why=why, gap=None if gap is None else round(gap, 4), gap_model=round(g_model, 4), gap_visual=None if g_vis is None else round(g_vis, 4), slide_measured=r3(self.m_slide))
        self.log.event(ev="approach", stage=self.state, steps=steps, result=res, why=why, gap=None if gap is None else round(gap, 4), gap_model=round(g_model, 4), gap_visual=None if g_vis is None else round(g_vis, 4), tag="scripted skill")
        self.cam3_shot("slide"); self.sleep(0.3)
        return res

    def close_hand(self):
        stages = STAGES_THUMB[1:] if not P.no_prethumb else STAGES_THUMB
        if P.no_thumb_lock: stages = stages[:-1]
        for q6, dt in stages:
            self.check_abort(); self.hand.set(q6); self.sleep(dt)
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
            self.say("Adjusting."); self.check_abort(); self.hand.set(THUMB_PRE); self.sleep(1.0)
            self.clear_or_hold("fix-" + pat); self.arm.nudge(fix, "fix-" + pat); self.counters["corrections"] += 1
            if self.arm.last.get("blocked"):
                print("  the %s correction was blocked (%s): no second close" % (pat, self.arm.last["blocked"]), flush=True)
                self.log.event(ev="stall", stage=self.state, pattern="fix_blocked", after=pat, tag="sensor gate"); self.o["fix"] = {"pattern": pat, "after": "blocked"}; return False
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
        self.o["closure_after_lift"] = round(float(self.hand.closed_fraction()), 3); rise = None; edge_px = None
        try:
            f1 = self.head_frame(1); d1 = self.detect(f1); ref = tg["box"] if before is None else before["box"]
            near = [d for d in d1 if iou(d.box, [ref[0] - 50, ref[1] - 90, ref[2] + 50, ref[3] + 20]) > 0.05]
            pick = max(near, key=lambda d: iou(d.box, ref)) if near else None
            after = self.can_point(f1, pick) if pick is not None else None
            if pick is not None: H, W = f1.color.shape[:2]; b = [int(v) for v in pick.box]; edge_px = min(b[0], b[1], W - 1 - b[2], H - 1 - b[3])
            if before is not None and after is not None: rise = float(after["p"][2] - before["p"][2])
            self.bundle("lift", f1, {"rise": rise, "edge_px": edge_px})
            self.view.frame(f1.color, "after the lift: can rose %s" % (None if rise is None else "%.3f m" % rise))
        except Exception as e: print("  lift check failed:", e)
        seen = None if rise is None else bool(abs(rise - P.lift) <= cv("lift_rise_tol_m"))
        hs = self.hand.state()                                             # logged next to the camera's reading
        self.o["lift_rise"] = None if rise is None else round(rise, 3); self.o["lift_seen"] = seen
        self.log.event(ev="lift_check", stage=self.state, rise=self.o["lift_rise"], seen=seen, edge_px=edge_px, hand=None if hs is None else np.round(hs, 2).tolist(), gate=False, tag="sensor gate")
        print("  lift check (logged only, not a gate): can rose %s (lift %.2f), box %s px from the image border, hand %s" % (
            self.o["lift_rise"], P.lift, edge_px, None if hs is None else np.round(hs, 2).tolist()), flush=True)
        return True   # owner 2026-10-23: no camera veto after the grasp. Grasps 4 and 5 held the can firmly while the box-centre point of the
                      # tilted held can read a 0.2 / -0.2 cm rise (the median depth of its box falls on the table behind it), and the miss
                      # recovery opened the hand. The hold signature (VERIFY) decides; the rise is kept for the post-mortem.

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
        self.set_state("RECOVER", "assist")
        if not self.ahead_clear(self.head_frame(), "assist"): self.o["result"] = "blocked"; return None
        self.check_abort(); self.hand.set(THUMB_PRE); self.sleep(0.8)
        if self.arms_on:
            m = self.arm.palm_meas(); self.arm.goto(m - self.arm.n * cv("retreat_out_m") + Z * max(0.0, self.high_z - m[2]), 0.08, "assist-up", psi="free", correct=0)
        else:
            self.arms_enable()
            if not self.at_home() and not self.go_home(): self.o["result"] = "held"; return None
            segs, y = self.plan_raise(self.arm.q_cmd(), self.pre[1]); self.say("Raising."); self.arm.open_trail()   # the pick's raise, planned whole first
            try:
                for label, goal, qs in segs: self.arm.run_path(qs, goal, "assist-" + label)
            finally: self.raise_trail = self.arm.close_trail()
        self.m_lift = self.arm.palm_meas() - Z * P.lift; self.m_lift = self.arm.goto(self.offer_pose(), 0.06, "assist-offer", psi="free", correct=0); self.at_offer = True
        self.say("I missed. Please place the %s one in my hand." % desc, wait=P.assist_wait)
        self.close_hand()
        return self.verify()

    # --- the way home: planned before any motion, never a joint-space sweep over the table ------------------------------------------
    def at_home(self, q=None):
        q = self.arm.q_cmd() if q is None else np.asarray(q, float); return float(np.max(np.abs(q - self.home_q))) <= 0.05

    def table_top(self):
        """The table height for the keep-out and the home region: the fitted plane of this order, else the taped one (--table-z, in
        every mode: the start-up check after a release needs it, V2_REVIEW round 3), else NO_TABLE_Z (below the pelvis origin)."""
        return self.table_z if self.table_z is not None else (P.air_table if P.air_table is not None else NO_TABLE_Z)

    def home_region(self, q):
        """The palm and the open fingertips below the table-top height and the palm behind the raise waypoint: a joint-space move to home
        cannot reach the table (and the keep-out checks that path too). Judged on the palm and the fingertips: home_q's own wrist sits at
        z +0.026, which put home itself outside the region when no table was known."""
        q = np.asarray(q, float); s = geom.arm_segments(q); top = self.table_top() - 0.02
        return (float(np.max(np.abs(q - self.home_q))) <= 0.3 and all(s[k][2] < top for k in ("palm", "tip"))      # releases leave 0.06-0.14 rad
                and float(s["palm"][0]) <= float(self.home_palm[0]) + cv("raise_ahead_m") + 0.03)

    def trail_index(self, q):
        """The index of the recorded raise target the command sits on (a stop during the raise or the retraced descent), or None."""
        tr = self.raise_trail
        if not tr: return None
        d = np.max(np.abs(np.asarray(tr) - np.asarray(q, float)[None, :]), axis=1); k = int(np.argmin(d))
        return k if float(d[k]) <= 2 * self.arm.joint_cap() + 1e-6 else None

    def joint_line(self, qa, qb):
        """Joint targets from qa to qb, at most one joint step (x speed) per target."""
        qa, qb = np.asarray(qa, float), np.asarray(qb, float); k = max(1, int(np.ceil(float(np.max(np.abs(qb - qa))) / self.arm.joint_cap() - 1e-9)))
        return [qa + (qb - qa) * (i / k) for i in range(1, k + 1)]

    def plan_line(self, q0, goal, yaws, label):
        """A straight line of the palm from q0's palm to goal, roll kept, trying the forearm yaws in order (a number: the yaw blended from
        q0's; "free": position only). Returns the joint targets; raises SkillFailed if none solves."""
        p0 = self.arm.palm(q0); yaw0 = float(geom.forearm_yaw_pitch(geom.arm_segments(q0)["d"])[0]); err = None
        for psi in yaws:
            try: return [q for q, _ in self.arm.path(p0, goal, psi, "keep", 0.08 * P.speed * self.arm.step_s, None if psi == "free" else yaw0, q_start=q0)]
            except motion.SkillFailed as e: err = e; print("  %s with psi %s refused: %s" % (label, psi, e), flush=True)
        raise motion.SkillFailed("%s: %s" % (label, err))

    def plan_retreat(self):
        """The way home from where the arm is, solved and keep-out checked before any motion: [(label, how, joint targets)].
        On the recorded raise (a stop during the raise or the descent): the raise retraced from there. Over the table: up first to the
        transit height (out along -n only until retreat_out_m from the can: a retry never walks further), back to the raise end at that
        height, a short joint-space bridge onto it, the raise retraced. Below the table-top height and behind the raise: joint space.
        Anything else raises SkillFailed (the arm holds; the operator decides): never a joint-space move from above the table."""
        q = self.arm.q_cmd(); segs = []
        if self.at_home(q): return segs
        tr = self.raise_trail; k = self.trail_index(q)
        if k is None and self.home_region(q):
            segs.append(("home", "joint space", self.joint_line(q, self.home_q)))
        else:
            if k is None:
                if not tr: raise motion.SkillFailed("the arm is away from home with no recorded raise: no automatic way home")
                p = self.arm.palm(q); end = self.arm.palm(tr[-1]); hz = max(float(end[2]), self.high_z or 0.0)
                if p[2] < hz - 0.01:
                    goal = np.array([p[0], p[1], hz])
                    if self.retreat_ref is not None:                       # away from the can along -n, only up to retreat_out_m beyond the pre-grasp line
                        c, r = self.retreat_ref; s = float((c - p) @ self.arm.n); want = r + cv("palm_to_axis_m") + cv("retreat_out_m")
                        goal = goal - self.arm.n * max(0.0, want - s)
                    qs = self.plan_line(q, goal, (self.arm.yaw_now(), "free"), "retreat-up"); segs.append(("retreat-up", "up first", qs)); q = qs[-1]; p = self.arm.palm(q)
                goal = np.array([end[0], end[1], max(float(end[2]), float(p[2]))])
                if float(np.linalg.norm(goal - p)) > 0.005:
                    qs = self.plan_line(q, goal, ((self.up_yaw,) if self.up_yaw is not None else ()) + ("free",), "retreat-back"); segs.append(("retreat-back", "back over the edge", qs)); q = qs[-1]
                if float(np.linalg.norm(self.arm.palm(q) - end)) > 0.05: raise motion.SkillFailed("the retreat ends %.3f m from the raise end" % float(np.linalg.norm(self.arm.palm(q) - end)))
                segs.append(("bridge", "onto the raise end", self.joint_line(q, tr[-1]))); k = len(tr) - 1
            down = [np.asarray(v, float) for v in reversed(tr[:k])]
            if not self.at_home(tr[0]):
                if not self.home_region(tr[0]): raise motion.SkillFailed("the recorded raise does not start at home")
                down += self.joint_line(tr[0], self.home_q)
            elif down: down += self.joint_line(down[-1], self.home_q)
            else: down = self.joint_line(q if k is None else tr[k], self.home_q)
            segs.append(("home", "the raise retraced", down))
        for label, how, qs in segs: self.keepout(qs, "%s (%s)" % (label, how))
        return segs

    def describe_retreat(self, segs):
        parts = []; names = ("shoulder", "shoulder", "upper arm", "elbow", "wrist")
        for label, how, qs in segs:
            a, b = self.arm.palm(qs[0]), self.arm.palm(qs[-1]); dq = np.abs(np.asarray(qs[-1]) - np.asarray(qs[0])); j = int(np.argmax(dq))
            if label == "bridge": parts.append("turn the %s %d degrees" % (names[j], round(math.degrees(float(dq[j])))))
            else: parts.append("%s %d centimetres" % (label.replace("-", " "), round(float(np.linalg.norm(b - a)) * 100)))
        return ", then ".join(parts) if parts else "nothing, the arm is home"

    def run_retreat(self, segs):
        """Stream the planned way home, announced. A stop (checked before every target) or any failure holds the arm again where it is.
        True when home."""
        names = ("shoulder", "shoulder", "upper arm", "elbow", "wrist"); said = False
        try:
            for label, how, qs in segs:
                if label in ("retreat-up", "retreat-back") and not said: self.say("Up and back."); said = True
                dq = np.abs(np.asarray(qs[-1]) - np.asarray(qs[0]))
                if label == "bridge" and float(dq.max()) > math.radians(5): self.say("Turning my %s." % names[int(np.argmax(dq))])
                if label == "home": self.say("Home.")
                self.arm.replay(qs, label)
                m = self.arm.palm_meas()
                if self.log: self.log.event(ev="move" if label != "home" else "home", stage=self.state, label=label, how=how, measured=r3(m), q_cmd=r3(self.arm.q_cmd()), tag="scripted skill")
                print("  %s (%s): measured palm %s" % (label, how, r3(m)), flush=True)
        except Stopped: self.hold("stopped on the way home"); return False
        except Exception as e: self.hold("the way home failed: %s" % (e or type(e).__name__)); return False
        self.raise_trail = []; self.retreat_ref = None; self.arm.table_floor = None
        return True

    def low_reach(self, qs, below):
        """The furthest-ahead point (x) of the wrist, palm and fingertips over the joint targets qs while below z `below`; -1 if none."""
        worst = -1.0
        for q in qs:
            s = geom.arm_segments(q)
            for k in ("wrist", "palm", "tip"):
                if s[k][2] < below: worst = max(worst, float(s[k][0]))
        return worst

    def keepout(self, qs, label):
        """The table keep-out on a transit path (raise, retreat, home, park), before it moves: below the table top + 3 cm the hand must
        stay 2 cm behind the table's near edge (--table-edge / calib table_edge_m, required to enable the arm)."""
        below = self.table_top() + 0.03 if (self.table_z is not None or P.air) else float("inf"); reach = self.low_reach(qs, below); edge = P.table_edge   # no table known yet: every point counts
        if self.log: self.log.event(ev="keepout", stage=self.state, label=label, below_z=round(below, 3), reach_x=round(reach, 3), edge_x=edge, tag="scripted skill")
        print("  %s path: below z %.3f the hand stays behind x %.3f%s" % (label, below, reach, "" if edge is None else " (taped table edge %.3f)" % edge), flush=True)
        if edge is None and not P.mock: raise motion.SkillFailed("%s: no table edge (--table-edge): the keep-out cannot be checked" % label)
        if edge is not None and reach > edge - 0.02: raise motion.SkillFailed("%s: the hand would pass x %.3f below the table top; the taped edge is %.3f" % (label, reach, edge))

    def go_home(self):
        """Home from wherever the arm is, planned first (plan_retreat), announced: the normal end of an order and the start-up park. A
        refusal, a stop or a failure holds the arm (the way home then runs only on y). True when home."""
        try: segs = self.plan_retreat()
        except motion.SkillFailed as e: self.hold("no way home: %s" % e); return False
        return self.run_retreat(segs)

    def retreat(self):
        """The normal end of an order: up first, back over the table edge, the raise retraced, home; each announced."""
        self.set_state("RECOVER", "retreat")
        return True if not self.arms_on else self.go_home()

    def park(self):
        """At start (never under --dry): the arm must already hang below the taped table top behind the raise, within 0.3 rad of home_q
        (the measured joints, before the streamer takes it); then a joint-space move to home, announced. False when nothing was enabled
        (refused) or when the arm holds (a mismatch at enable, a stop or a refusal on the way: the caller runs the hold loop)."""
        if P.dry: return True
        q = np.asarray(self.rb.arms.measured("left"), float); off = float(np.max(np.abs(q - self.home_q)))
        where = "at home" if self.at_home(q) else ("in the home region" if self.home_region(q) else "OUT of the home region")
        print("start pose: measured q %s, %.3f rad from home_q (largest joint), palm %s, fingertips %s: %s (table top %.3f)" % (r3(q), off, r3(self.arm.palm(q)), r3(geom.arm_segments(q)["tip"]), where, self.table_top()), flush=True)
        if self.log: self.log.event(ev="start_pose", q=r3(q), off_home=round(off, 3), where=where, tag="sensor gate")
        if not (self.at_home(q) or self.home_region(q)):
            print("park refused: the left arm is not at the side (palm %s): the owner lowers it by hand and restarts; nothing is enabled" % r3(self.arm.palm(q)), flush=True)
            self.say("My arm is not at my side. I will not move it."); return False
        try: self.arms_enable()
        except motion.SkillFailed as e: print("park refused: %s" % e, flush=True); return False
        took = float(np.max(np.abs(self.arm.q_cmd() - q)))
        if took > 0.10:                                                     # g1-fetch's enable must hold the measured pose, not an older one: hold, never release
            self.hold("ENABLE MISMATCH: the streamer holds %s but the arm was at %s (%.3f rad apart)" % (r3(self.arm.q_cmd()), r3(q), took)); return False
        if not self.at_home():
            self.say("Parking.")
            if not self.go_home(): return False
        if self.log: self.log.event(ev="park", stage=self.state, pose="home", q=self.home_q.tolist(), palm=r3(self.arm.palm(self.home_q)), tag="scripted skill")
        return True

    # --- one order ---------------------------------------------------------------------------------
    def order(self):
        """One order. Its normal path (look, listen, locate, then pick, probe or air, then the retreat home) runs by itself. Any stop,
        refusal or failure that leaves the arm out holds it there, and the way home runs only on y (hold_loop); the probe ends in the same
        hold. Returns False when the run ends (a stop, quit!, the scripted orders done)."""
        if not self.idle(): return False
        self.counters["orders"] += 1; n = self.counters["orders"]
        self.log = OrderLog(self.dir, n); self.o = {"n": n, "t": time.strftime("%Y-%m-%d %H:%M:%S"), "result": None, "assisted": False, "stages": [], "release": None}
        self.view.update(order=n, events=[], stages=[])
        self.log.event(ev="order", n=n, params={k: getattr(P, k) for k in ("pre", "grasp_below", "palm_real", "K", "servo_iters", "servo_tol", "psi", "clear", "pitch_max", "ik_tol", "contact", "lag", "lift", "verify", "seconds", "probe", "air", "no_gemma_hand",
                                                                             "pre_offset", "model_grasp", "no_fix", "probe_servo", "no_grasp", "speed", "table_edge", "air_table", "air_margin", "fingertip", "palm_half", "floor_margin", "blind_max")}, session=self.session, tag="scripted skill")
        for key, val, dflt in (("pre_offset", P.pre_offset, 0.0), ("no_gemma_hand", P.no_gemma_hand, False), ("air_margin", P.air_margin, 0.03), ("blind_max", P.blind_max, 0.08)):
            if val != dflt: self.log.event(ev="deviation", key=key, calib=dflt, cli=val, tag="scripted skill")
        self.log.event(ev="calib", calib_sha=CAL["_sha256"], git=calibmod.git_sha(), dirty=calibmod.git_dirty(), tag="scripted skill")
        for key, c, v in calibmod.deviations(CAL, P, CALIB_ARGS): self.log.event(ev="deviation", key=key, calib=c, cli=v, tag="scripted skill")
        self.armed = self.stops
        try: res = self.order_body()
        except Stopped: res = "stopped"; print("== stopped", flush=True)
        except SkillFailed as e:
            print("SKILL FAILED:", e, flush=True); self.log.event(ev="error", stage=self.state, error="skill: %s" % e); res = "skill_failed: %s" % e; self.say("I could not complete that move.")
        except Exception as e:
            traceback.print_exc(); self.log.event(ev="error", stage=self.state, error=traceback.format_exc()); res = "error: %s" % e; self.say("Something went wrong.")
        if self.arms_on and not self.held and not self.at_home_safe(): self.hold("the order ended with the arm out (%s)" % res)
        if self.held: self.o["held"] = self.held; self.hold_loop()          # the way home only on y; quit! leaves the arm holding
        self.finish(res)
        return not (self.quit_now or self.stops)

    def order_body(self):
        """The order's normal path; returns the result. Raises Stopped / SkillFailed / anything else to order()."""
        if P.air: return self.air()
        scene = self.look()
        if not scene: self.say("I do not see any can on the table.", wait=4.0); return "no_can"
        if P.probe: return self.probe(scene)
        idx, how = self.listen(scene)
        if idx is None:
            if how == "none": self.say("Sorry. Let us try another order.", wait=2.0); return "refused"
            self.say("Sorry, I did not catch which can you want."); return "no_choice"
        self.confirm(scene[idx]["desc"])
        tg = self.locate(idx, scene)
        if tg is None: return self.o["result"]
        if P.dry:
            self.dry_raise(tg["plan"])
            self.say("Dry run. I would pick the %s one, %d centimetres ahead and %d to my left, forearm yaw %d degrees." % (tg["desc"], round(tg["p"][0] * 100), round(tg["p"][1] * 100), tg["plan"]["psi"]), wait=4.0)
            return "dry"
        if P.no_grasp: self.say("No grasp in this run. I stop here.", wait=1.0); return "no_grasp"
        if P.K is None and not P.model_grasp:                                 # V2_REVIEW round 2: no model-only grasp unless asked for and logged
            self.say("I have no hand constant yet, so I do not grasp. The kill test measures it.", wait=2.0); return "no_K"
        if P.K is None: self.log.event(ev="deviation", key="model_grasp", calib=None, cli=True, tag="scripted skill")
        grasped = self.pick(tg) and self.lift(tg)
        if not grasped:
            self.say("Missed. Let me try once more."); self.hand.open(wait=True)
            if not self.retreat(): return "held"
            tg = self.locate(idx, scene)
            if tg is None: return self.o["result"]                           # a refused locate ends the order: no assist (V2_REVIEW round 2)
            grasped = self.pick(tg) and self.lift(tg)
            if not grasped:
                self.hand.open(wait=True)
                grasped = self.assist(scene[idx]["desc"])
                if grasped is None: return self.o["result"] or "blocked"
                if not grasped:
                    self.say("Sorry, I could not hold the can. Let us try another order."); self.hand.open(wait=True)
                    return "missed" if self.retreat() else "held"
                self.o["assisted"] = True
        self.check()
        self.handover()
        if not self.retreat(): return "held"
        return "assisted" if self.o["assisted"] else "success"

    def dry_raise(self, plan):
        """--dry: the raise the arm would run (plan_raise, the same planner and keep-out lines as the moving run), from home_q."""
        self.high_z = plan["high"][2]
        try: segs, y = self.plan_raise(self.home_q, plan["pre"][1], table_top=plan.get("table_z"))
        except motion.SkillFailed as e: print("  dry raise from home: REFUSED: %s" % e, flush=True); return
        below = (plan.get("table_z") if plan.get("table_z") is not None else self.table_top()) + 0.03
        print("  dry raise from home (candidate y %.3f): up-low below z %.3f stays behind x %.3f, up behind x %.3f%s" % (
              y, below, self.low_reach(segs[0][2], below), self.low_reach(segs[1][2], below), "" if P.table_edge is None else " (taped table edge %.3f)" % P.table_edge), flush=True)

    def probe(self, scene):
        """--probe (the kill test, experiment 2): the chosen can, the plan, the pre-grasp, 5 measurements of the hand features and the can
        with Gemma's box of the hand, the result spoken and stored; then, with --probe-servo and K, the servo iterations, each correction
        only on y. The probe ends holding: nothing moves after the pause without y (the way home). A probe is flagged (stored as
        off_flagged, not spoken, never a source of K) when the blob is cut off, the near face lies inside the can, Gemma's box is missing
        or under 50% on the blob, or off - model_off is outside d 0.03-0.12, n 0-0.04, z 0-0.07."""
        idx = min(max(0, P.probe_can), len(scene) - 1); tg = self.locate(idx, scene)
        if tg is None: return self.o["result"]
        if P.dry:
            self.dry_raise(tg["plan"]); self.say("Dry run. I would measure at the %s one, forearm yaw %d degrees." % (tg["desc"], tg["plan"]["psi"]), wait=3.0); return "dry"
        self.set_state("PICK", "probe"); self.to_pregrasp(tg); self.say("Measuring."); self.sleep(P.pause)
        m = self.measure(tg, "probe", frames=max(5, P.frames), gemma_box=not P.no_gemma_hand)
        keep = ("can", "blob", "model_palm", "model_off", "feat", "err", "n_blob", "scatter", "gemma_vs_blob", "gemma_on_blob", "gemma_box", "edge_px", "win_edge_px", "in_view", "frames_in_view", "near_inside_can")
        self.o["probe"] = {k: (r3(v) if isinstance(v, np.ndarray) else v) for k, v in m.items() if k in keep}
        why = ""
        if "off" not in m: why = "I could not see my hand and the can together"
        elif m.get("near_inside_can"): why = "my hand looks too close to the can"
        elif not m.get("in_view"): why = "my hand is at the edge of what I can measure"
        elif not P.no_gemma_hand and (m.get("gemma_on_blob") is None or m["gemma_on_blob"] < 0.5): why = "Gemma did not confirm my hand"
        else:
            dd = [float(a) - float(b) for a, b in zip(m["off"], m["model_off"])]; self.o["probe"]["off_minus_model"] = [round(v, 4) for v in dd]
            print("  probe: off - model_off %s (expected d 0.03-0.12, n 0.00-0.04, z 0.00-0.07)" % [round(v, 3) for v in dd], flush=True)
            if not (0.03 <= dd[0] <= 0.12 and 0.0 <= dd[1] <= 0.04 and 0.0 <= dd[2] <= 0.07): why = "the reading is outside the expected range"
        if "off" in m: self.o["probe"]["off_flagged" if why else "off"] = m["off"]                        # K comes only from an unflagged probe
        if why: print("  probe FLAGGED: %s: not used" % why, flush=True); self.say("%s%s. Not used." % (why[0].upper(), why[1:]), wait=2.0)
        else: self.say("Measured. Fingertip %d, near face %d, height %d millimetres from the can axis; the model palm %d, %d, %d." % tuple(round(v * 1000) for v in (list(m["off"]) + list(m["model_off"]))), wait=3.0)
        if P.probe_servo and P.K: self.servo(tg)
        self.hold("the probe is done: nothing moves after it without y"); return "probe"

    def table_at(self, frame, p):
        """Table plane fitted in a depth window around the projected point p (pelvis frame), WITHOUT a height hint (a hint would hide
        a tape error over 6 cm behind the fit's own gate); None if no level plane is seen."""
        uv = geom.pelvis_to_pixel(self.rb.frames, frame.intrinsics, p)
        if uv is None: return None
        pts, uu, vv = geom.cloud_in_window(frame, self.rb.frames, uv[0], uv[1], 70, 50, 3)
        return geom.table_plane(pts, z_hint=None) if pts.shape[0] else None

    def air(self):
        """--air (experiment 3, no can). One head frame first: the 0.30 m rule (refused as locate refuses) and the table under the
        target (a depth fit more than 2 cm from the taped height refuses). The virtual can's axis at table + h/2 + 3 cm, planned with a
        5 cm standoff; raise and high uncorrected (the sag baseline), the corrected pre-grasp, the tracking baseline, five corrected
        1 cm steps along n (each printing the measured advance), the slide-end error, back, retreat. --dry stops before any motion."""
        self.set_state("LOCATE", "air")
        if P.air_table is None: self.say("The air test needs the taped table height."); return "air_no_table"
        h, margin = 0.122, P.air_margin; z_axis = P.air_table + h / 2 + margin
        print("  air target: axis z = table %.3f + half can height %.3f + margin %.3f = %.3f; the planned palm centre z = axis - %.3f, its lowest point table + %.3f" % (
              P.air_table, h / 2, margin, z_axis, P.grasp_below, z_axis - P.grasp_below - cv("palm_half_height_m") - P.air_table), flush=True)
        frame = self.head_frame(); self.bundle("air_check", frame, {"air_can": P.air_can, "air_table": P.air_table})
        if not self.ahead_clear(frame, "air"): return "blocked"
        seen = self.table_at(frame, np.array([P.air_can[0], P.air_can[1], P.air_table]))
        self.log.event(ev="plane", stage=self.state, plane=None if seen is None else {"z": round(seen["z"], 3), "n_in": seen["n_in"], "tilt_deg": round(seen["tilt_deg"], 1)}, tape=P.air_table, tag="sensor gate")
        if seen is None:
            print("  table under the air target: not fitted from depth (tape %.3f): no motion" % P.air_table, flush=True)
            self.say("I cannot see the table under the air target. I stop.", wait=3.0); return "air_table_not_seen"
        if abs(seen["z"] - P.air_table) > 0.02:
            print("  table under the air target: depth %.3f vs tape %.3f: more than 2 cm apart" % (seen["z"], P.air_table), flush=True)
            self.say("The table I see is not where the tape says. I stop.", wait=3.0); return "air_table_mismatch"
        print("  table under the air target: depth %.3f (tape %.3f)" % (seen["z"], P.air_table), flush=True)
        self.table_z = P.air_table                                               # the REAL table for the keep-out and the floor, not the virtual one
        zt = z_axis - h / 2
        tg = {"p": np.array([P.air_can[0], P.air_can[1], z_axis]), "diam": 0.066, "h": h, "box": [0, 0, 1, 1], "others": [], "desc": "air target",
              "plane": {"z": zt, "n": np.array([0.0, 0.0, 1.0]), "d": zt, "n_in": 0, "tilt_deg": 0.0}}     # the virtual table 3 cm above the real one
        plan = self.plan(tg, pre=max(P.pre, 0.05))
        if "psi" not in plan: self.say("No plan for the air target."); return "air_no_plan"
        tg["plan"] = plan; plan["table_z"] = P.air_table                       # the floor from the real table (the virtual one is 3 cm higher)
        if P.dry:
            self.dry_raise(plan)
            self.say("Dry run. The air target plans at forearm yaw %d degrees." % plan["psi"], wait=3.0); return "dry"
        self.set_state("PICK", "air"); m_pre = self.to_pregrasp(tg); self.say("Pre-grasp. Baseline."); self.sleep(P.pause)
        base = self.arm.tracking(); self.log.event(ev="baseline", stage=self.state, tracking=round(base, 4), tag="sensor gate"); print("  tracking baseline %.3f rad" % base, flush=True)
        try: self.measure(tg, "air")
        except Exception as e: print("  measure in air failed:", e)
        start = self.arm.palm_meas(); self.say("Sliding.")          # no sag reference: across the body the sag grows over 1 cm in 4 cm; the stall stop ends a run-away
        for k in range(5):
            self.clear_or_hold("air step %d" % k)
            before = self.arm.palm_meas(); m, te = self.arm.step_along(plan["n"], 0.01, "air%d" % k, target=start + plan["n"] * 0.01 * (k + 1)); moved = float((m - before) @ plan["n"])
            self.log.event(ev="ap_step", stage=self.state, step=k, moved=round(moved, 4), measured=r3(m), tracking=round(te, 4), base=round(base, 4), q_cmd=r3(self.arm.q_cmd()), q_meas=r3(self.arm.q_meas()), tag="scripted skill")
            print("  air%d: moved %.3f along n (commanded 0.010), tracking %.3f (base %.3f)" % (k, moved, te, base), flush=True)
            if moved < 0.005 or te > base + max(P.contact, base): raise motion.SkillFailed("air step %d: the hand moved %.3f with tracking %.3f (base %.3f): stalled (contact?)" % (k, moved, te, base))
        end_p = self.arm.palm_meas(); want = start + plan["n"] * 0.05; slide_err = float(np.linalg.norm(end_p - want))
        print("  slide end: measured palm %s, expected %s, error %.3f (pass under 0.010)" % (r3(end_p), r3(want), slide_err), flush=True); self.sleep(1.0)
        back0 = self.arm.palm_meas(); self.say("Back.")
        for k in range(5):
            self.clear_or_hold("back step %d" % k); b0 = self.arm.palm_meas(); mb, te = self.arm.step_along(-plan["n"], 0.01, "back%d" % k, target=back0 - plan["n"] * 0.01 * (k + 1))
            if float((mb - b0) @ -plan["n"]) < 0.005 or te > base + max(P.contact, base): raise motion.SkillFailed("back step %d: the hand did not follow: stalled (contact?)" % k)
        self.o["air"] = {"psi": plan["psi"], "sag": self.o.get("sag"), "pre_err": self.o.get("pre_err"), "tracking_base": round(base, 4), "slide_err": round(slide_err, 4)}
        return "air" if self.retreat() else "held"

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

    def at_home_safe(self):
        try: return self.at_home()
        except Exception as e: print("arm state unreadable: %s" % e, flush=True); return False

    def shutdown(self):
        """The end of the run. The arm away from home (only after an error escaped an order): it holds and the way home runs only on y.
        At home: the hand opens and the arm is released, announced. quit!: exit without moving or releasing anything (the robot in
        damping, L2+B)."""
        print("== shutting down", flush=True)
        self.state = "OFF"; self.view.update(state="OFF", message="brain stopped")
        try:
            if not self.quit_now and self.arms_on and not self.at_home_safe():
                if not self.held: self.hold("the arm is away from home at the end")
                self.hold_loop()
        except BaseException as e: print("hold at the end failed: %r" % e, flush=True)
        if self.quit_now or (self.arms_on and not self.at_home_safe()):
            where = "at home" if self.arms_on and self.at_home_safe() else ("away from home" if self.arms_on else "not enabled")
            print("== exiting WITHOUT moving or releasing the arm (%s): the robot must be in damping (L2+B); the streamer holds its last target until the process ends" % where, flush=True)
            if self.log: self.log.event(ev="exit_holding", palm=(self.held or {}).get("palm"), tag="scripted skill"); self.log.close()
            self.view_off = True; return
        steps = [] if P.dry else [lambda: self.hand.set(THUMB_PRE), lambda: time.sleep(0.8), lambda: self.hand.open(wait=True)]
        if self.arms_on: self.say("Releasing my arm.")
        for step in steps + [self.arms_disable, self.rb.close, self.cam3.close]:
            try: step()
            except Exception as e: print("shutdown step failed:", e)
        try: print("arm service on ->", set_arm_action_service(True), flush=True)
        except Exception as e: print("arm service switch failed:", e)
        if self.log: self.log.close()
        self.view_off = True


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
    if P.expect_calib is None and not P.mock:                            # every robot command carries it (the run plan)
        print("REFUSED: no --expect-calib SHA16: the calib identity must be checked on the robot (python calib.py | head -1)"); sys.exit(1)
    if P.expect_calib is not None:                                      # DEV_WORKFLOW: calib hash mismatch or a dirty tree = the robot does not move
        state = calibmod.git_state()
        if CAL["_sha256"] != P.expect_calib or state != "clean":
            print("CALIB IDENTITY FAILED: calib.json sha %s, expected %s; the tree is %s: the robot does not move" % (CAL["_sha256"], P.expect_calib, state)); sys.exit(1)
        print("calib identity: sha %s as expected, tree clean" % CAL["_sha256"], flush=True)
    st = calibmod.stale(CAL)
    if st and not P.accept_calib: print("STALE calibration entries: %s. Re-measure, or start with --accept-calib." % st); sys.exit(1)
    dev = calibmod.deviations(CAL, P, CALIB_ARGS)
    if dev: print("CLI overrides of calib.json (logged as deviations):", dev, flush=True)
    if not P.no_preflight: run_preflight()
    brain = Brain()
    def on_signal(signum, frame): brain.stop_key({signal.SIGINT: "ctrl-c", signal.SIGTERM: "sigterm", signal.SIGHUP: "sighup"}.get(signum, "signal"))   # counts a stop, never raises
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(s, on_signal)
    try:
        if P.dry: print("--dry: the arm is not enabled and does not move (no park)", flush=True); ok = True
        else:
            ok = brain.park()
            if not ok and brain.held: brain.hold_loop()                       # a stop or a mismatch on the way home at start: the way home on y
            print("left arm at home: real palm at %s" % r3(brain.arm.palm(brain.home_q)) if ok else "startup park refused", flush=True)
        if ok: brain.say("Ready.")
        while ok and not brain.quit_now and not brain.stops and (not P.orders or brain.counters["orders"] < P.orders):
            if not brain.order(): break
    finally:
        brain.shutdown()

if __name__ == "__main__":
    main()
