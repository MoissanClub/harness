"""Read-only: which can positions does brain v2's own planner (geom.plan_reach, the brain's default thresholds from calib.json) accept
at a given table height, and how does the forearm-pitch limit change that? Usage: python reach_sweep.py BRAIN_DIR"""
import json, os, sys
import numpy as np
sys.path.insert(0, sys.argv[1]); import geom
cal = json.load(open(os.path.join(sys.argv[1], "calib.json"))); E = cal.get("entries", cal)
cv = (lambda k: E[k]["value"]) if isinstance(E, dict) else (lambda k: next(e["value"] for e in E if e.get("name") == k))
cl = cv("clearance_m"); base = {"upper": cl[0], "forearm": cl[1], "hand": cl[2], "right": cl[3], "pitch": cv("pitch_max_deg"), "table": cv("table_clear_m")}
psis = list(range(-30, 61, 5)); r, h, below = 0.033, 0.122, 0.015
xs = np.round(np.arange(0.28, 0.561, 0.02), 3); ys = np.round(np.arange(-0.14, 0.261, 0.04), 3)
print("defaults:", base)
for label, tz in (("this desk (77 cm)", -0.081), ("+5 cm box", -0.031), ("+10 cm box", 0.019), ("+15 cm box (Tuesday's height)", 0.069)):
    for pmax in (base["pitch"], 25, 35):
        th = dict(base, pitch=pmax); ok = []; why = {}
        for x in xs:
            for y in ys:
                plan, tried = geom.plan_reach(np.array([x, y, tz + h / 2 - below]), r, table_z=tz, thresholds=th, psis=psis)
                if plan is not None: ok.append((x, y))
                elif tried: w = tried[0]["why"].split(":")[0]; why[w] = why.get(w, 0) + 1
        xr = "x %.2f-%.2f" % (min(p[0] for p in ok), max(p[0] for p in ok)) if ok else "none"
        print("%-30s pitch<=%2d: %3d of %d cells %s %s" % (label, pmax, len(ok), len(xs) * len(ys), xr, "" if ok else "first refusal: %s" % why))
        if ok and pmax == base["pitch"]:
            for y in ys:
                row = [x for (x, yy) in ok if yy == y]
                if row: print("     y %+.2f: x %.2f-%.2f" % (y, min(row), max(row)))
