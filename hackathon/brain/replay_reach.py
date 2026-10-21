"""Experiment 1 of V2_STRATEGY.md (no robot): replay the logged can positions of Oct 19-21 through the v2 reach planner (geom.py) and
print, per position, the outcome on the day, the planner's psi / pitch / clearances, and the psi-0 (v1 strategy) clearances.
Pass: every position that was grasped or missed with the hand beside the can is accepted; the Oct 19 centre-line block
[0.347, 0.008] is rejected at psi 0 and accepted at an inward psi; the 030059 misses show the smallest psi-0 upper-arm clearance.
Usage: python replay_reach.py [--table 0.075] [--upper 0.015]"""
import argparse, os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import geom
ap = argparse.ArgumentParser(); ap.add_argument("--table", type=float, default=None, help="table z (pelvis); default: can z - 0.065"); ap.add_argument("--upper", type=float, default=geom.CLEAR_UPPER)
ap.add_argument("--forearm", type=float, default=geom.CLEAR_FOREARM); ap.add_argument("--hand", type=float, default=geom.CLEAR_HAND)
A = ap.parse_args()
# (label, can axis [x, y, z], diameter, outcome on the day). Oct 19 trials from grab_trials.jsonl (can_before, auto diameter 0.055 unless
# noted), Oct 21 from the order logs (axis after the fix).
CANS = [("19 trial5 grasp", [0.391, 0.094, 0.142], 0.055, "grasped"), ("19 trial6 grasp", [0.396, 0.113, 0.143], 0.055, "grasped"),
        ("19 trial7 grasp", [0.384, 0.100, 0.146], 0.055, "grasped"), ("19 trial8 grasp", [0.383, 0.099, 0.146], 0.055, "grasped"),
        ("19 trial9 grasp", [0.369, 0.117, 0.124], 0.066, "grasped"), ("19 purple grasp", [0.382, 0.211, 0.125], 0.066, "grasped"),
        ("19 white CENTRE", [0.347, 0.008, 0.145], 0.055, "blocked by the torso (forearm +x)"), ("19 white grasp", [0.304, 0.174, 0.144], 0.066, "grasped"),
        ("19 purple grasp2", [0.411, 0.145, 0.122], 0.066, "grasped"), ("21 024115 o1 grasp", [0.362, 0.087, 0.146], 0.066, "grasped"),
        ("21 024115 o2 grasp", [0.350, 0.100, 0.148], 0.066, "grasped (pre only logged)"), ("21 025439 o1 grasp", [0.380, 0.107, 0.145], 0.066, "grasped"),
        ("21 025439 o2 grasp", [0.469, 0.087, 0.144], 0.055, "grasped"), ("21 021723 o2 miss", [0.400, 0.119, 0.142], 0.066, "missed (surface target)"),
        ("21 030059 o1 miss", [0.459, 0.085, 0.140], 0.066, "missed, pushed"), ("21 030059 o2 miss", [0.464, 0.070, 0.141], 0.055, "missed, thumb+pinky 0.9"),
        ("21 dry can", [0.401, 0.030, 0.140], 0.055, "lane refusal"), ("21 far can", [0.491, 0.165, 0.148], 0.066, "lane refusal (too far)")]
th = {"upper": A.upper, "forearm": A.forearm, "hand": A.hand}
print("%-22s %-28s %5s %5s | psi0: upper fore hand ik | plan: psi pitch upper fore hand table | accepted psis" % ("position", "outcome on the day", "y", "x"))
for label, can, diam, outcome in CANS:
    table_z = A.table if A.table is not None else can[2] - 0.065
    d0, n0 = geom.grasp_frame(0); q0, err0, pitch0, _ = geom.ik4(np.asarray(can) - n0 * (diam / 2 + 0.01), 0, [0.0, 0.25, 0.0, 1.0, 0.0]); c0 = geom.pose_checks(q0, table_z)
    plan, tried = geom.plan_reach(can, diam / 2, table_z=table_z, thresholds=th)
    acc = [t["psi"] for t in tried if t["ok"]]
    p = "  none (%s)" % (tried[0]["why"] if tried else "?") if plan is None else "%3d %+5.1f %.3f %.3f %.3f %+.3f" % (plan["psi"], plan["pitch"], plan["checks"]["grasp"]["upper"], plan["checks"]["grasp"]["forearm"], plan["checks"]["grasp"]["hand"], plan["checks"]["grasp"]["table"])
    print("%-22s %-28s %5.2f %5.2f | %.3f %.3f %.3f %4.1f | %s | %s" % (label, outcome[:28], can[1], can[0], c0["upper"], c0["forearm"], c0["hand"], err0 * 1000, p, sorted(acc)))
