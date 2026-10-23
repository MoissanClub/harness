"""Read-only analysis of a teach_reach.py session: the reach envelope (soft samples, real-palm FK), the v2 planner's verdict at the
spots the hand reached at grasp height, and the camera-vs-model hand offset. Usage: python teach_analyse.py SESSION_DIR BRAIN_DIR"""
import json, math, os, sys
import numpy as np
D, B = sys.argv[1], sys.argv[2]; sys.path.insert(0, B); import geom
cal = json.load(open(os.path.join(B, "calib.json"))); E = cal.get("entries", cal)
cv = (lambda k: E[k]["value"]) if isinstance(E, dict) else (lambda k: next(e["value"] for e in E if e.get("name") == k))
cl = cv("clearance_m"); TH = {"upper": cl[0], "forearm": cl[1], "hand": cl[2], "right": cl[3], "pitch": cv("pitch_max_deg"), "table": cv("table_clear_m")}
ev = [json.loads(l) for l in open(os.path.join(D, "events.jsonl"))]
t_soft = next(e["t"] for e in ev if e["ev"] == "soft"); t_stiff = next((e["t"] for e in ev if e["ev"] == "stiff"), 1e12)
tz = next(e["table_z"] for e in ev if e["ev"] == "start")
J = [json.loads(l) for l in open(os.path.join(D, "joints.jsonl"))]; J = [j for j in J if t_soft + 2.5 < j["t"] < t_stiff][::5]
print("table z %.3f (depth, at start); thresholds %s; soft samples used %d (every 5th at 50 Hz)" % (tz, TH, len(J)))
R = []
for j in J:
    q = np.array(j["q"]); s = geom.arm_segments(q); c = geom.pose_checks(q, tz)
    R.append({"q": q, "palm": s["palm"], "d": s["d"], "pitch": float(c["pitch"]), "psi": float(c["psi"]), "c": c})
P = np.array([r["palm"] for r in R]); up = P[:, 2] - tz
print("\n1. Reach envelope: the largest palm x (ahead of the hips) by sideways position y and palm height above the table")
bands = [(0.00, 0.03), (0.03, 0.07), (0.07, 0.12), (0.12, 0.20), (0.20, 0.35)]
print("   y band      " + " ".join("%11s" % ("%+.2f..%+.2f" % b) for b in bands) + "   (palm above table, m; cell = max x / forearm pitch there)")
for y0 in np.arange(-0.15, 0.30, 0.05):
    cells = []
    for lo, hi in bands:
        m = (P[:, 1] >= y0) & (P[:, 1] < y0 + 0.05) & (up >= lo) & (up < hi)
        if m.sum(): i = np.flatnonzero(m)[np.argmax(P[m, 0])]; cells.append("%5.3f/%+3.0f" % (P[i, 0], R[i]["pitch"]))
        else: cells.append("      -    ")
    print("   %+.2f..%+.2f  " % (y0, y0 + 0.05) + " ".join("%11s" % c for c in cells))
print("\n2. The planner at the spots the hand reached at grasp height (palm 3-7 cm above the table: a 12-13.5 cm can), one per 3 cm cell,")
print("   the can axis inferred beside the palm along the grasp normal; the taught pose's own pitch and clearances next to the verdict")
g = [i for i in range(len(R)) if 0.03 <= up[i] < 0.07 and P[i, 0] > 0.28]
cells = {}
for i in g:
    k = (round(P[i, 0] / 0.03), round(P[i, 1] / 0.03))
    if k not in cells or abs(R[i]["pitch"]) < abs(R[cells[k]]["pitch"]): cells[k] = i
acc = 0
for k in sorted(cells, key=lambda k: (-k[1], k[0])):
    i = cells[k]; r = R[i]; dh = np.array([r["d"][0], r["d"][1], 0.0]); dh /= np.linalg.norm(dh) or 1.0
    n = np.array([dh[1], -dh[0], 0.0]); can = r["palm"] + n * (0.033 + 0.01); can_g = can.copy()
    plan, tried = geom.plan_reach(can_g, 0.033, table_z=tz, thresholds=TH, psis=list(range(-30, 61, 5)))
    acc += plan is not None; c = r["c"]
    viol = [nm for nm, bad in (("pitch", abs(c["pitch"]) > TH["pitch"]), ("upper", c["upper"] < TH["upper"]), ("forearm", c["forearm"] < TH["forearm"]), ("hand", c["hand"] < TH["hand"])) if bad]
    print("   palm (%.3f, %+.3f, %.3f) can (%.3f, %+.3f) | taught: psi %+4.0f pitch %+4.0f clear u %.3f f %.3f h %.3f %s | planner: %s" % (
        r["palm"][0], r["palm"][1], r["palm"][2], can[0], can[1], r["psi"], r["pitch"], c["upper"], c["forearm"], c["hand"],
        ("beyond " + ",".join(viol)) if viol else "within limits", ("OK psi %d pitch %+.0f" % (plan["psi"], plan["pitch"])) if plan else "no (%s)" % (tried[0]["why"][:40] if tried else "?")))
print("   planner accepts %d of %d taught grasp-height spots" % (acc, len(cells)))
print("\n3. Camera vs model: the hand found in depth near the FK palm (poses with a blob clear of the window edge)")
PO = [json.loads(l) for l in open(os.path.join(D, "poses.jsonl"))]
ok = [p for p in PO if p.get("blob") and p["blob"]["win_edge_px"] >= 8 and not p["blob"]["radius_cut"] and p["arm"] == "soft"]
if ok:
    fr = np.array([p["blob"]["front_minus_palm_along_d"] for p in ok]); off = np.array([p["blob"]["off_p_minus_palm"] for p in ok])
    dd = np.array([p["d"] for p in ok]); nn = np.cross(dd, [0, 0, 1.0]); nn /= np.linalg.norm(nn, axis=1, keepdims=True)
    od, on, oz = (off * dd).sum(1), (off * nn).sum(1), off[:, 2]
    q = lambda a: "median %+.3f (IQR %+.3f..%+.3f)" % (np.median(a), np.percentile(a, 25), np.percentile(a, 75))
    print("   n %d of %d soft poses with a blob" % (len(ok), sum(1 for p in PO if p["arm"] == "soft")))
    print("   fingertip front ahead of the FK palm along the forearm: %s  (the BrainCo hand from its URDF extents: about 0.114)" % q(fr))
    print("   visible-hand median minus FK palm: along forearm %s, along palm normal %s, z %s" % (q(od), q(on), q(oz)))
    for lo, hi in ((0.25, 0.35), (0.35, 0.42), (0.42, 0.55)):
        m = np.array([lo <= p["palm"][0] < hi for p in ok])
        if m.sum(): print("     palm x %.2f-%.2f (n %d): front-palm %s" % (lo, hi, m.sum(), q(fr[m])))
