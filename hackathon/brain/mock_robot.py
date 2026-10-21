"""Mac-side mock for brain.py --mock: fake g1_fetch modules (robot, camera, detector, kinematics, hand, arm, skills), a mock mic that
plays the office order clips (or macOS `say` clips) and a mock third-person camera. No hardware, no DDS.
v2: the head camera renders a synthetic RGB-D frame from the scene (table plane, can cylinders, the hand as a box at its TRUE position =
the model's palm plus a configuration-dependent error, the forearm as a cylinder), the arm uses the real URDF chain (geom.fk) with a
numeric IK, the measured joints sag below the command, and the hand's closure outcome follows the true palm-to-can geometry (grasp,
thumb-0.9 when the can is forward of the palm, pinky-0.9 when the hand is low, all-0.9 when it was pushed). So the servo loop, the
stall-pattern corrections and the reach search are exercised for real; only the model and the sensors are fake.
Environment knobs: BRAIN_MOCK_ORDERS=purple,blue,white (default; spoken clips, any text goes through macOS `say`)
BRAIN_MOCK_SCENE=two|one|none|centre  BRAIN_MOCK_ERR=0.096 (true palm ahead of the model's, m)  BRAIN_MOCK_ERRK=0.03 (its change per rad of elbow)
BRAIN_MOCK_SLEEP=0.25 (time.sleep scale)  BRAIN_MOCK_SAY=1 (speak through macOS say)  BRAIN_MOCK_HAND=auto|grasp,miss,... (force closure outcomes)
--mock-gemma adds scripted answers so the run needs no server at all."""
import os, sys, time, types, subprocess, math
import numpy as np, cv2
import geom
HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "..", "spikes", "office-mon")
CLIPS = os.path.join(HERE, "runs", "mock_clips")
ns = types.SimpleNamespace
TABLE_Z = 0.075                      # table top above the pelvis origin (cans 12 cm tall stood at mid-height z 0.14 in the office logs)
# scene cans: (description, colour name, axis x, axis y, diameter, height)
SCENES = {"two": [("purple la croix", "purple", 0.41, 0.21, 0.066, 0.122), ("silver chi sparkling", "silver", 0.38, 0.05, 0.055, 0.135)],
          "one": [("silver chi sparkling", "silver", 0.38, 0.17, 0.055, 0.135)], "none": [],
          "centre": [("purple la croix", "purple", 0.40, 0.26, 0.066, 0.122), ("silver chi sparkling", "silver", 0.42, 0.07, 0.055, 0.135)],
          "left": [("purple la croix", "purple", 0.40, 0.17, 0.066, 0.122)], "mid": [("silver chi sparkling", "silver", 0.40, 0.11, 0.055, 0.135)],
          "near": [("silver chi sparkling", "silver", 0.42, 0.06, 0.055, 0.135)],
          "three": [("purple la croix", "purple", 0.40, 0.30, 0.066, 0.122), ("silver chi sparkling", "silver", 0.40, 0.12, 0.055, 0.135), ("black coffee", "black", 0.38, -0.08, 0.055, 0.135)]}
SCENE = [dict(desc=d, colour=c, p=np.array([x, y, TABLE_Z + h / 2]), diam=dm, h=h) for d, c, x, y, dm, h in SCENES[os.environ.get("BRAIN_MOCK_SCENE", "two")]]
ERR0, ERRK = float(os.environ.get("BRAIN_MOCK_ERR", "0.096")), float(os.environ.get("BRAIN_MOCK_ERRK", "0.03"))
HAND_SCRIPT = [s for s in os.environ.get("BRAIN_MOCK_HAND", "auto").split(",") if s]
STATE = {"order": None, "pending": [], "closures": 0, "person": False}
SAG = np.array([0.015, -0.005, 0.0, 0.01, 0.0])        # measured = cmd + SAG (gravity): the hand sits ~1 cm low until corrected


# --- camera model ---------------------------------------------------------------------------------------------------------------
class Intrinsics:
    def __init__(self, fx, fy, ppx, ppy, width, height): self.fx, self.fy, self.ppx, self.ppy, self.width, self.height = fx, fy, ppx, ppy, width, height
    def deproject(self, u, v, z):
        u, v, z = np.asarray(u, float), np.asarray(v, float), np.asarray(z, float)
        return np.stack([(u - self.ppx) / self.fx * z, (v - self.ppy) / self.fy * z, z], axis=-1)
    def project(self, p):
        p = np.asarray(p, float); return np.array([self.fx * p[0] / p[2] + self.ppx, self.fy * p[1] / p[2] + self.ppy])


INTR = Intrinsics(615.0, 615.0, 320.0, 240.0, 640, 480)
CAM_XYZ, CAM_PITCH = np.array([0.05, 0.0, 0.47]), math.radians(47.0)      # D435i 0.47 m above the pelvis, looking 47 deg down (fits the office logs)


class Frames:
    """pelvis <-> optical (x right, y down, z forward) like g1-fetch Frames; pelvis 0.84 m above the floor (office logs: floor 0.98 at z 0.14)."""
    pelvis_height_m = 0.84
    def __init__(self):
        R_body = geom.rot_y(CAM_PITCH)                                 # camera body frame: x along the view, y left, z up
        R_opt_in_body = np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]], float)     # columns = optical axes (x right, y down, z fwd) in the body frame
        self.T = geom.make_T(CAM_XYZ, R=R_body @ R_opt_in_body); self.Ti = np.linalg.inv(self.T)
    def optical_to_pelvis(self, p): return self.T[:3, :3] @ np.asarray(p, float) + self.T[:3, 3]
    def pelvis_to_optical(self, p): return self.Ti[:3, :3] @ np.asarray(p, float) + self.Ti[:3, 3]
    def floor_height(self, p): return float(p[2]) + self.pelvis_height_m
    def pelvis_z_from_floor(self, h): return h - self.pelvis_height_m


FRAMES = Frames()


def render(true_palm, R_hand, fingers_open=True, cans=None, person=False):
    """Depth (float32 m, 0 = invalid) and a flat colour image of the table, the cans and the hand/forearm, from the camera."""
    H, W = INTR.height, INTR.width
    uu, vv = np.meshgrid(np.arange(W), np.arange(H)); d = INTR.deproject(uu, vv, np.ones((H, W)))      # ray directions (optical)
    Rwo, o = FRAMES.T[:3, :3], FRAMES.T[:3, 3]; dirs = d.reshape(-1, 3) @ Rwo.T                           # pelvis-frame directions
    best = np.full(dirs.shape[0], np.inf); kind = np.zeros(dirs.shape[0], np.int32)
    def hit(t, mask, k):
        nonlocal best, kind
        ok = mask & (t > 0.1) & (t < best); best = np.where(ok, t, best); kind = np.where(ok, k, kind)
    # table plane z = TABLE_Z inside a rectangle, floor at z = -0.84 elsewhere
    for z, k, box in ((TABLE_Z, 1, (0.20, 1.10, -0.55, 0.55)), (-0.84, 2, (-5, 5, -5, 5))):
        t = (z - o[2]) / np.where(np.abs(dirs[:, 2]) < 1e-6, 1e-6, dirs[:, 2]); p = o + dirs * t[:, None]
        hit(t, (p[:, 0] > box[0]) & (p[:, 0] < box[1]) & (p[:, 1] > box[2]) & (p[:, 1] < box[3]), k)
    # cans: vertical cylinders
    for i, c in enumerate(cans if cans is not None else SCENE):
        a, r = c["p"], c["diam"] / 2; z0, z1 = c["p"][2] - c["h"] / 2, c["p"][2] + c["h"] / 2      # a carried can rises with the hand
        dx, dy = dirs[:, 0], dirs[:, 1]; ox, oy = o[0] - a[0], o[1] - a[1]
        A = dx * dx + dy * dy; B = 2 * (ox * dx + oy * dy); C = ox * ox + oy * oy - r * r; disc = B * B - 4 * A * C
        t = (-B - np.sqrt(np.maximum(disc, 0))) / (2 * A); pz = o[2] + dirs[:, 2] * t
        hit(t, (disc > 0) & (pz > z0) & (pz < z1), 10 + i)
        tt = (z1 - o[2]) / np.where(np.abs(dirs[:, 2]) < 1e-6, 1e-6, dirs[:, 2]); p = o + dirs * tt[:, None]          # the lid
        hit(tt, (p[:, 0] - a[0]) ** 2 + (p[:, 1] - a[1]) ** 2 < r * r, 10 + i)
    # hand: an oriented box around the true palm (x along the forearm: -4..+4 cm palm, +8 cm fingers; y 4 cm; z 9 cm), forearm cylinder behind it
    if true_palm is not None:
        Rl = R_hand.T; lo = np.array([-0.045, -0.02, -0.045]); hi = np.array([0.125 if fingers_open else 0.06, 0.02, 0.045])
        ol = Rl @ (o - true_palm); dl = dirs @ Rl.T
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = (lo - ol) / dl; t2 = (hi - ol) / dl; tmin = np.max(np.minimum(t1, t2), axis=1); tmax = np.min(np.maximum(t1, t2), axis=1)
        hit(tmin, (tmax > tmin) & (tmax > 0), 30)
        wrist = true_palm - R_hand[:, 0] * 0.15; elbow = wrist - R_hand[:, 0] * 0.10 + np.array([0, 0.0, 0.03])   # rough forearm line
        ax = elbow - wrist; L = np.linalg.norm(ax); ax = ax / L
        w = o - wrist; dperp = dirs - np.outer(dirs @ ax, ax); wperp = w - (w @ ax) * ax
        A = np.sum(dperp * dperp, axis=1); B = 2 * np.sum(dperp * wperp, axis=1); C = wperp @ wperp - 0.03 ** 2; disc = B * B - 4 * A * C
        t = (-B - np.sqrt(np.maximum(disc, 0))) / (2 * np.where(A < 1e-9, 1e-9, A)); s = (w + dirs * t[:, None]) @ ax
        hit(t, (disc > 0) & (s > 0) & (s < L), 31)
    if person:                                   # a hand-sized box 10 cm beyond the robot's hand (the guest reaching for the can)
        c = (true_palm if true_palm is not None else np.array([0.3, 0.2, 0.2])) + np.array([0.12, -0.05, 0.02])
        t = np.linalg.norm(c - o); p = o + dirs * t; hit(np.full(dirs.shape[0], t), np.linalg.norm(p - c, axis=1) < 0.06, 40)
    depth = np.where(np.isfinite(best), best * (dirs @ Rwo[:, 2]), 0.0).reshape(H, W).astype(np.float32)   # z along the optical axis
    kind = kind.reshape(H, W)
    colour = np.full((H, W, 3), (60, 60, 60), np.uint8); colour[kind == 1] = (190, 215, 235); colour[kind == 2] = (40, 40, 40)
    cols = {"purple": (160, 60, 120), "silver": (210, 210, 210), "black": (30, 30, 30), "red": (40, 40, 200), "green": (60, 160, 60), "blue": (200, 90, 40)}
    for i, c in enumerate(cans if cans is not None else SCENE): colour[kind == 10 + i] = cols.get(c["colour"], (120, 120, 120))
    colour[kind == 30] = (35, 35, 35); colour[kind == 31] = (90, 90, 90); colour[kind == 40] = (120, 150, 200)
    noise = (np.random.default_rng(int(time.time() * 1000) % 100000).normal(0, 0.002, depth.shape)).astype(np.float32)
    depth = np.where(depth > 0, depth + noise, 0).astype(np.float32)
    return colour, depth, kind


class Detection:
    def __init__(self, label, conf, box, source="yoloe"):
        self.label, self.conf, self.box, self.source = label, conf, tuple(float(v) for v in box), source
    width = property(lambda s: s.box[2] - s.box[0]); height = property(lambda s: s.box[3] - s.box[1])
    center = property(lambda s: ((s.box[0] + s.box[2]) / 2, (s.box[1] + s.box[3]) / 2))


class Camera:
    """Head camera: renders the current scene (needs the arm for the hand position)."""
    def __init__(self): self.arms = None; self.last_kind = None; self.intrinsics = INTR
    def read(self):
        tp, R = (self.arms.true_palm(), self.arms.true_R()) if self.arms is not None and self.arms.on else (None, np.eye(3))
        colour, depth, kind = render(tp, R, fingers_open=self.arms.hand_open if self.arms else True, person=STATE["person"])
        self.last_kind = kind
        return ns(color=colour, depth=depth, intrinsics=INTR, t=time.time())
    def close(self): pass


class Detector:
    def __init__(self, camera): self.camera = camera
    def detect(self, img):
        kind = self.camera.last_kind; dets = []
        if kind is None: return dets
        for i, c in enumerate(SCENE):
            ys, xs = np.nonzero(kind == 10 + i)
            if len(xs) < 40: continue
            dets.append(Detection("can", 0.9 - 0.05 * i, (xs.min(), ys.min(), xs.max(), ys.max())))
        return dets


# --- arm model --------------------------------------------------------------------------------------------------------------------
class IKResult:
    def __init__(self, q, pos_err, dir_err, ok): self.q, self.pos_err, self.dir_err, self.ok = q, pos_err, dir_err, ok


class Kin:
    """Numeric IK on the URDF chain (damped least squares over the 4 proximal joints; position + forearm direction with dir_weight)."""
    lower, upper = geom.Q_LOWER, geom.Q_UPPER
    def fk(self, side, q): return geom.fk(np.asarray(q, float))
    def wrist_frame_rotation(self, side, q5): q = np.asarray(q5, float).copy(); q[4] = 0.0; return geom.fk_chain(q)[4][:3, :3]
    def ik(self, side, p_target, x_dir=None, q_seed=None, q_other=None, dir_weight=1.0):
        q = np.array(q_seed if q_seed is not None else [0.0, 0.25, 0.0, 1.0, 0.0], float); p_target = np.asarray(p_target, float)
        xd = None if x_dir is None else np.asarray(x_dir, float) / np.linalg.norm(x_dir)
        def resid(q):
            T = geom.fk(q); r = [(T[:3, 3] - p_target) * 40.0]      # position dominates the forearm direction, as on the robot (pos_err 1-7 mm logged)
            if xd is not None: r.append((T[:3, 0] - xd) * dir_weight * 1.0)
            return np.concatenate(r)
        for it in range(60):
            r = resid(q); J = np.zeros((r.size, 4))
            for j in range(4):
                dq = np.zeros(5); dq[j] = 1e-4; J[:, j] = (resid(q + dq) - r) / 1e-4
            step = np.linalg.solve(J.T @ J + 1e-3 * np.eye(4), -J.T @ r)
            q[:4] = np.clip(q[:4] + np.clip(step, -0.3, 0.3), self.lower[:4], self.upper[:4])
            if np.linalg.norm(step) < 1e-5: break
        T = geom.fk(q); pos_err = float(np.linalg.norm(T[:3, 3] - p_target))
        dir_err = 0.0 if xd is None else float(math.acos(max(-1.0, min(1.0, float(T[:3, 0] @ xd)))))
        return IKResult(q, pos_err, dir_err, pos_err < 0.02)
    def wrist_roll_for_palm(self, side, q5, palm_dir_world, roll_inward=0.0):
        inward = np.array([0.0, -1.0, 0.0]); R0 = self.wrist_frame_rotation(side, q5)
        d = np.asarray(palm_dir_world, float); d = d / (np.linalg.norm(d) + 1e-9); dl = R0.T @ d
        best, bv = 0.0, -2.0
        for th in np.linspace(self.lower[4], self.upper[4], 121):
            v = float(dl @ (geom.rot_x(th - roll_inward) @ inward))
            if v > bv: best, bv = th, v
        return best


class Arms:
    """Streamer mock: cmd per side, measured = cmd + sag, true palm = model palm + a configuration-dependent forward/vertical error."""
    def __init__(self, kin):
        self.kin = kin; self.cmd = {"left": np.array([0.0, 0.25, 0.0, 1.0, 0.0]), "right": np.array([0.0, -0.25, 0.0, 1.0, 0.0])}
        self.on = False; self.hand_open = True; self.stalled = False     # stalled: the last command was clipped at a can (contact)
        self.held = None                                                # (can dict, offset from the true palm) while the hand holds it
    def hold_nearest(self):
        tp = self.true_palm(); c = min(SCENE, key=lambda c: np.linalg.norm(c["p"] - tp), default=None)
        if c is not None and np.linalg.norm(c["p"] - tp) < 0.12: self.held = (c, c["p"] - tp); print("  [mock] holding %s" % c["desc"], flush=True)
    def carry(self):
        if self.held is not None: c, off = self.held; c["p"] = self.true_palm() + off
    def enable(self): self.on = True; time.sleep(0.5)
    def disable(self): self.on = False; time.sleep(0.3)
    def measured(self, side): return self.cmd[side] + (SAG if side == "left" else 0.0)
    def true_R(self): return geom.fk(self.measured("left"))[:3, :3]
    def true_palm(self):
        """The REAL palm centre: the model's palm (at the measured joints) plus the unmodelled offset along the hand's x (ERR0 at elbow
        1.0 rad, changing ERRK per rad) and 1 cm up; this is what the camera sees and what the can meets."""
        q = self.measured("left"); T = geom.fk(q)
        err = ERR0 + ERRK * (float(q[3]) - 1.0)
        return T[:3, 3] + T[:3, :3] @ np.array([err, 0.0, 0.01])
    def tracking_error(self, side):
        e = float(np.max(np.abs(self.measured(side) - self.cmd[side])))
        return e + (0.05 if (self.stalled or self.blocked()) else 0.0)       # pushing against a can shows as a tracking-error rise
    def blocked(self):
        """True when the commanded hand would penetrate a can: the hand stalls at the surface (contact)."""
        if not self.on or self.held is not None: return False
        tp = self.true_palm(); R = self.true_R()
        for c in SCENE:
            rel = c["p"] - tp; along = float(rel @ R[:, 0]); lat = rel - along * R[:, 0]; lat[2] = 0.0
            if -0.05 < along < 0.13 and abs(rel[2]) < 0.07 and np.linalg.norm(lat) < c["diam"] / 2 + 0.02 and self.hand_open: return True
        return False
    def set_target(self, side, q):
        q = np.asarray(q, float).copy()
        if side == "left" and self.on:
            old = self.cmd[side].copy(); self.cmd[side] = q; self.stalled = False
            if self.held is not None: self.carry(); return
            if self.blocked():                                    # stay at the surface: the command is clipped back (stall)
                self.cmd[side] = old; self.stalled = True; self.push_can(q)
        else: self.cmd[side] = q
    def push_can(self, q_wanted):
        """If the fingers (not the palm) meet the can, the can slides away by the attempted motion: the push the brief describes."""
        tp = self.true_palm(); R = self.true_R()
        for c in SCENE:
            rel = c["p"] - tp; along = float(rel @ R[:, 0])
            if along > 0.045:                                     # the can is at the fingers, not the palm
                want = geom.fk(q_wanted + SAG)[:3, 3] - geom.fk(self.cmd["left"] + SAG)[:3, 3]
                c["p"] = c["p"] + want * 1.5; print("  [mock] the fingers pushed the can by %s" % np.round(want * 1.5, 3).tolist(), flush=True)
    def move_to(self, side, q, duration, abort=None): self.cmd[side] = np.asarray(q, float).copy(); self.carry(); time.sleep(duration * 0.3)
    def wait_settled(self, side, tol=0.05, timeout=3.0): return True
    def measured_tau(self, side): return np.zeros(5)
    def close(self): pass


class Hand:
    """BrainCo mock: the closure outcome follows the true palm-to-can geometry (or a forced script)."""
    def __init__(self, side, arms=None): self.side, self.arms, self.q, self.result = side, arms, [0.0] * 6, None
    def outcome(self):
        if HAND_SCRIPT and HAND_SCRIPT[0] != "auto":
            r = HAND_SCRIPT[min(STATE["closures"], len(HAND_SCRIPT) - 1)]
            return {"grasp": [0.15, 0.56, 0.47, 0.52, 0.55, 0.50], "miss": [0.9, 0.8, 0.9, 0.9, 0.9, 0.9], "thumb": [0.9, 0.8, 0.5, 0.52, 0.5, 0.55],
                    "pinky": [0.15, 0.6, 0.5, 0.52, 0.5, 0.9]}[r]
        tp = self.arms.true_palm(); R = self.arms.true_R(); best = None
        for c in SCENE:
            rel = c["p"] - tp; along = float(rel @ R[:, 0]); lat = float(rel @ R[:, 1]); up = float(rel[2])
            if abs(lat) < c["diam"] / 2 + 0.04 and abs(up) < 0.08 and -0.06 < along < 0.14: best = (along, up, lat, c)
        if best is None: return [0.9, 0.8, 0.9, 0.9, 0.9, 0.9]
        along, up, lat, c = best
        print("  [mock] closing: can %+.3f ahead of the true palm, %+.3f above, %+.3f beside" % (along, up, lat), flush=True)
        if along > 0.025: return [0.9, 0.8, 0.48, 0.5, 0.5, 0.55]          # can forward of the palm: thumb closes past it
        if up > 0.025: return [0.15, 0.6, 0.5, 0.52, 0.5, 0.9]             # hand low: pinky under the can
        if along < -0.035 or up < -0.04: return [0.9, 0.8, 0.9, 0.9, 0.9, 0.9]   # can behind the palm, or the hand above the can
        return [0.15, 0.56, 0.47, 0.52, 0.55, 0.50]
    def set(self, q6):
        q = list(q6)
        if q[2] >= 0.85 and self.q[2] < 0.85 and q[0] < 0.5:              # the fingers stage of a grasp decides the outcome
            self.result = self.outcome(); STATE["closures"] += 1
            if self.arms is not None:
                self.arms.hand_open = False
                if self.result[0] < 0.3 and sum(0.25 < v < 0.7 for v in self.result[2:]) >= 3: self.arms.hold_nearest()   # the hold signature: the can travels with the hand
        elif q[2] < 0.5:
            self.result = None
            if self.arms is not None:
                self.arms.hand_open = True
                if self.arms.held is not None:                              # released: the guest has it, the can leaves the scene
                    c = self.arms.held[0]; self.arms.held = None
                    if c in SCENE: SCENE.remove(c); print("  [mock] the guest took %s" % c["desc"], flush=True)
        elif self.result is not None and STATE.get("taken"):                # the guest pulled the can: fresh setpoints close further
            self.result = [self.result[0], self.result[1]] + [min(0.9, v + 0.2) for v in self.result[2:]]
        self.q = q
    def open(self, wait=False): self.set([0.0] * 6)
    def state(self): return np.array(self.result if self.result else self.q)
    def closed_fraction(self): return float(np.mean(self.state()[2:]))
    def close(self): pass


class Robot:
    def __init__(self, cfg):
        self.kin = Kin(); self.arms = Arms(self.kin); self.camera = Camera(); self.camera.arms = self.arms; self.detector = Detector(self.camera)
        self.hands = {"left": Hand("left", self.arms), "right": Hand("right")}; self.frames = FRAMES; self.cfg = cfg
        time.sleep(0.5)
    def speak(self, text):
        if os.environ.get("BRAIN_MOCK_SAY"): subprocess.Popen(["say", "-r", "190", text])
    def check_abort(self): pass
    def close(self): self.camera.close()


class SkillFailed(Exception): pass


def build_robot(cfg): return Robot(cfg)
def median_depth(frame, box, frac=0.5):
    x1, y1, x2, y2 = [int(v) for v in box]; w, h = x2 - x1, y2 - y1
    sub = frame.depth[int(y1 + h * frac / 2):int(y2 - h * frac / 2) + 1, int(x1 + w * frac / 2):int(x2 - w * frac / 2) + 1]
    v = sub[sub > 0]; return float(np.median(v)) if v.size else None
def box_to_point(frame, det, frames, shrink=0.5):
    z = median_depth(frame, det.box, shrink)
    if z is None: return None
    u, v = det.center; return frames.optical_to_pelvis(frame.intrinsics.deproject(u, v, z))
def can_axis_from_box(frame, det, frames, cfg):
    p = box_to_point(frame, det, frames, 0.5)
    if p is None: return None
    p = p.copy(); p[0] += float(cfg.fridge.can_diameter_m) / 2; return p
def box_cloud(frame, box, frames, step=4, shrink=0.0, max_points=2500):
    x1, y1, x2, y2 = [int(v) for v in box]; uu, vv = np.meshgrid(np.arange(x1, x2 + 1, step), np.arange(y1, y2 + 1, step)); uu, vv = uu.ravel(), vv.ravel()
    uu = np.clip(uu, 0, frame.depth.shape[1] - 1); vv = np.clip(vv, 0, frame.depth.shape[0] - 1); z = frame.depth[vv, uu]; ok = z > 0
    return geom.optical_to_pelvis_many(frames, frame.intrinsics.deproject(uu[ok], vv[ok], z[ok])) if ok.any() else np.zeros((0, 3))
fit_plane_ransac = geom.fit_plane_ransac
def go_home(rb, side, duration=2.0): rb.arms.cmd[side] = np.array([0.0, 0.25, 0.0, 1.0, 0.0]); time.sleep(duration * 0.3)
def solve_pose(rb, side, pos, xdir, palm=None, q_seed=None, dir_weight=None):
    seed = rb.arms.cmd[side] if q_seed is None else q_seed
    res = rb.kin.ik(side, pos, xdir, q_seed=seed, dir_weight=0.5 if dir_weight is None else dir_weight); q = res.q.copy()
    q[4] = rb.kin.wrist_roll_for_palm(side, q, palm, 0.0) if palm is not None else seed[4]
    return q, res
def cart_move(rb, side, goal, xdir, palm=None, speed=0.05, tol=0.04, dir_weight=None, settle=True):
    goal = np.asarray(goal, float); start = rb.kin.fk(side, rb.arms.cmd[side])[:3, 3]; d = float(np.linalg.norm(goal - start))
    q_goal, res = solve_pose(rb, side, goal, xdir, palm, q_seed=rb.arms.cmd[side], dir_weight=dir_weight)
    if res.pos_err > tol: raise SkillFailed("%s hand cannot reach %s (err %.3f m)" % (side, np.round(goal, 3), res.pos_err))
    n = max(1, int(d / 0.01)); q_prev = rb.arms.cmd[side].copy()
    for i in range(1, n + 1):
        q, r = solve_pose(rb, side, start + (goal - start) * i / n, xdir, palm, q_seed=q_prev, dir_weight=dir_weight); rb.arms.set_target(side, q); q_prev = q
    time.sleep(min(1.0, d / max(speed, 0.01) * 0.3)); return float(res.pos_err)
def set_arm_action_service(on): return 0
def load_config(path):
    return ns(fridge=ns(can_diameter_m=0.0), arm=ns(ik_max_pos_err=0.035, ik_dir_weight=0.5, home_q=ns(left=[0.0, 0.25, 0.0, 1.0, 0.0])),
              cameras=ns(head=ns(enabled=True)), robot=ns(palm_inward_wrist_roll=ns(left=0.0), ee_offset_x=0.15), network_interface="enP8p1s0",
              hand=ns(grasp=[0.9, 0.7, 0.9, 0.9, 0.9, 0.9], get=lambda k, d=None: d))


class Mic:
    """Scripted orders: office clips for purple and white, macOS `say` for anything else; short recordings are the guest saying 'take it'."""
    device = "mock"
    def __init__(self, orders=None):
        self.orders = list(orders or os.environ.get("BRAIN_MOCK_ORDERS", "purple,blue,white").split(",")); self.done = False; self.i = 0
    def clip(self, text):
        office = {"purple": "voice_order.wav", "white": "voice_order_lang2.wav"}
        if text in office: return os.path.join(MEDIA, office[text])
        os.makedirs(CLIPS, exist_ok=True); wav = os.path.join(CLIPS, "".join(ch if ch.isalnum() else "_" for ch in text)[:40] + ".wav")
        if not os.path.exists(wav):
            aiff = wav[:-4] + ".aiff"; spoken = text if " " in text else "the %s can please" % text
            try:
                subprocess.run(["say", "-o", aiff, spoken], check=True); subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
            except (FileNotFoundError, subprocess.CalledProcessError):            # no macOS `say` (PC2): the office clip stands in; --mock-gemma answers from the scripted order anyway
                return os.path.join(MEDIA, office["purple"])
        return wav
    def record(self, seconds, path):
        if seconds <= 2.5: src = self.clip("take it"); STATE["taken"] = True
        else:
            if self.i >= len(self.orders): self.done = True
            STATE["order"] = self.orders[min(self.i, len(self.orders) - 1)]; self.i += 1; src = self.clip(STATE["order"]); STATE["taken"] = False
        data = open(src, "rb").read(); open(path, "wb").write(data); time.sleep(min(seconds, 1.0)); return data


class Cam3:
    node = "mock"
    def __init__(self): self.img = cv2.imread(os.path.join(MEDIA, "trial_021646_lifted.jpg"))
    def shot(self): return None if self.img is None else self.img.copy()
    def close(self): pass


def install(P):
    """Register the fake g1_fetch modules, scale time.sleep, return the mock mic and camera."""
    mods = {"g1_fetch": {}, "g1_fetch.config": {"load_config": load_config}, "g1_fetch.robot": {"build_robot": build_robot},
            "g1_fetch.perception": {}, "g1_fetch.perception.localize": {"can_axis_from_box": can_axis_from_box, "median_depth": median_depth, "box_to_point": box_to_point, "box_cloud": box_cloud, "fit_plane_ransac": fit_plane_ransac},
            "g1_fetch.perception.detector": {"Detection": Detection},
            "g1_fetch.skills": {}, "g1_fetch.skills.common": {"go_home": go_home, "cart_move": cart_move, "solve_pose": solve_pose, "SkillFailed": SkillFailed},
            "g1_fetch.control": {}, "g1_fetch.control.robot_state": {"set_arm_action_service": set_arm_action_service}}
    for name, attrs in mods.items():
        m = types.ModuleType(name); m.__dict__.update(attrs); m.__path__ = []; sys.modules[name] = m
    scale = float(os.environ.get("BRAIN_MOCK_SLEEP", "0.25")); real_sleep = time.sleep
    time.sleep = lambda s: real_sleep(s * scale)
    return {"mic": Mic(), "cam3": Cam3()}


def mock_gemma(GemmaClass):
    """Scripted answers in place of the server: descriptions from the scene, the order matched against them, yes to every gate."""
    def chat(base_url, payload):
        msgs = payload["messages"]; system = msgs[0]["content"] if msgs[0]["role"] == "system" else ""
        user = msgs[-1]["content"] if msgs[-1]["role"] == "user" else msgs[-2]["content"]
        parts = user if isinstance(user, list) else [{"type": "text", "text": user}]
        text = " ".join(p.get("text", "") for p in parts if p.get("type") == "text"); audio = any(p.get("type") == "input_audio" for p in parts)
        if audio and "numbered" in system:
            order = (STATE["order"] or "").lower(); ans = "none"
            for i, c in enumerate(SCENE):
                if order and (order in c["desc"] or order in c["colour"] or any(w in c["desc"] for w in order.split())): ans = str(i + 1); break
        elif audio: ans = "yes" if "let go" in text else ("I got it, thank you." if "Transcribe" in text else (STATE["order"] or "none"))
        elif "Identify this drink can" in text or "Describe this can" in text: ans = STATE["pending"].pop(0) if STATE["pending"] else "unknown can"
        elif "colour of this can" in text: ans = STATE["pending"].pop(0) if STATE["pending"] else "unknown"
        elif "human hand" in text: ans = "yes" if STATE["person"] else "no"
        elif "yes or no" in text: ans = "yes"
        elif "Detect" in text: ans = "100, 100, 300, 200]"
        else: ans = "ready"
        time.sleep(0.05)
        return {"content": ans, "timings": {"prompt_n": 100, "prompt_ms": 200.0, "predicted_n": 2, "predicted_ms": 50.0, "cache_n": 80}, "total_s": 0.3}
    class MockGemma(GemmaClass):
        def __init__(self, base_url="mock", on_record=None, **kw): GemmaClass.__init__(self, base_url, on_record, chat=chat)
    return MockGemma


def pending_descriptions(dets, frame):
    """Called by the detector hook in --mock-gemma: queue the descriptions of the detected cans left to right."""
    STATE["pending"] = [c["desc"] for c in sorted(SCENE, key=lambda c: -c["p"][1])][:len(dets)]
