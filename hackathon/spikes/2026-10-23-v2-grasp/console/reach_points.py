import json, os, sys, time
import numpy as np
sys.path.insert(0, sys.argv[1]); import geom
cal = json.load(open(os.path.join(sys.argv[1], "calib.json"))); E = cal.get("entries", cal)
cv = (lambda k: E[k]["value"]) if isinstance(E, dict) else (lambda k: next(e["value"] for e in E if e.get("name") == k))
cl = cv("clearance_m"); th = {"upper": cl[0], "forearm": cl[1], "hand": cl[2], "right": cl[3], "pitch": cv("pitch_max_deg"), "table": cv("table_clear_m")}
print("pitch limit", th["pitch"], flush=True)
for label, tz in [("table z %+.3f" % float(a), float(a)) for a in sys.argv[2:]]:
    for x in (0.36, 0.40, 0.44):
        row = []
        for y in (0.18, 0.06, -0.06):
            t = time.time(); plan, tried = geom.plan_reach(np.array([x, y, tz + 0.061 - 0.015]), 0.033, table_z=tz, thresholds=th, psis=list(range(-30, 61, 5)))
            row.append("y%+.2f %s" % (y, ("OK psi %d pitch %+.0f" % (plan["psi"], plan["pitch"])) if plan else "no (%s)" % (tried[0]["why"][:28] if tried else "?")))
        print("%-13s x %.2f | %s" % (label, x, " | ".join(row)), flush=True)
