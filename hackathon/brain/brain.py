"""Hackathon brain: ONE long-running process that runs the drinks-host loop on the G1 (left hand, robot in its stand, FSM 500).
IDLE > LISTEN > UNDERSTAND > CONFIRM > LOCATE > PICK > VERIFY > LIFT > CHECK > HANDOVER (> RECOVER) > IDLE ...
Robot, cameras, detector, hand and llama-server stay warm between orders. The mechanics and parameters are the verified ones
from spikes/scripts/grab_loop.py and voice_grab.py (8 grasps in a row, 2 honest negatives, 0 wrong-can picks).
Usage (PC2, g1fetch env):  python brain.py [--manual] [--venue] [--no-preflight] [--mock] [pick/lane/timing parameters]
Keys on stdin: q quit (safe release)  a abort this order  r release the can now  p pause/resume  Enter start an order (--manual)
Ctrl-C / SIGTERM: safe release (hand open, arm streamer disabled, arm service back on)."""
import argparse, glob, json, os, re, shlex, signal, subprocess, sys, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
XDIR_, PALM_ = (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)
STAGES_THUMB = (([0.0, 0.8, 0, 0, 0, 0], 1.0), ([0.0, 0.8, 0.9, 0.9, 0.9, 0.9], 1.5), ([0.9, 0.8, 0.9, 0.9, 0.9, 0.9], 1.0))
THUMB_PRE, OPEN6 = [0.0, 0.8, 0.0, 0.0, 0.0, 0.0], [0.0] * 6
PARK_ZERO = [0.0, 0.0, 0.0, 0.0, 0.0]        # Unitree joint zero for the 5 left-arm joints (g1-docs 00_about_G1: 关节零点)
PROMPTS = {"ask": "Which can would you like? Tell me the colour.", "again": "Please say the colour again.", "listening": "Listening."}
OWN_WORDS = ("holding the", "say take", "please take")       # the robot's own handover sentences, heard through the C922 (self-release on 2026-10-21)


def parse():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_argument_group("pick (verified defaults)")
    g.add_argument("--dx", type=float, default=-0.096, help="palm centre x offset vs the can axis (calibrated palm offset)")
    g.add_argument("--dz", type=float, default=0.0, help="palm centre above the can mid-height")
    g.add_argument("--pre", type=float, default=0.05, help="pre-grasp offset to the can's left")
    g.add_argument("--contact", type=float, default=0.015, help="tracking-error rise (rad) that counts as contact")
    g.add_argument("--press", type=float, default=0.02, help="slide this far past the can's near surface")
    g.add_argument("--tol", type=float, default=0.035, help="IK position tolerance")
    g.add_argument("--pause", type=float, default=4.0, help="pause at the pre-grasp before the slide")
    g.add_argument("--diam", type=float, default=0.0, help="can diameter; 0 = classify from the box width (55/66 mm)")
    g.add_argument("--no-prethumb", action="store_true", help="do not oppose the thumb before the slide")
    g.add_argument("--no-servo", action="store_true", help="no proprioceptive correction at the pre-grasp")
    g.add_argument("--lift", type=float, default=0.06)
    g.add_argument("--park", choices=["zero", "home", "release"], default="zero",
                   help="left-arm pose between orders: zero = Unitree joint zero (elbow bent, forearm forward; streamer stays on), home = g1-fetch home_q, release = fade the streamer out (arm drops to the controller's pose)")
    g.add_argument("--verify", choices=["strict", "majority"], default="strict", help="strict: every finger stalled in (0.15, 0.82); majority: thumb stalled below 0.3 and at least 3 of 4 fingers stalled")
    g = ap.add_argument_group("lane (pelvis frame: x ahead, y left)")
    g.add_argument("--lane-y", type=float, nargs=2, default=[0.06, 0.30], metavar=("LO", "HI"))
    g.add_argument("--lane-x", type=float, nargs=2, default=[0.31, 0.50], metavar=("LO", "HI"), help="can AXIS ahead of the pelvis; the jog reached an axis at 0.507 (palm limit 0.41 + 0.097)")
    g.add_argument("--relook", type=int, default=1, help="re-looks after asking the guest to move an out-of-lane can")
    g = ap.add_argument_group("voice and handover")
    g.add_argument("--seconds", type=float, default=4.0, help="order recording length")
    g.add_argument("--mic", default="auto", help="ALSA capture device, auto = the C922 card")
    g.add_argument("--cam3", default="auto", help="third-person camera node, auto = the C922 by-id node")
    g.add_argument("--retries", type=int, default=3, help="listen attempts per order")
    g.add_argument("--assist-wait", type=float, default=8.0, help="seconds for the guest to place the can after two misses")
    g.add_argument("--hold-reminder", type=float, default=15.0, help="seconds between 'take it' reminders while holding")
    g.add_argument("--release-after", type=float, default=0.0, help="rehearsal: release after this many seconds (0 = only on the guest)")
    g.add_argument("--hand-q", default=None, help="override the human-hand yes/no question")
    g = ap.add_argument_group("system")
    g.add_argument("--server", default="http://127.0.0.1:8080/v1")
    g.add_argument("--g1fetch", default=os.environ.get("G1FETCH", "/home/unitree/g1-fetch"))
    g.add_argument("--runs", default=os.path.join(HERE, "runs"))
    g.add_argument("--manual", action="store_true", help="wait for Enter in IDLE instead of listening continuously")
    g.add_argument("--dry", action="store_true", help="no arm motion: listen, locate, report the target and stop before PICK")
    g.add_argument("--idle", type=float, default=1.0, help="seconds in IDLE between orders")
    g.add_argument("--orders", type=int, default=0, help="stop after this many orders (0 = run until q / Ctrl-C)")
    g.add_argument("--venue", action="store_true", help="preflight: no-cloud checks are hard failures")
    g.add_argument("--no-preflight", action="store_true")
    g.add_argument("--preflight-args", default="", help="extra preflight.py arguments")
    g.add_argument("--mock", action="store_true", help="Mac: mock robot, mic and third-person camera (mock_robot.py)")
    g.add_argument("--mock-gemma", action="store_true", help="Mac: scripted Gemma answers, no server")
    return ap.parse_args()


P = parse()
if P.mock:
    import mock_robot; MOCK = mock_robot.install(P)
import numpy as np, cv2
from gemma import Gemma, SYN, IN_HAND_Q, HUMAN_HAND_Q
if P.mock_gemma: import mock_robot; Gemma = mock_robot.mock_gemma(Gemma)
sys.path.insert(0, P.g1fetch)
if os.path.isdir(P.g1fetch): os.chdir(P.g1fetch)        # configs/pc2.yaml and the detector weights resolve from here
from g1_fetch.config import load_config
cfg = load_config(os.path.join(P.g1fetch, "configs", "pc2.yaml"))
cfg.fridge.can_diameter_m = P.diam; cfg.arm.ik_max_pos_err = P.tol
cfg.cameras.head.enabled = False                          # the SR300 head camera is gone; the C922 is the third-person view
from g1_fetch.robot import build_robot
from g1_fetch.perception.localize import can_axis_from_box, median_depth
from g1_fetch.skills.common import go_home, cart_move, solve_pose, SkillFailed
from g1_fetch.control.robot_state import set_arm_action_service
XDIR, PALM = np.array(XDIR_), np.array(PALM_)


class Abort(Exception): pass          # quit the program (signal or 'q')
class OrderAborted(Exception): pass   # abort this order only ('a')


def atomic_write(path, data, mode="w"):
    tmp = path + ".tmp"
    with open(tmp, mode) as f: f.write(data)
    os.replace(tmp, path)


class View:
    """Status for brainview.py: runs/live/status.json plus frame.jpg, replaced atomically."""
    def __init__(self, live):
        self.live = live; os.makedirs(live, exist_ok=True); self.frame_v = 0; self.lock = threading.Lock()
        self.s = {"state": "BOOT", "order": 0, "colour": None, "message": "", "last": None, "tag": "", "events": [], "stages": [],
                  "counters": {}, "frame_v": 0, "frame_label": "", "paused": False, "note": "", "pid": os.getpid()}
        self.update()
    def update(self, **kv):
        with self.lock:                                   # the live-frame thread and the state machine both write
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
    """One JSON-lines file per order (every Gemma call, stage timings, result) plus a folder of frames."""
    def __init__(self, session_dir, n):
        self.path = os.path.join(session_dir, "order_%02d.jsonl" % n); self.frames = os.path.join(session_dir, "order_%02d" % n)
        os.makedirs(self.frames, exist_ok=True); self.f = open(self.path, "a")
    def event(self, **rec):
        rec.setdefault("t", time.time()); self.f.write(json.dumps(rec, default=str) + "\n"); self.f.flush()
    def save(self, name, bgr):
        path = os.path.join(self.frames, name); cv2.imwrite(path, bgr, [cv2.IMWRITE_JPEG_QUALITY, 88]); return path
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
    """The C922 as the third-person camera, opened once and kept warm. A thread keeps dequeuing frames (grab, no decode) so a shot
    is the live frame: with on-demand reads the V4L2 buffer handed out frames from the previous stage (seen on 2026-10-21)."""
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
        self.counters = {"orders": 0, "autonomous": 0, "honest_negatives": 0, "assisted": 0, "manual_release": 0, "failed": 0, "grasps": 0, "misses": 0}
        self.quit = self.abort = self.release_now = self.paused = self.go = False
        self.log = None; self.o = None; self.state = "BOOT"; self.stage_t0 = time.time(); self.arms_on = False; self.frame_hold = False
        self.cam_lock = threading.Lock()
        self.gem = Gemma(P.server, self.on_gemma)
        self.view.update(state="BOOT", message="building robot, camera, detector", counters=self.counters, session=self.session)
        t0 = time.time()
        self.rb = build_robot(cfg)                      # DDS, loco (read-only), arm streamer, hands, D435i, YOLOE; arm service off
        self.hand = self.rb.hands["left"]
        self.mic = Mic(P.mic) if not P.mock else MOCK["mic"]
        self.cam3 = Cam3(P.cam3) if not P.mock else MOCK["cam3"]
        print("robot ready in %.1f s; mic %s; cam3 %s; runs %s" % (time.time() - t0, self.mic.device, getattr(self.cam3, "node", "?"), self.dir), flush=True)
        if sys.stdin is not None and sys.stdin.isatty(): threading.Thread(target=self.keys, daemon=True).start()
        threading.Thread(target=self.live_frames, daemon=True).start()

    # --- plumbing --------------------------------------------------------------------------------
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
        if self.log: self.log.event(ev="say", stage=self.state, text=text, tag="scripted skill")
        self.view.update(message=text)
        if wait: self.sleep(wait)

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
            elif k == "": self.go = True

    def live_frames(self):
        """Head-camera frame for the view at ~2 Hz while nothing else owns the camera."""
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

    def hand_meas(self):
        return self.rb.kin.fk("left", self.rb.arms.measured("left"))[:3, 3]

    def move(self, goal, speed, tol=0.04, servo=True, label=""):
        """Cartesian move, then up to two proprioceptive corrections so the MEASURED hand reaches the goal (grab_loop.py)."""
        self.check_abort(); goal = np.asarray(goal, float)
        cart_move(self.rb, "left", goal, XDIR, PALM, speed=speed, tol=tol)
        time.sleep(0.4); cmd = goal.copy()
        for i in range(2 if servo else 0):
            err = goal - self.hand_meas()
            if np.linalg.norm(err) < 0.008: break
            cmd = cmd + err
            q, res = solve_pose(self.rb, "left", cmd, XDIR, PALM, q_seed=self.rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
            self.rb.arms.set_target("left", q); time.sleep(0.6)
        m = self.hand_meas()
        print("  %s: goal %s measured %s err %.3f" % (label, np.round(goal, 3).tolist(), np.round(m, 3).tolist(), np.linalg.norm(goal - m)), flush=True)
        self.log.event(ev="move", stage=self.state, label=label, goal=np.round(goal, 3).tolist(), measured=np.round(m, 3).tolist(), err=round(float(np.linalg.norm(goal - m)), 4), tag="scripted skill")
        return m

    def arms_enable(self):
        if not self.arms_on: self.rb.arms.enable(); self.arms_on = True
    def arms_disable(self):
        if self.arms_on:
            try: self.rb.arms.disable()
            finally: self.arms_on = False

    # --- states ----------------------------------------------------------------------------------
    def idle(self):
        self.set_state("IDLE"); self.frame_hold = False; self.go = False
        self.view.update(colour=None, message="", stages=[], counters=self.counters)
        t_end = time.time() + P.idle
        while not self.quit:
            if getattr(self.mic, "done", False): self.quit = True; break          # mock: scripted orders exhausted
            if P.manual and not self.go and not P.mock and sys.stdin is not None and sys.stdin.isatty(): time.sleep(0.1); continue
            if self.paused: time.sleep(0.2); continue
            if time.time() < t_end: time.sleep(0.05); continue
            return True
        return False

    def listen(self):
        """LISTEN + UNDERSTAND with retries: TTS prompt, 4 s clip from the C922, Gemma names the colour from the audio."""
        for attempt in range(P.retries):
            self.set_state("LISTEN", "attempt %d" % (attempt + 1))
            self.say(PROMPTS["ask"] if attempt == 0 else PROMPTS["again"], wait=2.8 if attempt == 0 else 1.6)
            self.say(PROMPTS["listening"], wait=0.6)
            clip = os.path.join(self.log.frames, "order_%d.wav" % (attempt + 1)); t0 = time.time()
            try: wav = self.mic.record(P.seconds, clip)
            except Exception as e:
                print("record failed:", e); self.log.event(ev="error", stage=self.state, error="record: %s" % e); self.say("My microphone failed.", wait=1.5); continue
            self.log.event(ev="record", stage=self.state, seconds=P.seconds, bytes=len(wav), ms=int((time.time() - t0) * 1000), path=clip, tag="scripted skill")
            self.set_state("UNDERSTAND")
            colour, ans, rec = self.gem.hear_colour(wav)
            self.o.setdefault("heard", []).append(ans)
            if colour: return colour
        return None

    def confirm(self, colour):
        self.set_state("CONFIRM", colour); self.o["colour"] = colour; self.view.update(colour=colour)
        self.say("The %s can. Coming up." % colour, wait=1.0)

    def lane_reason(self, p, colour):
        (ylo, yhi), (xlo, xhi) = P.lane_y, P.lane_x
        if p[1] < ylo: return "That %s can is too close to my centre line for my left hand. Please move it to my left." % colour
        if p[1] > yhi: return "That %s can is too far to my left. Please move it closer to my centre." % colour
        if p[0] < xlo: return "That %s can is too close to me. Please move it a little further away." % colour
        if p[0] > xhi: return "That %s can is too far away. Please move it closer to me." % colour
        return None

    def locate(self, colour, relook=None):
        """YOLOE can boxes, Gemma colour per crop, the requested colour's can located in the pelvis frame, lane guard."""
        relook = P.relook if relook is None else relook
        self.set_state("LOCATE", colour); self.frame_hold = True
        frame = self.head_frame()
        t0 = time.perf_counter(); cans = sorted([d for d in self.rb.detector.detect(frame.color) if d.label == "can"], key=lambda d: d.box[0])
        self.log.event(ev="detect", stage=self.state, n=len(cans), ms=int((time.perf_counter() - t0) * 1000), boxes=[[int(v) for v in d.box] for d in cans], conf=[round(float(d.conf), 2) for d in cans], tag="scripted skill")
        want = SYN.get(colour, {colour}); colours = []
        for i, d in enumerate(cans):
            x1, y1, x2, y2 = [int(v) for v in d.box]; m = 10
            crop = frame.color[max(0, y1 - m):min(480, y2 + m), max(0, x1 - m):min(640, x2 + m)]
            c = self.gem.crop_colour(crop, media="can %d" % i)[0] if crop.size else ""
            colours.append((d, c))
        verified = [d for d, c in colours if any(w in c for w in want)]
        self.o["colour_check"] = [c for _, c in colours]
        cands = []
        for d in verified:
            p = can_axis_from_box(frame, d, self.rb.frames, cfg); z = median_depth(frame, d.box, 0.5)
            if p is not None and z: cands.append((d, p, z))
        in_lane = [c for c in cands if self.lane_reason(c[1], colour) is None]
        pick = max(in_lane or cands, key=lambda c: c[0].conf) if cands else None
        vis = frame.color.copy()
        for d, c in colours:
            col = (0, 255, 0) if pick and d is pick[0] else (255, 128, 0)
            cv2.rectangle(vis, (int(d.box[0]), int(d.box[1])), (int(d.box[2]), int(d.box[3])), col, 3 if pick and d is pick[0] else 2)
            cv2.putText(vis, c, (int(d.box[0]), max(14, int(d.box[1]) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
        label = "%s: %d can(s) %s" % (colour, len(cans), [c for _, c in colours])
        if pick: label += " -> target at x %.2f y %.2f m" % (pick[1][0], pick[1][1])
        self.log.save("head_boxes.jpg", vis); self.view.frame(vis, label)
        if not cans:
            self.say("I do not see any can on the table.", wait=2.5); self.o["result"] = "no_can"; return None
        if not verified:
            seen = sorted({c.split()[0] for _, c in colours if c})
            self.say("I do not see a %s can. I see %s." % (colour, " and ".join(seen)) if seen else "I do not see a %s can." % colour, wait=3.5)
            self.o["result"] = "refused"; return None
        if not cands:
            self.say("I see the %s can but I cannot measure where it is." % colour, wait=3.0); self.o["result"] = "no_depth"; return None
        d, p, z = pick
        w_m = d.width * z / frame.intrinsics.fx; h_m = d.height * z / frame.intrinsics.fy
        diam = P.diam or (0.055 if w_m < 0.060 else 0.066)
        p = np.asarray(p, float) + np.array([diam / 2 - float(cfg.fridge.can_diameter_m) / 2, 0.0, 0.0])
        # can_axis_from_box pushes the front-surface depth back by cfg.fridge.can_diameter_m / 2; with the diameter classified here
        # the point is moved to the true axis. The palm offset dx (-0.096) was calibrated with jog_x.py against the true axis;
        # grab_loop.py in auto mode grasped the front surface, 3.3 cm nearer, which put a sleek can at the fingertips (2026-10-21).
        tg = {"p": p, "diam": diam, "box": [int(v) for v in d.box], "z": round(float(z), 3), "size_m": [round(float(w_m), 3), round(float(h_m), 3)],
              "colour_seen": next(c for dd, c in colours if dd is d), "n_cans": len(cans)}
        print("  target %s can at pelvis %s, box %s, %.2f m, width %.3f m -> diameter %.3f" % (colour, np.round(p, 3).tolist(), tg["box"], z, w_m, diam), flush=True)
        self.log.event(ev="target", stage=self.state, colour=colour, p=np.round(p, 3).tolist(), diam=diam, box=tg["box"], z=tg["z"], size_m=tg["size_m"], colour_seen=tg["colour_seen"], tag="scripted skill")
        self.o["target"] = {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in tg.items()}
        reason = self.lane_reason(p, colour)
        if reason:
            self.log.event(ev="lane", stage=self.state, p=np.round(p, 3).tolist(), reason=reason, tag="scripted skill")
            if relook > 0:
                self.say(reason + " I will look again in five seconds.", wait=6.0); return self.locate(colour, relook - 1)
            self.say(reason + " Then order again.", wait=5.0); self.o["result"] = "outside_lane"; return None
        grasp = tg["p"] + np.array([P.dx, diam / 2 + 0.01, P.dz])
        res = self.rb.kin.ik("left", grasp, XDIR, q_seed=self.rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
        self.o["ik_err"] = round(float(res.pos_err), 4)
        print("  grasp %s IK err %.3f (floor %.2f m)" % (np.round(grasp, 3).tolist(), res.pos_err, self.rb.frames.floor_height(tg["p"])), flush=True)
        if res.pos_err > P.tol:
            self.say("The %s can is out of my reach. Please move it a little closer to my left hand." % colour, wait=4.0); self.o["result"] = "unreachable"; return None
        self.tg_last = tg
        return tg

    def pick(self, tg):
        """Raise, reach high, lower beside the can, thumb first, slide to contact, staged grasp (grab_loop.py), then VERIFY."""
        self.set_state("PICK"); p, R = tg["p"], tg["diam"] / 2; self.at_offer = False
        grasp = p + np.array([P.dx, R + 0.01, P.dz]); pre = grasp + np.array([0.0, P.pre, 0.0]); self.grasp_z = grasp[2]
        self.arms_enable(); self.hand.open(wait=False); self.rb.hands["right"].open(wait=False)
        go_home(self.rb, "left", duration=2.0); self.home_p = self.hand_meas(); self.pre = pre
        up = np.array([self.home_p[0] + 0.05, pre[1], grasp[2] + 0.12]); high = np.array([pre[0], pre[1], grasp[2] + 0.12])
        self.say("Raising."); self.move(up, 0.10, servo=False, label="up")
        self.say("Reaching."); self.move(high, 0.08, servo=False, label="high")
        self.say("Lowering beside the can."); m_pre = self.move(pre, 0.05, tol=P.tol, servo=not P.no_servo, label="pre")
        self.o["pre_measured"] = np.round(m_pre, 3).tolist(); self.cam3_shot("pregrasp"); self.sleep(P.pause)
        if not P.no_prethumb: self.hand.set(THUMB_PRE); self.say("Thumb first."); self.sleep(1.2)
        self.say("Sliding."); base = self.rb.arms.tracking_error("left")
        cur = pre.copy(); goal_y = p[1] + R - P.press; contact = False; step = 0; why = ""
        lag0 = float(self.hand_meas()[1] - cur[1])
        while cur[1] > goal_y:
            self.check_abort(); cur[1] = max(goal_y, cur[1] - 0.01); step += 1
            q, res = solve_pose(self.rb, "left", cur, XDIR, PALM, q_seed=self.rb.arms.cmd["left"], dir_weight=float(cfg.arm.ik_dir_weight))
            self.rb.arms.set_target("left", q); time.sleep(0.25)
            err = self.rb.arms.tracking_error("left"); lag = float(self.hand_meas()[1] - cur[1]) - lag0
            if err > base + P.contact: contact = True; why = "tracking error %.3f > base %.3f + %.3f" % (err, base, P.contact); break
            if lag > 0.012: contact = True; why = "hand lags the command by %.3f m in y" % lag; break
        self.m_slide = self.hand_meas()
        print("  slide: steps %d contact %s (%s) cmd y %.3f measured %s" % (step, contact, why or "none", cur[1], np.round(self.m_slide, 3).tolist()), flush=True)
        self.o.update(slide_steps=step, contact=contact, contact_why=why, slide_measured=np.round(self.m_slide, 3).tolist())
        self.log.event(ev="slide", stage=self.state, steps=step, contact=contact, why=why, tag="scripted skill")
        self.cam3_shot("slide"); self.sleep(0.3)
        for q6, dt in (STAGES_THUMB[1:] if not P.no_prethumb else STAGES_THUMB): self.hand.set(q6); self.sleep(dt)
        self.cam3_shot("closed")
        return self.verify()

    def verify(self):
        """Grasp verified by the finger stall: every finger between 0.15 and 0.82 (not blocked open, not closed on nothing)."""
        self.set_state("VERIFY"); closed = float(self.hand.closed_fraction()); state = self.hand.state()
        fingers = list(state[2:]) if state is not None else None
        stalled = [0.15 < f < 0.82 for f in fingers] if fingers else []
        if P.verify == "majority": grasped = bool(fingers) and float(state[0]) < 0.3 and sum(stalled) >= 3
        else: grasped = bool(fingers) and all(stalled)
        self.o["closure"] = round(closed, 3); self.o["hand_state"] = None if state is None else np.round(state, 2).tolist()
        self.counters["grasps" if grasped else "misses"] += 1
        print("  closure %.2f state %s -> %s" % (closed, self.o["hand_state"], "GRASPED" if grasped else "MISSED"), flush=True)
        self.log.event(ev="verify", stage=self.state, closure=self.o["closure"], hand_state=self.o["hand_state"], grasped=grasped, rule=P.verify, stalled=stalled, tag="sensor gate")
        self.view.event({"ev": "verify", "stage": "VERIFY", "kind": "finger stall", "question": "every finger stalled between 0.15 and 0.82?", "answer": "yes, grasped" if grasped else "no, missed", "ms": 0, "tag": "sensor gate", "t": time.time()})
        return grasped

    def lift(self):
        self.set_state("LIFT"); self.say("Grasped. Lifting.")
        self.m_lift = self.move(self.m_slide + np.array([0.0, 0.0, P.lift]), 0.04, servo=True, label="lift"); self.sleep(1.0)
        self.o["closure_after_lift"] = round(float(self.hand.closed_fraction()), 3)

    def check(self):
        """Third-person Gemma yes/no after the lift: advisory only (1 of 2 wrong on held cans in the office trials)."""
        self.set_state("CHECK"); fr, path = self.cam3_shot("lifted")
        if fr is None: self.o["gemma_in_hand"] = None; return
        v, ans, rec = self.gem.yesno(fr, IN_HAND_Q, "CHECK", media=path, tag="Gemma advisory")
        self.o["gemma_in_hand"] = ans

    def handover(self):
        """Offer the can; release on a human hand seen twice in a row by Gemma, a spoken 'take it', the r key, or --release-after."""
        self.set_state("HANDOVER"); self.release_now = False
        if not self.at_offer: self.move(self.m_lift + np.array([-0.12, 0.03, 0.06]), 0.06, servo=False, label="offer")   # after an assisted placement the hand is already there
        self.say("I have the can. Please take it.", wait=1.5)
        st0 = self.hand.state(); held = list(st0[2:]) if st0 is not None else None     # finger stall values with the can in hand
        t0 = time.time(); last_reminder = t0 - P.hold_reminder + 4.0; yes_run = 0; it = 0; how = None   # first reminder after 4 s of silence, none while the offer sentence plays
        while how is None:
            self.check_abort(); it += 1
            if self.release_now: how = "operator"; break
            self.hand.set([0.9, 0.8] + [0.88 if it % 2 else 0.9] * 4)                     # fresh setpoint each cycle: a stalled BrainCo finger stops driving and ignores a repeated target; the fingers close on only when the can is gone
            time.sleep(0.4); st = self.hand.state()
            if st is not None: self.log.event(ev="hold", stage=self.state, it=it, hand=np.round(st, 2).tolist(), tag="sensor gate")
            if held is not None and st is not None and sum(float(st[2 + i]) - held[i] > 0.15 for i in range(4)) >= 2:
                how = "taken"; self.log.event(ev="taken", stage=self.state, held=held, now=np.round(st, 2).tolist(), tag="sensor gate"); break
            if P.release_after and time.time() - t0 > P.release_after: how = "timer"; break
            fr, path = self.cam3_shot("hold_%02d" % it)
            if fr is not None:
                v, ans, rec = self.gem.yesno(fr, P.hand_q or HUMAN_HAND_Q, "HANDOVER", media=path)
                yes_run = yes_run + 1 if v else 0
                if yes_run >= 2: how = "vision"; break
            if it % 2 == 0 and time.time() - last_reminder > 4.0:         # never record while the robot's own sentence is playing
                clip = os.path.join(self.log.frames, "hold_%02d.wav" % it)
                try:
                    wav = self.mic.record(2.0, clip)
                    heard, ans, rec = self.gem.heard_take_it(wav)
                    if heard and not any(w in ans for w in OWN_WORDS): how = "voice"; break
                except Exception as e: print("record failed:", e)
            if time.time() - last_reminder > P.hold_reminder:
                self.say("I am holding the can. Take it, or say take it."); last_reminder = time.time()
        self.o["release"] = how; self.o["hold_s"] = round(time.time() - t0, 1)
        self.log.event(ev="release", stage=self.state, how=how, hold_s=self.o["hold_s"], iterations=it, tag="sensor gate" if how == "vision" else "scripted skill")
        print("  release: %s after %.1f s" % (how, self.o["hold_s"]), flush=True)
        self.hand.set(THUMB_PRE); self.sleep(1.0); self.hand.open(wait=True)
        self.say("Enjoy." if how in ("vision", "voice", "taken") else "Released.")
        return how

    def assist(self, colour):
        """After two misses: hold the open hand out at the offer pose and ask the guest to place the can; verify by the stall."""
        self.set_state("RECOVER", "assist"); self.hand.set(THUMB_PRE); self.sleep(0.8)
        p = self.tg_last["p"]; offer = np.array([p[0] + P.dx - 0.12, self.pre[1] + 0.03, self.grasp_z + 0.12])   # the verified offer region: high waypoint, 12 cm back, 3 cm left
        if self.arms_on:                                                    # the hand is beside the can: up first
            m = self.hand_meas(); self.move(np.array([m[0], m[1] + 0.05, self.grasp_z + 0.12]), 0.08, servo=False, label="assist-up")
        else:                                                               # the arm is home after a retreat: raise from the shoulder first
            self.arms_enable(); go_home(self.rb, "left", duration=2.0); self.home_p = self.hand_meas()
            self.move(np.array([self.home_p[0] + 0.05, self.pre[1], self.grasp_z + 0.12]), 0.10, servo=False, label="assist-raise")
        self.m_lift = self.move(offer, 0.06, servo=False, label="assist-offer"); self.at_offer = True
        self.say("I missed. Please place the %s can in my hand." % colour, wait=P.assist_wait)
        for q6, dt in STAGES_THUMB[1:]: self.hand.set(q6); self.sleep(dt)
        self.cam3_shot("assist_closed")
        return self.verify()

    def retreat(self):
        """Up first (never straight down into the table), then back over the edge, then home, then the park pose."""
        self.set_state("RECOVER", "retreat")
        try:
            if self.arms_on:
                m = self.hand_meas(); z = getattr(self, "grasp_z", m[2]); pre_y = self.pre[1] if hasattr(self, "pre") else m[1]
                self.move(np.array([m[0], m[1] + 0.05, z + 0.12]), 0.08, servo=False, label="retreat-up")
                self.move(np.array([self.home_p[0] + 0.05, pre_y, z + 0.12]), 0.08, servo=False, label="retreat-back")
                go_home(self.rb, "left", duration=2.5)
        finally:
            self.park()

    def park(self):
        """Between orders: hold the left arm at the park pose with the streamer on (--park zero/home), or release it."""
        if P.park == "release": self.arms_disable(); return
        try:
            self.arms_enable()
            q = PARK_ZERO if P.park == "zero" else list(cfg.arm.home_q.left)
            self.rb.arms.move_to("left", np.array(q, float), 2.5); self.rb.arms.wait_settled("left", tol=0.08, timeout=3.0)
            self.log.event(ev="park", stage=self.state, pose=P.park, q=q, tag="scripted skill") if self.log else None
        except Exception as e:
            print("park failed:", e); self.arms_disable()

    def recover_fast(self):
        """Abort or failure: open the hand, fade the arms out (the stand controller takes the arms back)."""
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
        self.log.event(ev="order", n=n, params={k: getattr(P, k) for k in ("dx", "dz", "pre", "contact", "press", "tol", "pause", "diam", "lane_y", "lane_x", "seconds")}, session=self.session, tag="scripted skill")
        try:
            colour = self.listen()
            if colour is None: self.say("Sorry, I did not catch a colour."); return self.finish("no_colour")
            self.confirm(colour)
            tg = self.locate(colour)
            if tg is None: return self.finish(self.o["result"])
            if P.dry:
                self.say("Dry run. I would pick the %s can, %d centimetres ahead and %d to my left." % (colour, round(tg["p"][0] * 100), round(tg["p"][1] * 100)), wait=4.0)
                return self.finish("dry")
            grasped = self.pick(tg)
            if not grasped:
                self.say("Missed. Let me try once more."); self.hand.open(wait=True); self.retreat()
                tg = self.locate(colour, relook=0)
                grasped = tg is not None and self.pick(tg)
                if not grasped:
                    if tg is not None: self.hand.open(wait=True)
                    grasped = self.assist(colour)
                    if not grasped:
                        self.say("Sorry, I could not hold the can. Let us try another order."); self.hand.open(wait=True); self.retreat(); return self.finish("missed")
                    self.o["assisted"] = True
            if not self.o["assisted"]: self.lift()
            self.check()
            how = self.handover()
            self.retreat()
            return self.finish("assisted" if self.o["assisted"] else "success")
        except OrderAborted:
            self.say("Order cancelled."); self.recover_fast(); return self.finish("aborted")
        except SkillFailed as e:
            print("SKILL FAILED:", e, flush=True); self.say("I could not complete that reach."); self.recover_fast(); return self.finish("skill_failed: %s" % e)
        except Abort: raise
        except Exception as e:
            traceback.print_exc(); self.say("Something went wrong. Resetting."); self.log.event(ev="error", stage=self.state, error=traceback.format_exc()); self.recover_fast(); return self.finish("error: %s" % e)

    def finish(self, result):
        self.o["result"] = result; self.o["stages"].append({"stage": self.state, "ms": int((time.time() - self.stage_t0) * 1000)})
        autonomous = result == "success" and self.o.get("release") in ("vision", "voice", "taken")
        if autonomous: self.counters["autonomous"] += 1
        elif result == "refused": self.counters["honest_negatives"] += 1
        elif result == "assisted": self.counters["assisted"] += 1
        elif result == "success": self.counters["manual_release"] += 1      # grasped alone, released by the r key or --release-after
        else: self.counters["failed"] += 1
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
