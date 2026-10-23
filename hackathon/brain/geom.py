"""Geometry for brain v2 (numpy only): the G1 left-arm chain from the URDF (xr_teleoperate g1_body23.urdf, the file g1-fetch loads),
a torso box with a clearance test for the elbow/forearm/hand, a RANSAC table plane, the hand located in the head camera as a depth
blob above the table, forearm-direction candidates for the free-forearm reach, and the projection of pelvis points into the image.
Pelvis frame: x ahead, y left, z up, metres. The chain is validated against g1-fetch's pinocchio FK (see test_geom.py)."""
import math
import numpy as np

# --- URDF chain, left arm (joint origins xyz / rpy and axes; waist yaw fixed at 0, torso_link at (-0.0039635, 0, 0.054)) -----------
TORSO_XYZ = (-0.0039635, 0.0, 0.054)
CHAIN = (  # (xyz, rpy, axis) of each joint in its parent frame
    ((0.0039563, 0.10022, 0.23778), (0.27931, 5.4949e-05, -0.00019159), (0, 1, 0)),   # shoulder pitch
    ((0.0, 0.038, -0.013831), (-0.27925, 0.0, 0.0), (1, 0, 0)),                        # shoulder roll
    ((0.0, 0.00624, -0.1032), (0.0, 0.0, 0.0), (0, 0, 1)),                             # shoulder yaw
    ((0.015783, 0.0, -0.080518), (0.0, 0.0, 0.0), (0, 1, 0)),                          # elbow
    ((0.100, 0.00188791, -0.010), (0.0, 0.0, 0.0), (1, 0, 0)),                         # wrist roll
)
Q_LOWER = np.array([-3.0892, -1.5882, -2.618, -1.0472, -1.972222054])
Q_UPPER = np.array([2.6704, 2.2515, 2.618, 2.0944, 1.972222054])
EE_OFFSET_X = 0.15       # g1-fetch robot.ee_offset_x: the model's palm centre ahead of the wrist-roll origin (MEASURE in g1-fetch)
# Torso box in the pelvis frame (x ahead, y left, z up) and the clearance the forearm needs around it. From the robot sessions: the
# Oct 19 collision had the forearm along +x at y 0.095 (elbow beside the torso at x ~0, y 0.10); the verified lateral grasps put the
# elbow at y 0.17-0.19 with no contact; the chest front is ~0.13 m ahead of the pelvis origin. Half-width 0.12 plus a 0.04 margin
# separates the two. Override with --torso / --clear on the brain command line and re-measure once on the robot.
TORSO_BOX = np.array([[-0.14, 0.13], [-0.12, 0.12], [0.00, 0.42]])
FOREARM_RADIUS = 0.04    # forearm/hand half-thickness used as the clearance margin


def rot_x(a):
    c, s = math.cos(a), math.sin(a); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)
def rot_y(a):
    c, s = math.cos(a), math.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], float)
def rot_z(a):
    c, s = math.cos(a), math.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)
def rpy_to_R(rpy): return rot_z(rpy[2]) @ rot_y(rpy[1]) @ rot_x(rpy[0])
def make_T(xyz, rpy=(0, 0, 0), R=None):
    T = np.eye(4); T[:3, :3] = rpy_to_R(rpy) if R is None else R; T[:3, 3] = xyz; return T
def rot_axis(axis, a):
    return {(1, 0, 0): rot_x, (0, 1, 0): rot_y, (0, 0, 1): rot_z}[tuple(axis)](a)


def fk_chain(q5, ee_offset_x=EE_OFFSET_X):
    """4x4 transforms (pelvis frame) of the shoulder-pitch, shoulder-roll, shoulder-yaw, elbow and wrist-roll joint origins, then
    the end-effector frame (wrist frame translated by ee_offset_x along its x axis: the model's palm centre)."""
    T = make_T(TORSO_XYZ); out = []
    for (xyz, rpy, axis), a in zip(CHAIN, q5):
        T = T @ make_T(xyz, rpy) @ make_T((0, 0, 0), R=rot_axis(axis, float(a))); out.append(T)
    out.append(T @ make_T((ee_offset_x, 0, 0)))
    return out


def fk(q5, ee_offset_x=EE_OFFSET_X):
    """End-effector 4x4, like g1-fetch ArmKinematics.fk('left', q)."""
    return fk_chain(q5, ee_offset_x)[-1]


def arm_points(q5, ee_offset_x=EE_OFFSET_X):
    """Shoulder (yaw joint origin), elbow, wrist and palm points in the pelvis frame."""
    Ts = fk_chain(q5, ee_offset_x)
    return {"shoulder": Ts[2][:3, 3], "elbow": Ts[3][:3, 3], "wrist": Ts[4][:3, 3], "palm": Ts[5][:3, 3], "R": Ts[5][:3, :3]}


# --- torso clearance ---------------------------------------------------------------------------------------------------------------
def box_distance(p, box):
    """Euclidean distance from a point to an axis-aligned box (0 inside)."""
    d = np.maximum(np.maximum(box[:, 0] - p, p - box[:, 1]), 0.0)
    return float(np.linalg.norm(d))


def segment_box_clearance(a, b, box, n=12):
    """Minimum distance from the segment a-b to the box, sampled."""
    return min(box_distance(a + (b - a) * t, box) for t in np.linspace(0.0, 1.0, n))


def clearance(q5, box=TORSO_BOX, ee_offset_x=EE_OFFSET_X):
    """Smallest clearance (m) between the torso box and the elbow, forearm (elbow-wrist), hand (wrist-palm) and 8 cm past the palm
    (the fingers). The upper arm is left out: the shoulder roll keeps it clear and its root sits in the box's corner."""
    pts = arm_points(q5, ee_offset_x); tip = pts["palm"] + (pts["palm"] - pts["wrist"]) / max(1e-6, np.linalg.norm(pts["palm"] - pts["wrist"])) * 0.08
    return min(segment_box_clearance(pts["elbow"], pts["wrist"], box), segment_box_clearance(pts["wrist"], pts["palm"], box), segment_box_clearance(pts["palm"], tip, box))


# --- reach candidates ---------------------------------------------------------------------------------------------------------------
def grasp_vectors(yaw_deg, pitch_deg=0.0):
    """Forearm direction (hand x) and palm normal for the LEFT hand: yaw rotates +x inward (toward -y) by yaw_deg, pitch tilts it down.
    The palm faces the midline/back of the body: the horizontal direction perpendicular to the forearm on the -y side; the approach
    direction is the palm normal (the hand slides onto the can along it; for yaw 0 that is -y, the verified lateral slide)."""
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    xdir = np.array([math.cos(yaw) * math.cos(pitch), -math.sin(yaw) * math.cos(pitch), -math.sin(pitch)])
    palm = np.array([-math.sin(yaw), -math.cos(yaw), 0.0])
    return xdir, palm


def reach_candidates(yaws=(0, 10, 20, 30, 45), pitches=(0, -10)):
    """Forearm directions in order of preference: the verified +x first, then inward yaw, each level first and then pitched down."""
    return [(y, p) for y in yaws for p in pitches]


# --- table plane -----------------------------------------------------------------------------------------------------------------------
def fit_plane_ransac(points, thresh=0.012, iters=80, rng=None, min_nz=0.0):
    """Plane n.p = d (n unit) by RANSAC on an (N,3) cloud; returns (n, d, inlier_mask) or None. Same contract as g1-fetch's. min_nz > 0
    considers only candidates within acos(min_nz) of level (a can's side near the table would otherwise win on a narrow table strip)."""
    P = np.asarray(points, float)
    if P.shape[0] < 30: return None
    rng = np.random.default_rng(0) if rng is None else rng
    best = None
    for _ in range(iters):
        i = rng.choice(P.shape[0], 3, replace=False); a, b, c = P[i]
        n = np.cross(b - a, c - a); nn = np.linalg.norm(n)
        if nn < 1e-9: continue
        n = n / nn
        if abs(n[2]) < min_nz: continue
        d = float(n @ a); inl = np.abs(P @ n - d) < thresh
        if best is None or inl.sum() > best[2].sum(): best = (n, d, inl)
    if best is None or best[2].sum() < 30: return None
    Q = P[best[2]]; c = Q.mean(axis=0); u, s, vt = np.linalg.svd(Q - c); n = vt[2]
    if n[2] < 0: n = -n                                   # normal up
    return n, float(n @ c), np.abs(P @ n - float(n @ c)) < thresh


def table_plane(cloud, z_hint=None, band=0.012):
    """Table plane from a pelvis-frame cloud of the region around the can's base. Tables are level (owner, 2026-10-23): the table is
    the most common height of the cloud, returned as a LEVEL plane (n = +z, d = z). The free RANSAC fit this replaces leaned 3-16 deg
    through can sides and a narrow table strip on Oct 23, while the IMU read 1 deg and the depth showed the desk level within 1 cm over
    x 0.30-0.90. With z_hint (the can base from the box) only the points within 6 cm of it count: with the cans near the table's edge
    the band under them also sees the floor. A table is a sharp peak in the 5 mm height histogram; vertical surfaces (can sides) spread
    evenly over heights, so a peak under twice the median of the bins away from it (2 bins either side) is not a table (the old fit
    refused can sides as not level). Returns dict(n, d, z, n_in, tilt_deg 0) or None (under 30 points within `band` of the mode, a flat
    histogram, or the mode further than 6 cm from z_hint)."""
    cloud = np.asarray(cloud, float)
    if z_hint is not None and cloud.size: cloud = cloud[np.abs(cloud[:, 2] - z_hint) < 0.06]
    if cloud.ndim != 2 or cloud.shape[0] < 30: return None
    z = cloud[:, 2]; edges = np.arange(z.min(), z.max() + 0.01, 0.005)
    hist, edges = np.histogram(z, bins=edges if edges.size > 1 else 1); i = int(hist.argmax())
    away = np.r_[hist[:max(0, i - 2)], hist[i + 3:]]
    if away.size and hist[i] < 2.0 * float(np.median(away)): return None   # flat: can sides, no table
    inl = np.abs(z - 0.5 * (edges[i] + edges[i + 1])) < band
    if inl.sum() < 30: return None
    z0 = float(np.median(z[inl])); inl = np.abs(z - z0) < band         # the table height where it was seen (near the can)
    if z_hint is not None and abs(z0 - z_hint) > 0.06: return None
    return {"n": np.array([0.0, 0.0, 1.0]), "d": z0, "z": z0, "n_in": int(inl.sum()), "tilt_deg": 0.0}


def height_above(points, plane):
    return np.asarray(points) @ plane["n"] - plane["d"]


# --- camera helpers ---------------------------------------------------------------------------------------------------------------------
def pelvis_to_pixel(frames, intr, p):
    """Pixel (u, v) of a pelvis-frame point, or None if behind the camera."""
    po = np.asarray(frames.pelvis_to_optical(np.asarray(p, float)), float)
    if po[2] <= 0.05: return None
    uv = intr.project(po)
    return float(uv[0]), float(uv[1])


def cloud_in_window(frame, frames, u0, v0, half_w, half_h, step=2):
    """Pelvis-frame points of the valid depth pixels in a window around (u0, v0). Returns (points, uu, vv)."""
    H, W = frame.depth.shape
    x1, x2 = max(0, int(u0 - half_w)), min(W - 1, int(u0 + half_w)); y1, y2 = max(0, int(v0 - half_h)), min(H - 1, int(v0 + half_h))
    if x2 <= x1 or y2 <= y1: return np.zeros((0, 3)), np.zeros(0, int), np.zeros(0, int)
    uu, vv = np.meshgrid(np.arange(x1, x2 + 1, step), np.arange(y1, y2 + 1, step)); uu, vv = uu.ravel(), vv.ravel()
    z = np.asarray(frame.depth[vv, uu], float)
    if z.max(initial=0) > 50: z = z / 1000.0              # uint16 millimetres
    ok = z > 0.05
    if ok.sum() == 0: return np.zeros((0, 3)), uu[:0], vv[:0]
    po = np.asarray(frame.intrinsics.deproject(uu[ok], vv[ok], z[ok]), float)
    if po.ndim == 2 and po.shape[0] == 3 and po.shape[1] != 3: po = po.T
    return optical_to_pelvis_many(frames, po), uu[ok], vv[ok]


def in_boxes(uu, vv, boxes, pad=8):
    m = np.zeros(uu.shape, bool)
    for b in boxes:
        m |= (uu >= b[0] - pad) & (uu <= b[2] + pad) & (vv >= b[1] - pad) & (vv <= b[3] + pad)
    return m


def hand_blob(frame, frames, expect_p, plane, exclude_boxes=(), xdir=(1.0, 0.0, 0.0), ndir=(0.0, -1.0, 0.0), half_w=200, half_h=170, min_h=0.03, max_h=0.30, radius=0.25, hand_len=0.12, step=2, exclude_cyl=(), ahead=0.04, grow=True):
    """The hand blob in a window centred `ahead` of the expected palm along xdir (the open hand spans -4.5..+12.5 cm about the palm
    centre); a blob touching the window edge is searched again once in a window 1.4x larger (radius + 5 cm). See _hand_blob."""
    c = np.asarray(expect_p, float) + np.asarray(xdir, float) * ahead
    b = _hand_blob(frame, frames, c, plane, exclude_boxes, xdir, ndir, half_w, half_h, min_h, max_h, radius, hand_len, step, exclude_cyl)
    if grow and b is not None and (b["win_edge_px"] < 8 or b["radius_cut"]):
        b2 = _hand_blob(frame, frames, c, plane, exclude_boxes, xdir, ndir, int(half_w * 1.4), int(half_h * 1.4), min_h, max_h, radius + 0.05, hand_len, step, exclude_cyl)
        if b2 is not None: b2["grown"] = True; return b2
    return b


def _hand_blob(frame, frames, expect_p, plane, exclude_boxes=(), xdir=(1.0, 0.0, 0.0), ndir=(0.0, -1.0, 0.0), half_w=200, half_h=170, min_h=0.03, max_h=0.30, radius=0.25, hand_len=0.12, step=2, exclude_cyl=()):
    """The robot's hand in the head camera: valid depth pixels in a window around the projected expected palm point, higher than min_h
    above the table plane, outside the can boxes, within `radius` (horizontal) of the expected point: that is the arm blob (hand plus
    forearm). The hand is its front part: the points within hand_len of the front extent along the forearm direction xdir (robust 90th
    percentile). Returns a dict with the hand's 3D median ('p'), its front ('front', the fingertips), extent, pixel bbox and count, or
    None. The median of the visible hand sits beside and ahead of the palm centre by a hand-geometry constant that the brain calibrates
    once (the reference offset). The window and radius hold the whole hand with a forward error up to 6 cm (the 130 x 110 px window cut
    the fingertips: forward errors of 2.4-5.4 cm read 6-9 mm, V2_REVIEW round 2 blocker 5); 'win_edge_px' is the kept points' margin to
    the window and 'radius_cut' says the front reaches the radius: either one means the features are the window's, not the hand's."""
    xdir = np.asarray(xdir, float); expect_p = np.asarray(expect_p, float)
    uv = pelvis_to_pixel(frames, frame.intrinsics, expect_p)
    if uv is None: return None
    pts, uu, vv = cloud_in_window(frame, frames, uv[0], uv[1], half_w, half_h, step)
    if pts.shape[0] == 0: return None
    h = height_above(pts, plane) if plane is not None else pts[:, 2] - (expect_p[2] - 0.10)
    sel = (h > min_h) & (h < max_h) & ~in_boxes(uu, vv, exclude_boxes)
    for cp, cr in exclude_cyl:                                         # the cans' own surface points, by 3D distance to each axis (a 2D box would clip the hand behind the can)
        sel &= np.hypot(pts[:, 0] - cp[0], pts[:, 1] - cp[1]) > cr + 0.012
    sel &= np.hypot(pts[:, 0] - expect_p[0], pts[:, 1] - expect_p[1]) < radius
    if sel.sum() < 25: return None
    P, U, V = pts[sel], uu[sel], vv[sel]
    along = P @ xdir; front = float(np.percentile(along, 90)); keep = along > front - hand_len
    if keep.sum() < 20: return None
    P, U, V = P[keep], U[keep], V[keep]; med = np.median(P, axis=0); near = float(np.percentile(P @ np.asarray(ndir, float), 90))   # the face nearest the can
    H, W = frame.depth.shape; wx1, wx2 = max(0, int(uv[0] - half_w)), min(W - 1, int(uv[0] + half_w)); wy1, wy2 = max(0, int(uv[1] - half_h)), min(H - 1, int(uv[1] + half_h))
    win_edge = int(min(U.min() - wx1, V.min() - wy1, wx2 - U.max(), wy2 - V.max()))
    fr = P[(P @ xdir) > front - 0.02]; radius_cut = bool(fr.shape[0] and float(np.max(np.hypot(fr[:, 0] - expect_p[0], fr[:, 1] - expect_p[1]))) > radius - 0.01)
    return {"p": med, "front": front, "near": near, "n": int(P.shape[0]), "xmin": float(P[:, 0].min()), "xmax": float(P[:, 0].max()), "ymin": float(P[:, 1].min()),
            "ymax": float(P[:, 1].max()), "zmin": float(P[:, 2].min()), "zmax": float(P[:, 2].max()),
            "bbox": [int(U.min()), int(V.min()), int(U.max()), int(V.max())], "uv_expect": [int(uv[0]), int(uv[1])], "win_edge_px": win_edge, "radius_cut": radius_cut}


def obstacle_ahead(frame, frames, x_max=0.30, y_half=0.15, z_lo=0.05, z_hi=0.50, step=6, min_pts=60, min_valid=0.7, own=()):
    """Hard safety, fail-closed: (blocked, why, info). Blocked when the depth image shows at least min_pts points within x_max straight
    ahead at chest height (pelvis frame), or when under min_valid of the depth pixels are valid: a dropped stream, a blinded projector or
    something inside the D435i's minimum range (a box 15-25 cm ahead leaves 12% valid in the mock) is not "clear". The zone at x < 0.30
    covers nearly the whole image (the camera looks 47.6 deg down from z 0.47), so the frame's valid fraction is the zone's. On the robot
    normal frames were 82-97% valid (Oct 19). `own`: (a, b, r) segments of the robot's own arm; points within r of them do not count
    (a cross-body reach puts the forearm inside the zone)."""
    H, W = frame.depth.shape
    valid = float(np.mean(np.asarray(frame.depth)[::step, ::step] > 0))
    pts, uu, vv = cloud_in_window(frame, frames, W / 2, H / 2, W / 2, H / 2, step)
    n, n_own = 0, 0
    if pts.shape[0]:
        sel = (pts[:, 0] > 0.05) & (pts[:, 0] < x_max) & (np.abs(pts[:, 1]) < y_half) & (pts[:, 2] > z_lo) & (pts[:, 2] < z_hi)
        for a, b, r in own:
            a, b = np.asarray(a, float), np.asarray(b, float); ab = b - a; t = np.clip(((pts - a) @ ab) / max(1e-9, float(ab @ ab)), 0.0, 1.0)
            mine = np.linalg.norm(pts - (a + t[:, None] * ab), axis=1) < r; n_own += int((sel & mine).sum()); sel &= ~mine
        n = int(sel.sum())
    info = {"valid": round(valid, 3), "n_zone": n, "n_own_arm": n_own}
    if valid < min_valid: return True, "only %.0f%% of the depth pixels are valid: cannot see ahead" % (valid * 100), info
    if n >= min_pts: return True, "%d points within %.2f m ahead at chest height" % (n, x_max), info
    return False, "", info


def in_view(frames, intr, p, margin=0.15):
    """True when the pelvis point projects inside the image with a relative margin on every side."""
    uv = pelvis_to_pixel(frames, intr, p)
    if uv is None: return False
    W, H = int(intr.width), int(intr.height)
    return margin * W < uv[0] < (1 - margin) * W and margin * H < uv[1] < (1 - margin) * H


_T_CACHE = {}
def frames_T(frames):
    """4x4 optical->pelvis transform recovered from frames.optical_to_pelvis (robust to how Frames stores it), cached per object."""
    key = id(frames)
    if key not in _T_CACHE:
        o = np.asarray(frames.optical_to_pelvis(np.zeros(3)), float); T = np.eye(4); T[:3, 3] = o
        for i in range(3):
            e = np.zeros(3); e[i] = 1.0; T[:3, i] = np.asarray(frames.optical_to_pelvis(e), float) - o
        _T_CACHE[key] = T
    return _T_CACHE[key]


def optical_to_pelvis_many(frames, po):
    T = frames_T(frames); return np.asarray(po, float) @ T[:3, :3].T + T[:3, 3]


# =====================================================================================================================================
# v2 reach model (V2_STRATEGY.md section 3): the REAL palm 0.246 m along the wrist-roll axis, one search variable (forearm yaw psi
# toward the midline), a 4-joint IK with the yaw held hard and the forearm pitch as an outcome, the torso from the URDF meshes.
# =====================================================================================================================================
PALM_REAL = 0.246        # wrist-roll origin -> real palm centre along the roll axis: g1-fetch ee_offset_x 0.15 + the 0.096 jog (Oct 19/21)
CHAIN_RIGHT = (          # the right arm, mirrored in y (URDF g1_body23)
    ((0.0039563, -0.10022, 0.23778), (-0.27931, 5.4949e-05, 0.00019159), (0, 1, 0)),
    ((0.0, -0.038, -0.013831), (0.27925, 0.0, 0.0), (1, 0, 0)),
    ((0.0, -0.00624, -0.1032), (0.0, 0.0, 0.0), (0, 0, 1)),
    ((0.015783, 0.0, -0.080518), (0.0, 0.0, 0.0), (0, 1, 0)),
    ((0.100, -0.00188791, -0.010), (0.0, 0.0, 0.0), (1, 0, 0)),
)
# Torso extents per height band in the pelvis frame, from torso_link.STL / waist_support_link.STL / pelvis.STL placed by the URDF
# joints (computed 2026-10-20 with a stdlib STL reader): (z0, z1, x_min, x_max, y_half).
TORSO_BANDS = ((-0.15, 0.00, -0.049, 0.049, 0.064), (0.00, 0.05, -0.058, 0.059, 0.066), (0.05, 0.10, -0.061, 0.063, 0.088),
               (0.10, 0.16, -0.063, 0.068, 0.098), (0.16, 0.22, -0.069, 0.079, 0.100), (0.22, 0.30, -0.071, 0.080, 0.108),
               (0.30, 0.38, -0.066, 0.063, 0.101), (0.38, 0.50, -0.060, 0.060, 0.090))
LIMIT_MARGIN = math.radians(10.0)
# acceptance thresholds on the segment centre lines (the link radii are inside them); calibrated on the logged poses in replay_reach.py
CLEAR_UPPER, CLEAR_FOREARM, CLEAR_HAND, CLEAR_RIGHT, PITCH_MAX_DEG, IK_TOL, TABLE_CLEAR = 0.03, 0.04, 0.06, 0.05, 15.0, 0.005, -0.01   # defaults = calib.json (brain.py overrides them from the file); table: the pinky edge may touch (trial 8)
HIGH_RISE, FINGERTIP, PALM_HALF_HEIGHT = 0.12, 0.08, 0.045
HAND_BACK, HAND_HALF_THICK = 0.045, 0.02   # the open hand behind the palm centre and half its thickness (assumed, the mock's box; BrainCo palm 7.6 x 4.1 cm)


def hand_lowest(q5, ee=None):
    """(the open hand's lowest point z, palm z) at q5: the corners of the hand box (HAND_BACK behind to FINGERTIP ahead of the palm
    centre along the wrist-roll axis, +-HAND_HALF_THICK, +-PALM_HALF_HEIGHT) through the forearm pitch and the wrist roll."""
    Ts = fk_chain_side(np.asarray(q5, float), "left", PALM_REAL if ee is None else ee); R = Ts[4][:3, :3]; palm = Ts[5][:3, 3]
    low = min(float((palm + R @ np.array([x, y, z]))[2]) for x in (-HAND_BACK, FINGERTIP) for y in (-HAND_HALF_THICK, HAND_HALF_THICK) for z in (-PALM_HALF_HEIGHT, PALM_HALF_HEIGHT))
    return low, float(palm[2])


def fk_chain_side(q5, side="left", ee=PALM_REAL):
    T = make_T(TORSO_XYZ); out = []
    for (xyz, rpy, axis), a in zip(CHAIN if side == "left" else CHAIN_RIGHT, q5):
        T = T @ make_T(xyz, rpy) @ make_T((0, 0, 0), R=rot_axis(axis, float(a))); out.append(T)
    out.append(T @ make_T((ee, 0, 0)))
    return out


def arm_segments(q5, side="left", ee=PALM_REAL):
    """Named points: shoulder (pitch origin), upper (yaw origin = the lower upper arm's top), elbow, wrist, palm, tip (fingers +8 cm)."""
    Ts = fk_chain_side(q5, side, ee); palm = Ts[5][:3, 3]; d = Ts[4][:3, :3][:, 0]
    return {"shoulder": Ts[0][:3, 3], "upper": Ts[2][:3, 3], "elbow": Ts[3][:3, 3], "wrist": Ts[4][:3, 3], "palm": palm, "tip": palm + d * FINGERTIP, "d": d, "R": Ts[4][:3, :3]}


def torso_distance(p):
    """Distance from a point to the torso (union of the band boxes); 0 inside."""
    best = 1.0
    for z0, z1, x0, x1, yh in TORSO_BANDS:
        best = min(best, box_distance(np.asarray(p, float), np.array([[x0, x1], [-yh, yh], [z0, z1]])))
    return best


def segment_torso_clearance(a, b, n=14):
    return min(torso_distance(a + (b - a) * t) for t in np.linspace(0.0, 1.0, n))


def segment_segment_distance(a0, a1, b0, b1, n=10):
    best = 1.0
    for t in np.linspace(0, 1, n):
        p = a0 + (a1 - a0) * t; ab = b1 - b0; s = float(np.clip(((p - b0) @ ab) / max(1e-9, ab @ ab), 0, 1))
        best = min(best, float(np.linalg.norm(p - (b0 + ab * s))))
    return best


def forearm_yaw_pitch(d):
    """Forearm direction -> (psi toward the midline for the left arm, pitch) in degrees."""
    return math.degrees(math.atan2(-d[1], d[0])), math.degrees(math.asin(max(-1.0, min(1.0, -d[2]))))


def ik4(p_palm, psi_deg, q_seed, ee=PALM_REAL, iters=40):
    """4-joint IK (shoulder pitch, roll, yaw, elbow) for the real palm at p_palm with the forearm yaw held at psi (pitch free), or
    position only when psi_deg is None (damped least squares, stays near the seed: for the raise from the park pose, where the
    forearm hangs). Newton on the residuals with a numeric Jacobian, joint limits clipped. Returns (q5 with the seed's roll, pos_err m,
    pitch deg, d)."""
    free = psi_deg is None; psi = 0.0 if free else math.radians(psi_deg); p_palm = np.asarray(p_palm, float); q = np.array(q_seed, float).copy()
    def resid(q):
        Ts = fk_chain_side(q, "left", ee); d = Ts[4][:3, :3][:, 0]
        r = Ts[5][:3, 3] - p_palm
        return r if free else np.concatenate([r, [0.5 * (d[1] * math.cos(psi) + d[0] * math.sin(psi))]])
    for it in range(iters):
        r = resid(q)
        if np.linalg.norm(r[:3]) < 1e-4 and (free or abs(r[3]) < 1e-4): break
        J = np.zeros((r.size, 4))
        for j in range(4):
            dq = np.zeros(5); dq[j] = 1e-5; J[:, j] = (resid(q + dq) - r) / 1e-5
        step = np.linalg.solve(J.T @ J + (1e-3 if free else 1e-6) * np.eye(4), -J.T @ r)
        q[:4] = np.clip(q[:4] + np.clip(step, -0.4, 0.4), Q_LOWER[:4], Q_UPPER[:4])
    Ts = fk_chain_side(q, "left", ee); d = Ts[4][:3, :3][:, 0]
    if not free and d[0] * math.cos(psi) - d[1] * math.sin(psi) < 0: return q, 1.0, 0.0, d     # the forearm points backward: not a solution
    return q, float(np.linalg.norm(Ts[5][:3, 3] - p_palm)), forearm_yaw_pitch(d)[1], d


def wrist_roll_for_palm(q5, palm_dir, roll_inward=0.0, side="left"):
    """g1-fetch's rule: at roll = roll_inward the palm faces the midline (-y for the left hand in the wrist frame); choose the roll
    whose palm normal best aligns with palm_dir (world)."""
    inward = np.array([0.0, -1.0, 0.0]) if side == "left" else np.array([0.0, 1.0, 0.0])
    q = np.array(q5, float); q[4] = 0.0; R0 = fk_chain_side(q, side)[4][:3, :3]
    d = np.asarray(palm_dir, float); d = d / (np.linalg.norm(d) + 1e-9); dl = R0.T @ d
    best, bv = 0.0, -2.0
    for th in np.linspace(Q_LOWER[4], Q_UPPER[4], 241):
        v = float(dl @ (rot_x(th - roll_inward) @ inward))
        if v > bv: best, bv = th, v
    return best


def grasp_frame(psi_deg):
    """Forearm direction d (level) and palm normal n = d x z (palm to the right of the forearm, thumb up): the only family on a table."""
    psi = math.radians(psi_deg); d = np.array([math.cos(psi), -math.sin(psi), 0.0]); n = np.cross(d, np.array([0.0, 0.0, 1.0]))
    return d, n


def pose_checks(q5, table_z=None, right_q=None):
    """Clearances and margins of one left-arm pose: lower upper arm / forearm / hand (wrist..tip) to the torso, hand to the right arm,
    forearm pitch, the smallest joint-limit margin (rad), the palm's lowest point above the table (palm z - 0.045)."""
    s = arm_segments(q5); out = {"upper": segment_torso_clearance(s["upper"], s["elbow"]), "forearm": segment_torso_clearance(s["elbow"], s["wrist"]),
                                 "hand": segment_torso_clearance(s["wrist"], s["tip"]), "pitch": forearm_yaw_pitch(s["d"])[1],
                                 "psi": forearm_yaw_pitch(s["d"])[0], "margin": float(np.min(np.minimum(np.asarray(q5) - Q_LOWER, Q_UPPER - np.asarray(q5)))),
                                 "elbow": s["elbow"], "palm": s["palm"]}
    out["table"] = None if table_z is None else float(s["palm"][2] - PALM_HALF_HEIGHT - table_z)
    if right_q is not None:
        r = arm_segments(right_q, "right", ee=0.15)
        out["right"] = min(segment_segment_distance(s["wrist"], s["tip"], r["elbow"], r["wrist"]), segment_segment_distance(s["wrist"], s["tip"], r["wrist"], r["palm"]),
                           segment_segment_distance(s["elbow"], s["wrist"], r["elbow"], r["palm"]))
    return out


def pose_ok(c, thresholds=None):
    t = thresholds or {}
    return (c["upper"] >= t.get("upper", CLEAR_UPPER) and c["forearm"] >= t.get("forearm", CLEAR_FOREARM) and c["hand"] >= t.get("hand", CLEAR_HAND)
            and abs(c["pitch"]) <= t.get("pitch", PITCH_MAX_DEG) and c["margin"] >= t.get("margin", LIMIT_MARGIN)
            and (c.get("table") is None or c["table"] >= t.get("table", TABLE_CLEAR)) and c.get("right", 1.0) >= t.get("right", CLEAR_RIGHT))


def psi_order(y_can, lo=-30, hi=60, step=5):
    """psi candidates visited outward from psi_pref = clamp(10 + (0.09 - y) * 100, 0, 50) degrees."""
    pref = int(round(max(0.0, min(50.0, 10 + (0.09 - y_can) * 100)) / step) * step)
    cands = list(range(lo, hi + 1, step)); return sorted(cands, key=lambda p: (abs(p - pref), p))


def plan_reach(can, r, table_z=None, q_seed=None, right_q=None, pre=0.03, thresholds=None, psis=None, ee=PALM_REAL, extra_points=()):
    """V2_STRATEGY.md section 3: for each psi (outward from the preferred one) solve the real-palm IK at the grasp P = C - (r + 0.01) n,
    the pre-grasp P - pre n, every 1 cm approach pose and the high waypoints (+0.12 z); accept when every pose passes pose_checks with
    IK error <= IK_TOL; choose the smallest |pitch|, ties to the smaller |psi|. Returns (plan or None, tried list)."""
    can = np.asarray(can, float); q_seed = np.array([0.0, 0.25, 0.0, 1.0, 0.0] if q_seed is None else q_seed, float); tried = []; best = None
    for psi in (psis if psis is not None else psi_order(can[1])):
        d, n = grasp_frame(psi); P = can - n * (r + 0.01); poses = [("grasp", P), ("pre", P - n * pre)]
        k = int(math.ceil(pre / 0.01))
        poses += [("slide%d" % i, P - n * (pre - i * pre / k)) for i in range(1, k)] + [("high", P - n * pre + np.array([0, 0, HIGH_RISE]))] + list(extra_points)
        seed = q_seed.copy(); rec = {"psi": psi, "ok": True, "why": "", "poses": {}}
        for name, p in poses:
            q, err, pitch, dd = ik4(p, psi, seed, ee); seed = q
            transit = name == "high" or name.startswith("way")
            c = pose_checks(q, None if transit else table_z, right_q); c["ik"] = err; c["q"] = q
            rec["poses"][name] = c
            t = dict(thresholds or {}); t.setdefault("pitch", PITCH_MAX_DEG)
            if transit: t["pitch"] = 40.0                                    # a transit pose may droop; only the clearances and limits count
            if err > IK_TOL: rec["ok"] = False; rec["why"] = "%s: IK %.1f mm" % (name, err * 1000); break
            if not pose_ok(c, t):
                rec["ok"] = False; rec["why"] = "%s: " % name + ", ".join(k2 for k2, v in (("upper", c["upper"] < t.get("upper", CLEAR_UPPER)), ("forearm", c["forearm"] < t.get("forearm", CLEAR_FOREARM)), ("hand", c["hand"] < t.get("hand", CLEAR_HAND)), ("pitch", abs(c["pitch"]) > t["pitch"]), ("limit", c["margin"] < t.get("margin", LIMIT_MARGIN)), ("table", c.get("table") is not None and c["table"] < t.get("table", TABLE_CLEAR)), ("right", c.get("right", 1.0) < t.get("right", CLEAR_RIGHT))) if v); break
        g = rec["poses"].get("grasp"); rec["pitch"] = None if g is None else g["pitch"]; tried.append(rec)
        if rec["ok"] and (best is None or (abs(g["pitch"]), abs(psi)) < (abs(best["pitch"]), abs(best["psi"]))):
            best = {"psi": psi, "pitch": g["pitch"], "d": d, "n": n, "grasp": P, "pre": P - n * pre, "high": P - n * pre + np.array([0, 0, HIGH_RISE]),
                    "q": {name: c["q"] for name, c in rec["poses"].items()}, "checks": {name: {k2: v for k2, v in c.items() if k2 not in ("q", "elbow", "palm")} for name, c in rec["poses"].items()}}
    return best, tried
