"""Mac-side mock for brain.py --mock: fake g1_fetch modules (robot, camera, detector, kinematics, hand, arm, skills), a mock mic that
plays the office order clips (or macOS `say` clips) and a mock third-person camera. No hardware, no DDS.
v2: the head camera renders a synthetic RGB-D frame from the scene (table plane, can cylinders, the hand as a box at its TRUE position =
the model's palm plus a configuration-dependent error, the forearm as a cylinder), the arm uses the real URDF chain (geom.fk) with a
numeric IK, the measured joints sag below the command, and the hand's closure outcome follows the true palm-to-can geometry (grasp,
thumb-0.9 when the can is forward of the palm, pinky-0.9 when the hand is low, all-0.9 when it was pushed). So the servo loop, the
stall-pattern corrections and the reach search are exercised for real; only the model and the sensors are fake.
Environment knobs: BRAIN_MOCK_ORDERS=purple,blue,white (default; spoken clips, any text goes through macOS `say`)
BRAIN_MOCK_SCENE=two|one|none|centre|left|mid|near|three  BRAIN_MOCK_ERR=0.096 (true palm along the hand's x from the wrist minus g1-fetch's 0.15,
m: 0.096 = v2's model)  BRAIN_MOCK_ERRK=0.03 (its change per rad of elbow)  BRAIN_MOCK_ERRZ=0.01 (true palm above the model's, hand frame)
BRAIN_MOCK_SAG=1 (scale of the gravity sag; 0 = none)  BRAIN_MOCK_OBSTACLE=1 (a box at chest height 15-25 cm ahead; after:TEXT = once the robot says TEXT)
BRAIN_MOCK_CONTACT=0.006 (the open hand meets a can this far beyond its radius: 0.02 = 1 cm before the closure pose)
BRAIN_MOCK_SLEEP=0.25 (time.sleep scale)  BRAIN_MOCK_SAY=1 (speak through macOS say)  BRAIN_MOCK_HAND=auto|grasp,miss,... (force closure outcomes)
BRAIN_MOCK_ERRY=0 (true palm along the hand's y: an error along the palm normal)  BRAIN_MOCK_GEMMA_OFF=0 (Gemma's hand box shifted this far ahead)
BRAIN_MOCK_TABLE_BIAS=0 (the depth camera sees the table this much LOWER than it is; the hand still meets the real table: the hand's
bottom, palm z - 0.045, cannot go below the table top, the measured joints stay at the last command that did not penetrate)
BRAIN_MOCK_TABLE_EDGE=0.34 (the table's near edge, pelvis x)  BRAIN_MOCK_TABLE_Z=0.075 (its top)  BRAIN_MOCK_START_Q=q0,..,q4 (the arm's pose at start, e.g. where a
release left it)  BRAIN_MOCK_GEMMA_BOX=none (Gemma returns no hand box)  BRAIN_MOCK_NEAR_HAND=1 (a hand-sized box 10 cm in front of the
chest; after:TEXT = once the robot says TEXT)  BRAIN_MOCK_OBSBOX=x0,x1,y0,y1,z0,z1 (the obstacle box)  BRAIN_MOCK_CAMFAIL=after:TEXT (the head
camera raises on every read from then on)  BRAIN_MOCK_SAYKEYS="SAY prefix:k+k,..." (the operator types keys into the running brain, any version, after a sentence; `enter`
= an empty line; a STOP kind `keys:q+q` types at a streamed target)  BRAIN_MOCK_TIMEKEYS="seconds:k+k,...": typed on a clock  BRAIN_MOCK_DEPTH=zero (every depth pixel invalid)  BRAIN_MOCK_MIN_RANGE=0.28 (depth nearer than this is invalid, as on the D435i)
BRAIN_MOCK_STOP="SAY text;kind;when[,...]": after the robot says a sentence starting with SAY text, raise `kind` at a streamed target,
before it is sent (abort = the a key, quit = the q key, fail = a g1-fetch exception, sigint = Ctrl-C), `when` = the n-th target, or
z>Z, z<Z, x<X, x>X on the commanded real palm. The same faults reach any brain version (check.py shows each gate case fails on c39a468).
At exit the mock prints `[mock] stats {...}`: targets streamed, the largest joint change in one target, the lowest commanded palm
over the table, the push into the table, arm releases away from home, and after each injected stop the hand's reach below the table
top + 3 cm and how far the palm went out from where it stopped (check.py reads it).
--mock-gemma adds scripted answers so the run needs no server at all."""
import atexit, gc, json, os, signal, sys, threading, time, types, subprocess, math
import numpy as np, cv2
import geom
HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "..", "spikes", "office-mon")
CLIPS = os.path.join(HERE, "runs", "mock_clips")
ns = types.SimpleNamespace
TABLE_Z = float(os.environ.get("BRAIN_MOCK_TABLE_Z", "0.075"))   # table top above the pelvis origin (cans 12 cm tall stood at mid-height z 0.14 in the office logs)
TABLE_X = (float(os.environ.get("BRAIN_MOCK_TABLE_EDGE", "0.34")), 1.10)   # the table's near and far edge (pelvis x): the run plan needs the near edge beyond ~0.33
# scene cans: (description, colour name, axis x, axis y, diameter, height)
SCENES = {"two": [("purple la croix", "purple", 0.41, 0.21, 0.066, 0.122), ("silver chi sparkling", "silver", 0.38, 0.05, 0.055, 0.135)],
          "one": [("silver chi sparkling", "silver", 0.38, 0.17, 0.055, 0.135)], "none": [],
          "centre": [("purple la croix", "purple", 0.40, 0.26, 0.066, 0.122), ("silver chi sparkling", "silver", 0.42, 0.07, 0.055, 0.135)],
          "left": [("purple la croix", "purple", 0.40, 0.17, 0.066, 0.122)], "mid": [("silver chi sparkling", "silver", 0.40, 0.11, 0.055, 0.135)],
          "near": [("silver chi sparkling", "silver", 0.42, 0.06, 0.055, 0.135)],
          "three": [("purple la croix", "purple", 0.40, 0.30, 0.066, 0.122), ("silver chi sparkling", "silver", 0.40, 0.12, 0.055, 0.135), ("black coffee", "black", 0.38, -0.08, 0.055, 0.135)],
          "slot12": [("purple la croix", "purple", 0.38, 0.12, 0.066, 0.122)], "slot09": [("purple la croix", "purple", 0.38, 0.09, 0.066, 0.122)],
          "slot06": [("purple la croix", "purple", 0.38, 0.06, 0.066, 0.122)], "slot17": [("purple la croix", "purple", 0.38, 0.17, 0.066, 0.122)]}   # the run plan's kill-test slots
SCENE = [dict(desc=d, colour=c, p=np.array([x, y, TABLE_Z + h / 2]), diam=dm, h=h) for d, c, x, y, dm, h in SCENES[os.environ.get("BRAIN_MOCK_SCENE", "two")]]
ERR0, ERRK, ERRZ = float(os.environ.get("BRAIN_MOCK_ERR", "0.096")), float(os.environ.get("BRAIN_MOCK_ERRK", "0.03")), float(os.environ.get("BRAIN_MOCK_ERRZ", "0.01"))
ERRY, GEMMA_OFF = float(os.environ.get("BRAIN_MOCK_ERRY", "0")), float(os.environ.get("BRAIN_MOCK_GEMMA_OFF", "0"))
TABLE_BIAS = float(os.environ.get("BRAIN_MOCK_TABLE_BIAS", "0")); DEPTH_MODE = os.environ.get("BRAIN_MOCK_DEPTH", ""); MIN_RANGE = float(os.environ.get("BRAIN_MOCK_MIN_RANGE", "0"))
HAND_HALF_H = 0.045                  # the true hand's half height (thumb up): its bottom meets the table top
HOME_Q = np.array([0.0, 0.25, 0.0, 1.0, 0.0])
START_Q = np.array([float(v) for v in os.environ["BRAIN_MOCK_START_Q"].split(",")]) if os.environ.get("BRAIN_MOCK_START_Q") else HOME_Q.copy()   # e.g. the pose a release left
GEMMA_BOX = os.environ.get("BRAIN_MOCK_GEMMA_BOX", "")             # "none": Gemma answers with no box (server down, timeout)
NEAR_HAND_SPEC = os.environ.get("BRAIN_MOCK_NEAR_HAND", "")            # "1" or "after:TEXT": a hand-sized box 10 cm in front of the chest at belly height
CAMFAIL = os.environ.get("BRAIN_MOCK_CAMFAIL", "")                     # "after:TEXT": the head camera raises on every read once the robot says TEXT
OBSBOX = [float(v) for v in os.environ["BRAIN_MOCK_OBSBOX"].split(",")] if os.environ.get("BRAIN_MOCK_OBSBOX") else [0.15, 0.25, -0.08, 0.08, 0.20, 0.40]   # x0,x1,y0,y1,z0,z1
SAYKEYS = [tuple(s.split(":", 1)) for s in os.environ.get("BRAIN_MOCK_SAYKEYS", "").split(",") if ":" in s]   # "SAY prefix:key+key": the operator types
TIMEKEYS = [(float(t), k) for t, k in (s.split(":", 1) for s in os.environ.get("BRAIN_MOCK_TIMEKEYS", "").split(",") if ":" in s)]   # "seconds:key+key" after start
HAND_BOX = ((-0.045, 0.125), (-0.02, 0.02), (-0.045, 0.045))          # the true open hand about the true palm, hand frame (x fingers, y thickness, z thumb)


def hand_corners(tp, R):
    return [tp + R @ np.array([x, y, z]) for x in HAND_BOX[0] for y in HAND_BOX[1] for z in HAND_BOX[2]]


def hand_in_table(tp, R):
    """True when the open hand box reaches into the table: the box is convex, so its lowest point beyond the table's near edge is a
    corner beyond the edge or a point where one of its 12 edges crosses x = edge (V2_REVIEW round 4: the corners alone missed the
    bottom-back edge cutting the table at the kill slots)."""
    C = hand_corners(tp, R); e = TABLE_X[0]; pts = [c for c in C if c[0] >= e]
    for i in range(8):
        for b in (1, 2, 4):
            j = i ^ b
            if j > i and (C[i][0] - e) * (C[j][0] - e) < 0: pts.append(C[i] + (C[j] - C[i]) * ((e - C[i][0]) / (C[j][0] - C[i][0])))
    return any(p[2] < TABLE_Z and abs(p[1]) < 0.55 and p[0] < TABLE_X[1] for p in pts)


def find_brain():
    """The running brain (any version) for the scripted operator's keys: the object whose class is Brain."""
    for o in gc.get_objects():
        try:
            if type(o).__name__ == "Brain" and hasattr(o, "key"): return o
        except Exception: pass
    return None


def note_key(k):
    """A key the operator typed: a y opens the way home (targets streamed after a stop and before the next y are counted per stop)."""
    if k == "y":
        for rec in STATS["stops"]: rec["y_seen"] = True
    STATS.setdefault("keys", []).append([k, STATS["targets"]])


def type_keys(keys, why):
    b = find_brain()
    for k in keys:
        print("  [mock operator] types %r (%s)" % (k, why), flush=True); note_key(k)
        if b is not None: b.key("" if k == "enter" else k)
OBSTACLE_SPEC = os.environ.get("BRAIN_MOCK_OBSTACLE", "")          # "1": always; "after:Missed.": from the moment the robot says that
CONTACT = float(os.environ.get("BRAIN_MOCK_CONTACT", "0.006"))   # contact starts this far beyond r from the can axis (0.006: 4 mm past the closure pose)
HAND_SCRIPT = [s for s in os.environ.get("BRAIN_MOCK_HAND", "auto").split(",") if s]
STATE = {"order": None, "pending": [], "closures": 0, "person": False}
STATS = {"targets": 0, "max_dq": 0.0, "max_dq_joint": None, "max_dq_palm": None, "max_dq_after": "", "min_cmd_z": None, "table_contacts": 0, "push": 0.0, "raise_tip_under_table_x": -1.0, "raise_cmd_hand_under_table_x": -1.0,
         "disable_away": [], "disables": 0, "stops": [], "raise_low_reach": -1.0, "says": 0}
STOPS = []
for _spec in [s for s in os.environ.get("BRAIN_MOCK_STOP", "").split(",") if s.strip()]:
    _say, _kind, _when = [v.strip() for v in _spec.split(";")]
    STOPS.append({"say": _say, "kind": _kind, "when": _when, "armed": False, "n": 0, "fired": False})
_LAST_SAY = [""]


def _segments(q):
    s = geom.arm_segments(np.asarray(q, float)); return s


def _low_reach(q, below=None):
    """The furthest-ahead x of the wrist, palm and fingertips while below the table top + 3 cm (-1 if none): the keep-out measure."""
    below = TABLE_Z + 0.03 if below is None else below; s = _segments(q); worst = -1.0
    for k in ("wrist", "palm", "tip"):
        if s[k][2] < below: worst = max(worst, float(s[k][0]))
    return worst


def on_say(text):
    STATS["says"] += 1; _LAST_SAY[0] = text
    for rec in STATS["stops"]:
        if text.startswith("The way out") or text.startswith("The way home"): rec["way_out_said"] = True
    for say, keys in SAYKEYS:
        if text.startswith(say): type_keys(keys.split("+"), "after '%s'" % say)
    if OBSTACLE_SPEC.startswith("after:") and text.startswith(OBSTACLE_SPEC[6:]) and not STATE.get("obstacle"):
        STATE["obstacle"] = True; print("  [mock] a box appears at chest height 15-25 cm ahead", flush=True)
    if CAMFAIL.startswith("after:") and text.startswith(CAMFAIL[6:]) and not STATE.get("camfail"):
        STATE["camfail"] = True; print("  [mock] the head camera stops answering", flush=True)
    if NEAR_HAND_SPEC.startswith("after:") and text.startswith(NEAR_HAND_SPEC[6:]) and not STATE.get("near_hand"):
        STATE["near_hand"] = True; print("  [mock] a hand appears 10 cm in front of the chest", flush=True)
    for st in STOPS:
        if not st["fired"] and not st["armed"] and text.startswith(st["say"]): st["armed"] = True; st["n"] = 0


def stop_due(q):
    """The injected stop due at this target (before it is sent), or None."""
    palm = _segments(q)["palm"]
    for st in STOPS:
        if not st["armed"] or st["fired"]: continue
        st["n"] += 1; w = st["when"]
        due = ((w.startswith("z>") and palm[2] > float(w[2:])) or (w.startswith("z<") and palm[2] < float(w[2:])) or (w.startswith("x<") and palm[0] < float(w[2:]))
               or (w.startswith("x>") and palm[0] > float(w[2:])) or (w.isdigit() and st["n"] >= int(w)))
        if due:
            st["fired"] = True; return st
    return None


def fire(st, q_now):
    s = _segments(q_now)
    rec = {"kind": st["kind"], "say": st["say"], "when": st["when"], "palm": np.round(s["palm"], 3).tolist(), "target": STATS["targets"], "after_targets": 0, "after_low_reach": -1.0, "out_x": 0.0, "out_y": 0.0, "up_z": 0.0}
    # out_x / out_y: how far the palm went ahead / outward of where it stopped while still at that height (a retry that walks the arm
    # out over the table); the retraced descent home leaves the height first and does not count
    rec["moved_before_way_out"] = 0; rec["way_out_said"] = False; rec["moved_before_y"] = 0; rec["y_seen"] = False
    STATS["stops"].append(rec); print("  [mock] injected stop: %s after '%s' (%s) with the palm at %s" % (st["kind"], st["say"], st["when"], rec["palm"]), flush=True)
    main = sys.modules.get("__main__")
    if st["kind"].startswith("keys:"): type_keys(st["kind"][5:].split("+"), "at a streamed target"); return
    if st["kind"] in ("abort", "quit") and find_brain() is not None:       # the a / q key itself, into any brain with a key reader
        type_keys(["a" if st["kind"] == "abort" else "q"], "at a streamed target"); return
    if st["kind"] in ("abort", "quit"): raise (getattr(main, "Stopped", None) or getattr(main, "OrderAborted" if st["kind"] == "abort" else "Abort"))()   # a brain without a key reader
    if st["kind"] == "sigint": note_key("ctrl-c"); os.kill(os.getpid(), signal.SIGINT); time.sleep(0.05); return
    raise SkillFailed("injected g1-fetch failure at a streamed target")


def track(q_prev, q):
    """Per-target statistics of the streamed command (the left arm, enabled)."""
    q = np.asarray(q, float); dq = np.abs(q - np.asarray(q_prev, float)); m = float(dq.max()); STATS["targets"] += 1; s = _segments(q)
    if m > STATS["max_dq"]: STATS.update(max_dq=round(m, 4), max_dq_joint=int(dq.argmax()), max_dq_palm=np.round(s["palm"], 3).tolist(), max_dq_after=_LAST_SAY[0])
    if s["palm"][0] > TABLE_X[0] and (STATS["min_cmd_z"] is None or s["palm"][2] < STATS["min_cmd_z"]): STATS["min_cmd_z"] = round(float(s["palm"][2]), 4)
    if _LAST_SAY[0].startswith("Raising."):
        STATS["raise_low_reach"] = max(STATS["raise_low_reach"], round(_low_reach(q), 4))
        rb = STATE.get("robot")
        if rb is not None:                                # any corner of the TRUE open hand under the table top during the raise (the keep-out's reason)
            tp, R = rb.arms.true_palm_at(q)
            for c in hand_corners(tp, R):
                if c[2] < TABLE_Z: STATS["raise_tip_under_table_x"] = max(STATS["raise_tip_under_table_x"], round(float(c[0]), 4))
            Tc = geom.fk_chain_side(np.asarray(q, float)); pc, Rc = Tc[5][:3, 3], Tc[4][:3, :3]      # where the command puts the hand (no sag): the keep-out's own measure
            for c in hand_corners(pc, Rc):
                if c[2] < TABLE_Z: STATS["raise_cmd_hand_under_table_x"] = max(STATS["raise_cmd_hand_under_table_x"], round(float(c[0]), 4))
    for rec in STATS["stops"]:
        rec["after_targets"] += 1; rec["after_low_reach"] = max(rec["after_low_reach"], round(_low_reach(q), 4))
        if not rec.get("way_out_said", True): rec["moved_before_way_out"] = rec.get("moved_before_way_out", 0) + 1
        if not rec.get("y_seen", True): rec["moved_before_y"] = rec.get("moved_before_y", 0) + 1
        p0 = np.array(rec["palm"]); rec["up_z"] = max(rec["up_z"], round(float(s["palm"][2] - p0[2]), 4))
        if s["palm"][2] >= p0[2] - 0.02: rec["out_x"] = max(rec["out_x"], round(float(s["palm"][0] - p0[0]), 4)); rec["out_y"] = max(rec["out_y"], round(float(s["palm"][1] - p0[1]), 4))


@atexit.register
def _print_stats():
    rb = STATE.get("robot")
    if rb is not None:                                   # where the arm ended: the last command's real palm and its distance from home
        p = _segments(rb.arms.cmd["left"])["palm"]; STATS["end_palm"] = np.round(p, 3).tolist(); STATS["end_home_dist"] = round(float(np.linalg.norm(p - _segments(HOME_Q)["palm"])), 4)
    print("[mock] stats " + json.dumps(STATS, default=str), flush=True)
# Gravity sag of the left arm: point masses on the URDF chain (upper arm, forearm, hand), joint stiffness k; the measured joints settle at
# cmd - dV/dq / k. Fitted to Tuesday's 25 uncorrected up/high moves (spikes/office-tue-brain, v1, model palm 0.15): predicted |sag| at
# the high waypoints 2.7-4.8 cm vs 2.5-4.6 cm logged, at the raise 1.5-1.7 vs 1.9-2.5 cm, rms 9.5 mm (2026-10-20).
SAG_MASSES, SAG_K, SAG_SCALE = (0.8, 0.5, 0.8), np.array([50.0, 30.0, 40.0, 30.0]), float(os.environ.get("BRAIN_MOCK_SAG", "1"))
_SAG_CACHE = {}


def _potential(q):
    Ts = geom.fk_chain(q, 0.15); up = (Ts[0][:3, 3] + Ts[3][:3, 3]) / 2; fore = (Ts[3][:3, 3] + Ts[4][:3, 3]) / 2
    hand = Ts[4][:3, 3] + Ts[4][:3, :3] @ np.array([0.10, 0.0, 0.0])
    return 9.81 * (SAG_MASSES[0] * up[2] + SAG_MASSES[1] * fore[2] + SAG_MASSES[2] * hand[2])


def sag_dq(q_cmd):
    """Joint deflection under gravity at the commanded pose (fixed point: the torque is evaluated at the sagged pose)."""
    if SAG_SCALE == 0: return np.zeros(5)
    key = tuple(np.round(np.asarray(q_cmd, float), 6))
    if key not in _SAG_CACHE:
        q_cmd = np.asarray(q_cmd, float); q = q_cmd.copy()
        for _ in range(3):
            V0 = _potential(q); dq = np.zeros(5)
            for j in range(4):
                e = np.zeros(5); e[j] = 1e-5; dq[j] = -((_potential(q + e) - V0) / 1e-5) / SAG_K[j] * SAG_SCALE
            q = q_cmd + dq
        if len(_SAG_CACHE) > 20000: _SAG_CACHE.clear()
        _SAG_CACHE[key] = q - q_cmd
    return _SAG_CACHE[key]


# --- camera model ---------------------------------------------------------------------------------------------------------------
class Intrinsics:
    def __init__(self, fx, fy, ppx, ppy, width, height): self.fx, self.fy, self.ppx, self.ppy, self.width, self.height = fx, fy, ppx, ppy, width, height
    def deproject(self, u, v, z):
        u, v, z = np.asarray(u, float), np.asarray(v, float), np.asarray(z, float)
        return np.stack([(u - self.ppx) / self.fx * z, (v - self.ppy) / self.fy * z, z], axis=-1)
    def project(self, p):
        p = np.asarray(p, float); return np.array([self.fx * p[0] / p[2] + self.ppx, self.fy * p[1] / p[2] + self.ppy])


INTR = Intrinsics(615.0, 615.0, 320.0, 240.0, 640, 480)
CAM_XYZ, CAM_PITCH = np.array([0.054, 0.018, 0.474]), 0.8308            # the URDF d435_joint (calib camera_pose): 47.6 deg down (fits the office logs)


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
    for z, k, box in ((TABLE_Z - TABLE_BIAS, 1, (TABLE_X[0], TABLE_X[1], -0.55, 0.55)), (-0.84, 2, (-5, 5, -5, 5))):
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
    if OBSTACLE_SPEC == "1" or STATE.get("obstacle"):   # a box at chest height straight ahead (a guest leaning in): the 0.30 m rule must refuse
        lo, hi = np.array([OBSBOX[0], OBSBOX[2], OBSBOX[4]]), np.array([OBSBOX[1], OBSBOX[3], OBSBOX[5]])
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = (lo - o) / dirs; t2 = (hi - o) / dirs; tmin = np.max(np.minimum(t1, t2), axis=1); tmax = np.min(np.maximum(t1, t2), axis=1)
        hit(tmin, (tmax > tmin) & (tmax > 0), 50)
    if NEAR_HAND_SPEC == "1" or STATE.get("near_hand"):   # a guest's hand 10 cm in front of the chest at belly height: inside the D435i's minimum range
        lo, hi = np.array([0.18, -0.04, 0.24]), np.array([0.24, 0.04, 0.32])
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = (lo - o) / dirs; t2 = (hi - o) / dirs; tmin = np.max(np.minimum(t1, t2), axis=1); tmax = np.min(np.maximum(t1, t2), axis=1)
        hit(tmin, (tmax > tmin) & (tmax > 0), 51)
    if person:                                   # a hand-sized box 10 cm beyond the robot's hand (the guest reaching for the can)
        c = (true_palm if true_palm is not None else np.array([0.3, 0.2, 0.2])) + np.array([0.12, -0.05, 0.02])
        t = np.linalg.norm(c - o); p = o + dirs * t; hit(np.full(dirs.shape[0], t), np.linalg.norm(p - c, axis=1) < 0.06, 40)
    depth = np.where(np.isfinite(best), best * (dirs @ Rwo[:, 2]), 0.0).reshape(H, W).astype(np.float32)   # z along the optical axis
    kind = kind.reshape(H, W)
    colour = np.full((H, W, 3), (60, 60, 60), np.uint8); colour[kind == 1] = (190, 215, 235); colour[kind == 2] = (40, 40, 40)
    cols = {"purple": (160, 60, 120), "silver": (210, 210, 210), "black": (30, 30, 30), "red": (40, 40, 200), "green": (60, 160, 60), "blue": (200, 90, 40)}
    for i, c in enumerate(cans if cans is not None else SCENE): colour[kind == 10 + i] = cols.get(c["colour"], (120, 120, 120))
    colour[kind == 30] = (35, 35, 35); colour[kind == 31] = (90, 90, 90); colour[kind == 40] = (120, 150, 200); colour[kind == 50] = (60, 90, 160)
    noise = (np.random.default_rng(int(time.time() * 1000) % 100000).normal(0, 0.002, depth.shape)).astype(np.float32)
    depth = np.where(depth > 0, depth + noise, 0).astype(np.float32)
    if DEPTH_MODE == "zero": depth = np.zeros_like(depth)
    if MIN_RANGE > 0: depth = np.where(depth < MIN_RANGE, 0.0, depth).astype(np.float32)
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
        if STATE.get("camfail"): raise RuntimeError("mock: the head camera does not answer")
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
            # the axis-aligned box of the mask: an off-centre upright can looks slanted from the tilted head camera, so the box is wider
            # than the can (95 px for 75 px rows at y 0.11), as on the robot (Tuesday: the 58 mm Chi measured 70 mm and classed 66)
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
        self.kin = kin; self.cmd = {"left": START_Q.copy(), "right": np.array([0.0, -0.25, 0.0, 1.0, 0.0])}
        self.on = False; self.hand_open = True; self.contact_q = None    # contact_q: while the hand presses a can, the measured joints stay at this command
        self.held = None                                                # (can dict, offset from the true palm) while the hand holds it
    def hold_nearest(self):
        tp = self.true_palm(); c = min(SCENE, key=lambda c: np.linalg.norm(c["p"] - tp), default=None)
        if c is not None and np.linalg.norm(c["p"] - tp) < 0.12: self.held = (c, c["p"] - tp); print("  [mock] holding %s" % c["desc"], flush=True)
    def carry(self):
        if self.held is not None: c, off = self.held; c["p"] = self.true_palm() + off
    def enable(self):
        """g1-fetch ArmStreamer.enable: target = cmd = the measured joints, then the weight ramps to 1 (the arm then sags once more)."""
        if not self.on: self.cmd["left"] = self.measured("left").copy(); self.contact_q = None
        self.on = True; print("  [mock] arm streamer enabled", flush=True); time.sleep(0.5)
    def disable(self):
        """g1-fetch ramps the arm_sdk weight to 0: the controller takes the arm back in joint space from wherever it is."""
        STATS["disables"] += 1; palm = _segments(self.cmd["left"])["palm"]; home = _segments(HOME_Q)["palm"]
        if self.on and float(np.linalg.norm(palm - home)) > 0.03:
            STATS["disable_away"].append(np.round(palm, 3).tolist()); print("  [mock] ARM RELEASED AWAY FROM HOME, palm %s" % np.round(palm, 3).tolist(), flush=True)
        self.on = False; time.sleep(0.3)
    def measured(self, side):
        base = self.contact_q if (side == "left" and self.contact_q is not None) else self.cmd[side]
        return base + (sag_dq(base) if side == "left" else 0.0)
    def true_R(self): return geom.fk(self.measured("left"))[:3, :3]
    def true_palm_at(self, q_cmd):
        """The REAL palm if the arm settled at the command q_cmd (the sagged joints)."""
        q = np.asarray(q_cmd, float) + sag_dq(q_cmd); T = geom.fk(q); err = ERR0 + ERRK * (float(q[3]) - 1.0)
        return T[:3, 3] + T[:3, :3] @ np.array([err, ERRY, ERRZ]), T[:3, :3]
    def true_palm(self):
        """The REAL palm centre: the model's palm (at the measured joints) plus the unmodelled offset along the hand's x (ERR0 at elbow
        1.0 rad, changing ERRK per rad) and 1 cm up; this is what the camera sees and what the can meets."""
        q = self.measured("left"); T = geom.fk(q)
        err = ERR0 + ERRK * (float(q[3]) - 1.0)
        return T[:3, 3] + T[:3, :3] @ np.array([err, ERRY, ERRZ])
    def tracking_error(self, side):
        return float(np.max(np.abs(self.measured(side) - self.cmd[side])))   # the sag, plus the command running ahead of a hand held at a can
    def table_block(self, q_cmd):
        """True when the open hand, settled at q_cmd, would put any corner (palm box and fingertips, from its pitch and roll) below the
        REAL table top over the table."""
        tp, R = self.true_palm_at(q_cmd); return hand_in_table(tp, R)
    def would_block(self, q_cmd):
        """True when the open hand, settled at q_cmd, would penetrate a can (the geometry of blocked())."""
        if not self.on or self.held is not None or not self.hand_open: return False
        tp, R = self.true_palm_at(q_cmd)
        for c in SCENE:
            rel = c["p"] - tp; along = float(rel @ R[:, 0]); lat = rel - along * R[:, 0]; lat[2] = 0.0
            if -0.05 < along < 0.13 and abs(rel[2]) < 0.07 and np.linalg.norm(lat) < c["diam"] / 2 + CONTACT: return True
        return False
    def blocked(self):
        """True when the commanded hand would penetrate a can: the open hand stalls at the surface (contact). The palm face is ~1 cm from
        the palm centre, so contact starts 4 mm PAST the closure pose (palm centre r + 1 cm from the axis); the fingers (up to 13 cm
        ahead of the palm centre) touch the can when it stands at the fingertips."""
        if not self.on or self.held is not None: return False
        tp = self.true_palm(); R = self.true_R()
        for c in SCENE:
            rel = c["p"] - tp; along = float(rel @ R[:, 0]); lat = rel - along * R[:, 0]; lat[2] = 0.0
            if -0.05 < along < 0.13 and abs(rel[2]) < 0.07 and np.linalg.norm(lat) < c["diam"] / 2 + CONTACT and self.hand_open: return True
        return False
    def set_target(self, side, q):
        """The streamer accepts every command; a hand pressing a can stays at the contact (the measured joints stop at the last command
        that did not penetrate) while the command runs ahead: the tracking error and the lag grow, as on the robot."""
        q = np.asarray(q, float).copy()
        if side != "left" or not self.on: self.cmd[side] = q; return
        st = stop_due(q)
        if st is not None: fire(st, self.cmd[side])
        track(self.cmd[side], q)
        prev = self.cmd[side].copy() if self.contact_q is None else self.contact_q; self.cmd[side] = q
        if self.table_block(q):                                           # the hand rests on the table: the command runs ahead of it
            if self.contact_q is None: self.contact_q = prev
            STATS["table_contacts"] += 1                                   # push: how far the settled command sits below the hand resting on the table
            STATS["push"] = max(STATS["push"], round(float(geom.fk(self.contact_q + sag_dq(self.contact_q))[2, 3] - geom.fk(q + sag_dq(q))[2, 3]), 4))
            if self.held is not None: self.carry()
            return
        if self.held is not None: self.contact_q = None; self.carry(); return
        if self.would_block(q):
            self.push_can(q, prev)
            if self.would_block(q): self.contact_q = prev
            else: self.contact_q = None
        else: self.contact_q = None
    def push_can(self, q_wanted, q_from):
        """If the fingers (not the palm) meet the can, the can slides away by the attempted motion: the push the brief describes."""
        tp, R = self.true_palm_at(q_from); tw, Rw = self.true_palm_at(q_wanted)
        for c in SCENE:
            rel = c["p"] - tp; along = float(rel @ R[:, 0]); relw = c["p"] - tw; alw = float(relw @ Rw[:, 0]); latw = relw - alw * Rw[:, 0]; latw[2] = 0.0
            touching = -0.05 < alw < 0.13 and abs(relw[2]) < 0.07 and np.linalg.norm(latw) < c["diam"] / 2 + CONTACT   # only the can the hand meets (2026-10-21: every can ahead moved)
            if touching and along > 0.045:                        # the can is at the fingers, not the palm
                want = self.true_palm_at(q_wanted)[0] - tp; want[2] = 0.0
                c["p"] = c["p"] + want * 1.5; print("  [mock] the fingers pushed the can by %s" % np.round(want * 1.5, 3).tolist(), flush=True)
    def move_to(self, side, q, duration, abort=None): self.cmd[side] = np.asarray(q, float).copy(); self.contact_q = None; self.carry(); time.sleep(duration * 0.3)
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
        print("  [mock] closing: can %+.3f ahead of the true palm, %+.3f above, %+.3f beside (closure pose at %.3f)" % (along, up, lat, c["diam"] / 2 + 0.01), flush=True)
        if abs(lat) > c["diam"] / 2 + 0.02: return [0.59, 0.77, 0.9, 0.9, 0.9, 0.9]     # palm more than 1 cm short of the closure pose: closes on nothing
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
        STATE["robot"] = self; time.sleep(0.5)
        for t, keys in TIMEKEYS:                                         # the operator types on a clock (a thread, like the brain's key reader)
            th = threading.Timer(t, type_keys, args=(keys.split("+"), "at %.0f s" % t)); th.daemon = True; th.start()
    def speak(self, text):
        on_say(text)
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
    def chat(base_url, payload, **kw):
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
        elif "Detect" in text:                                                # Gemma's box of the robot's hand: around the TRUE hand (+-6 cm), 0-1000 grid
            rb = STATE.get("robot"); ans = "100, 100, 300, 200]"
            if GEMMA_BOX == "none": ans = "I cannot see a hand."
            elif rb is not None and rb.arms.on:
                tp = rb.arms.true_palm() + np.array([GEMMA_OFF, 0.0, 0.0]); R = rb.arms.true_R()    # the image box of the true open hand's 8 corners
                corners = [tp + R @ np.array([x, y, z]) for x in (-0.045, 0.125) for y in (-0.02, 0.02) for z in (-0.045, 0.045)]
                uv = [geom.pelvis_to_pixel(FRAMES, INTR, c) for c in corners]
                if all(uv):
                    xs = [min(639, max(0, u)) for u, v in uv]; ys = [min(479, max(0, v)) for u, v in uv]
                    ans = "%d, %d, %d, %d]" % (min(ys) / 480 * 1000, min(xs) / 640 * 1000, max(ys) / 480 * 1000, max(xs) / 640 * 1000)
        else: ans = "ready"
        time.sleep(0.05)
        return {"content": ans, "timings": {"prompt_n": 100, "prompt_ms": 200.0, "predicted_n": 2, "predicted_ms": 50.0, "cache_n": 80}, "total_s": 0.3}
    class MockGemma(GemmaClass):
        def __init__(self, base_url="mock", on_record=None, **kw): GemmaClass.__init__(self, base_url, on_record, chat=chat)
    return MockGemma


def pending_descriptions(dets, frame):
    """Called by the detector hook in --mock-gemma: queue the descriptions of the detected cans left to right."""
    STATE["pending"] = [c["desc"] for c in sorted(SCENE, key=lambda c: -c["p"][1])][:len(dets)]
