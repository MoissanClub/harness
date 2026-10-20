"""Mac-side mock for brain.py --mock: fake g1_fetch modules (robot, camera, detector, kinematics, hand, arm, skills), a mock mic
that plays the office order clips (or macOS `say` clips) and a mock third-person camera (office frames). No hardware, no DDS.
Environment knobs: BRAIN_MOCK_ORDERS=purple,blue,white (default)  BRAIN_MOCK_HAND=grasp,miss,...  (one entry per closure, default grasp)
BRAIN_MOCK_SCENE=two|one|none  BRAIN_MOCK_SLEEP=0.25 (time.sleep scale)  BRAIN_MOCK_SAY=1 (speak through macOS say)
--mock-gemma adds scripted answers so the run needs no server at all."""
import os, sys, time, types, subprocess
import numpy as np, cv2
HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "..", "spikes", "office-mon")
CLIPS = os.path.join(HERE, "runs", "mock_clips")
# scene_two_cans.jpg (640x480): purple standard can 21 cm left / 41 cm ahead, white slim can 5 cm left / 38 cm ahead (office notes)
SCENES = {"two": [("purple", (22, 160, 138, 300), (0.41, 0.21, 0.12), 0.47), ("silver", (240, 150, 328, 330), (0.38, 0.05, 0.12), 0.45)],
          "one": [("silver", (240, 150, 328, 330), (0.38, 0.17, 0.12), 0.45)], "none": []}
SCENE = SCENES[os.environ.get("BRAIN_MOCK_SCENE", "two")]
HAND = os.environ.get("BRAIN_MOCK_HAND", "grasp").split(",")
STATE = {"colour": None, "pending_colours": [], "closures": 0}
ns = types.SimpleNamespace


class Detection:
    def __init__(self, label, conf, box, source="yoloe"):
        self.label, self.conf, self.box, self.source = label, conf, tuple(float(v) for v in box), source
    width = property(lambda s: s.box[2] - s.box[0]); height = property(lambda s: s.box[3] - s.box[1])


class Camera:
    def __init__(self): self.img = cv2.imread(os.path.join(MEDIA, "scene_two_cans.jpg")); assert self.img is not None
    def read(self): return ns(color=self.img.copy(), depth=np.full((480, 640), 450, np.uint16), intrinsics=ns(fx=600.0, fy=600.0))
    def close(self): pass


class Detector:
    def detect(self, img):
        STATE["pending_colours"] = [c for c, _, _, _ in SCENE]
        return [Detection("can", 0.8 - 0.05 * i, box) for i, (_, box, _, _) in enumerate(SCENE)]


class Kin:
    def fk(self, side, q): T = np.eye(4); T[:3, 3] = np.asarray(q, float)[:3]; return T
    def ik(self, side, pos, xdir, q_seed=None, dir_weight=1.0): return ns(q=np.asarray(pos, float), pos_err=0.002)


class Arms:
    HOME = {"left": np.array([0.12, 0.22, 0.02]), "right": np.array([0.12, -0.22, 0.02])}
    def __init__(self): self.cmd = {s: v.copy() for s, v in self.HOME.items()}; self.on = False
    def enable(self): self.on = True; time.sleep(0.5)
    def disable(self): self.on = False; time.sleep(0.3)
    def measured(self, side): return self.cmd[side] + np.array([0.003, -0.002, 0.004])
    def tracking_error(self, side): return 0.010
    def set_target(self, side, q): self.cmd[side] = np.asarray(q, float).copy()
    def close(self): pass


class Hand:
    def __init__(self, side): self.side, self.q, self.result = side, [0.0] * 6, None
    def set(self, q6):
        self.q = list(q6)
        if self.q[2] >= 0.9 and self.q[0] < 0.5:                  # the fingers stage of a grasp: decide the outcome
            r = HAND[min(STATE["closures"], len(HAND) - 1)]; STATE["closures"] += 1
            self.result = [0.15, 0.56, 0.47, 0.52, 0.55, 0.50] if r == "grasp" else [0.90, 0.80, 0.90, 0.90, 0.90, 0.90]
    def open(self, wait=False): self.q = [0.0] * 6; self.result = None
    def state(self): return np.array(self.result if self.result else self.q)
    def closed_fraction(self): return float(np.mean(self.state()[2:]))
    def close(self): pass


class Robot:
    def __init__(self, cfg):
        self.camera, self.detector, self.kin, self.arms = Camera(), Detector(), Kin(), Arms()
        self.hands = {"left": Hand("left"), "right": Hand("right")}; self.frames = ns(floor_height=lambda p: float(p[2]) + 0.75)
        time.sleep(0.5)
    def speak(self, text):
        if os.environ.get("BRAIN_MOCK_SAY"): subprocess.Popen(["say", "-r", "190", text])
    def close(self): self.camera.close()


class SkillFailed(Exception): pass


def build_robot(cfg): return Robot(cfg)
def can_axis_from_box(frame, det, frames, cfg):
    return next((np.array(p) for _, box, p, _ in SCENE if tuple(float(v) for v in box) == det.box), None)
def median_depth(frame, box, frac):
    return next((z for _, b, _, z in SCENE if tuple(float(v) for v in b) == tuple(float(v) for v in box)), None)
def go_home(rb, side, duration=2.0): rb.arms.cmd[side] = Arms.HOME[side].copy(); time.sleep(duration * 0.5)
def cart_move(rb, side, goal, xdir, palm, speed=0.05, tol=0.04):
    d = float(np.linalg.norm(np.asarray(goal) - rb.arms.cmd[side])); rb.arms.cmd[side] = np.asarray(goal, float).copy(); time.sleep(min(1.0, d / max(speed, 0.01) * 0.3))
def solve_pose(rb, side, pos, xdir, palm, q_seed=None, dir_weight=1.0): return np.asarray(pos, float), ns(pos_err=0.001)
def set_arm_action_service(on): return 0
def load_config(path):
    return ns(fridge=ns(can_diameter_m=0.0), arm=ns(ik_max_pos_err=0.035, ik_dir_weight=1.0), cameras=ns(head=ns(enabled=True)), network_interface="enP8p1s0")


class Mic:
    """Scripted orders: office clips for purple and white, macOS `say` for the rest; short recordings are the guest saying 'take it'."""
    device = "mock"
    def __init__(self, orders=None):
        self.orders = list(orders or os.environ.get("BRAIN_MOCK_ORDERS", "purple,blue,white").split(",")); self.done = False; self.i = 0
    def clip(self, colour):
        office = {"purple": "voice_order.wav", "white": "voice_order_lang2.wav"}
        if colour in office: return os.path.join(MEDIA, office[colour])
        os.makedirs(CLIPS, exist_ok=True); wav = os.path.join(CLIPS, colour.replace(" ", "_") + ".wav")
        if not os.path.exists(wav):
            aiff = wav[:-4] + ".aiff"; text = colour if " " in colour else "the %s can please" % colour
            subprocess.run(["say", "-o", aiff, text], check=True); subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
        return wav
    def record(self, seconds, path):
        if seconds <= 2.5: src = self.clip("take it")
        else:
            if self.i >= len(self.orders): self.done = True
            STATE["colour"] = self.orders[min(self.i, len(self.orders) - 1)]; self.i += 1; src = self.clip(STATE["colour"])
        data = open(src, "rb").read(); open(path, "wb").write(data); time.sleep(min(seconds, 1.0)); return data


class Cam3:
    node = "mock"
    def __init__(self): self.img = cv2.imread(os.path.join(MEDIA, "trial_021646_lifted.jpg"))
    def shot(self): return None if self.img is None else self.img.copy()
    def close(self): pass


def install(P):
    """Register the fake g1_fetch modules, scale time.sleep, return the mock mic and camera."""
    mods = {"g1_fetch": {}, "g1_fetch.config": {"load_config": load_config}, "g1_fetch.robot": {"build_robot": build_robot},
            "g1_fetch.perception": {}, "g1_fetch.perception.localize": {"can_axis_from_box": can_axis_from_box, "median_depth": median_depth},
            "g1_fetch.perception.detector": {"Detection": Detection},
            "g1_fetch.skills": {}, "g1_fetch.skills.common": {"go_home": go_home, "cart_move": cart_move, "solve_pose": solve_pose, "SkillFailed": SkillFailed},
            "g1_fetch.control": {}, "g1_fetch.control.robot_state": {"set_arm_action_service": set_arm_action_service}}
    for name, attrs in mods.items():
        m = types.ModuleType(name); m.__dict__.update(attrs); m.__path__ = []; sys.modules[name] = m
    scale = float(os.environ.get("BRAIN_MOCK_SLEEP", "0.25")); real_sleep = time.sleep
    time.sleep = lambda s: real_sleep(s * scale)
    return {"mic": Mic(), "cam3": Cam3()}


def mock_gemma(GemmaClass):
    """Scripted answers in place of the server: colour of the current order from audio, scene colours per crop, yes to every gate."""
    def chat(base_url, payload):
        msgs = payload["messages"]; user = msgs[-1]["content"] if msgs[-1]["role"] == "user" else msgs[-2]["content"]
        parts = user if isinstance(user, list) else [{"type": "text", "text": user}]
        text = " ".join(p.get("text", "") for p in parts if p.get("type") == "text"); audio = any(p.get("type") == "input_audio" for p in parts)
        if audio: ans = "yes" if "let go" in text else (STATE["colour"] or "none")
        elif "colour of this can" in text: ans = STATE["pending_colours"].pop(0) if STATE["pending_colours"] else "unknown"
        elif "yes or no" in text: ans = "yes"
        elif "Detect" in text: ans = "100, 100, 300, 200]"
        else: ans = "ready"
        time.sleep(0.05)
        return {"content": ans, "timings": {"prompt_n": 100, "prompt_ms": 200.0, "predicted_n": 2, "predicted_ms": 50.0, "cache_n": 80}, "total_s": 0.3}
    class MockGemma(GemmaClass):
        def __init__(self, base_url="mock", on_record=None, **kw): GemmaClass.__init__(self, base_url, on_record, chat=chat)
    return MockGemma
