"""Reach map for the lateral grasp: for a grid of can positions (pelvis frame, can mid-height z), check IK error at the pre-grasp and grasp points."""
import sys, numpy as np
sys.path.insert(0, "/home/unitree/g1-fetch")
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml")
from g1_fetch.control.arm import ArmKinematics
kin = ArmKinematics(cfg)
DX, R, DZ, PRE = -0.096, 0.033, 0.0, 0.05
XDIR = np.array([1.0, 0.0, 0.0]); z = 0.13
seed = np.array([0.0, 0.25, 0.0, 1.0, 0.0])
xs = np.arange(0.26, 0.48, 0.03); ys = np.arange(-0.10, 0.41, 0.05)
print("IK error (cm) at the grasp point; '.' <= 1.5 cm, 'o' <= 3.5 cm, 'X' unreachable; rows = can x (forward), cols = can y (left)")
print("      " + " ".join("%5.2f" % y for y in ys))
for x in xs:
    row = []
    for y in ys:
        can = np.array([x, y, z]); g = can + np.array([DX, R + 0.01, DZ]); p = g + np.array([0.0, PRE, 0.0])
        eg = kin.ik("left", g, XDIR, q_seed=seed, dir_weight=0.5).pos_err; ep = kin.ik("left", p, XDIR, q_seed=seed, dir_weight=0.5).pos_err
        e = max(eg, ep) * 100
        row.append(("  . " if e <= 1.5 else ("  o " if e <= 3.5 else "  X ")) + "%2.0f" % e if e < 100 else "  X 99")
    print("%4.2f " % x + "".join(row))
