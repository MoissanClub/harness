"""Read-only analysis of one brain bundle: table height (by x band and under each can), the table's near edge, the floor height.
Usage: python table_from_depth.py BUNDLE_DIR LABEL"""
import json, sys
import numpy as np, cv2
d, label = sys.argv[1], sys.argv[2]
meta = json.load(open(f"{d}/bundle_{label}_meta.json"))
dep = cv2.imread(f"{d}/bundle_{label}_depth.png", cv2.IMREAD_UNCHANGED).astype(float) / 1000.0
K = meta["intrinsics"]; T = np.array(meta["T_optical_to_pelvis"])
fx, fy = K["fx"], K["fy"]; cx, cy = K.get("ppx", K["width"] / 2), K.get("ppy", K["height"] / 2)
H, W = dep.shape; vv, uu = np.mgrid[0:H:2, 0:W:2]; z = dep[0:H:2, 0:W:2]; ok = (z > 0.15) & (z < 3.0)
P = np.stack([(uu - cx) / fx * z, (vv - cy) / fy * z, z, np.ones_like(z)], -1)[ok] @ T.T
x, y, h = P[:, 0], P[:, 1], P[:, 2]; uv = np.stack([uu[ok], vv[ok]], -1)
def mode(a, lo, hi, w=0.005):
    a = a[(a > lo) & (a < hi)]
    if a.size < 50: return None, a.size
    hist, e = np.histogram(a, bins=np.arange(lo, hi + w, w)); i = hist.argmax(); return round(float((e[i] + e[i + 1]) / 2), 3), int(a.size)
floor, nf = mode(h, -1.0, -0.6); top, nt = mode(h[(x > 0.25) & (np.abs(y) < 0.45)], -0.25, 0.15)
print(f"floor z (mode) {floor} (n {nf}); pelvis height implied {None if floor is None else -floor}")
print(f"table z (mode, x>0.25, |y|<0.45) {top} (n {nt})")
tab = (np.abs(h - top) < 0.02) & (np.abs(y) < 0.45) if top is not None else np.zeros_like(h, bool)
for x0 in np.arange(0.20, 0.70, 0.05):
    s = tab & (x >= x0) & (x < x0 + 0.05)
    if s.sum() > 30: print(f"  x {x0:.2f}-{x0 + 0.05:.2f}: table z median {np.median(h[s]):.3f} (n {int(s.sum())})")
edges = []
for y0 in np.arange(-0.30, 0.30, 0.05):
    s = tab & (y >= y0) & (y < y0 + 0.05)
    if s.sum() > 30: edges.append(float(np.percentile(x[s], 1))); print(f"  y {y0:+.2f}..{y0 + 0.05:+.2f}: nearest table x (1st pct) {edges[-1]:.3f} (n {int(s.sum())}, image row max {int(uv[s][:, 1].max())})")
if edges: print(f"near edge x: median {np.median(edges):.3f}, min {min(edges):.3f}, max {max(edges):.3f}; image bottom row {H - 1}")
for c in meta.get("cans", []) or []: pass
tx, ty = meta["target"][0], meta["target"][1]
s = tab & (np.abs(y - ty) < 0.06) & (x > tx - 0.12) & (x < tx - 0.04)
if s.sum() > 20: print(f"table z just in front of the target ({tx:.2f}, {ty:.2f}): {np.median(h[s]):.3f} (n {int(s.sum())})")
