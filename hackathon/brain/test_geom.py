"""Offline checks for geom.py (numpy only): the URDF chain against g1-fetch's pinocchio FK (values logged on the robot), the torso
clearance on a known collision pose, the plane fit and the hand blob on a synthetic frame from mock_robot. Run: python test_geom.py"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geom
os.environ.setdefault("BRAIN_MOCK_SCENE", "mid")
import mock_robot as M

def test_fk():
    # (q, g1-fetch fk position, allowed error): the first is an exact FK print (reach_test.py 2026-10-18), the others are IK targets
    # whose logged pos_err is the distance between fk(q) and the target
    for q, want, tol in (([-0.5, 0.25, 0.0, 0.6, 0.0], [0.356, 0.190, 0.109], 0.002), ([-0.95, 0.09, 0.3, 1.05, 0.0], [0.42, 0.149, 0.152], 0.008),
                         ([-1.09, -0.04, 0.84, 1.28, 0.0], [0.438, 0.11, 0.119], 0.030)):
        e = np.linalg.norm(geom.fk(q)[:3, 3] - np.array(want)); assert e < tol, (q, e)
    R = geom.fk([-0.5, 0.25, 0.0, 0.6, 0.0])[:3, :3]
    assert np.allclose(R, [[0.995, 0.014, 0.1], [0.011, 0.968, -0.251], [-0.1, 0.251, 0.963]], atol=0.002)

def test_clearance():
    # Oct 19: pre-grasp 9.5 cm left at 25 cm ahead, forearm along +x: the forearm was blocked by the torso. A pose with the hand at
    # (0.25, 0.10, 0.14) and the forearm along +x must fail the clearance; the verified lateral poses (pre-grasp y 0.18-0.23,
    # Oct 21 grasps at can y 0.087-0.13) must pass with the 0.04 margin.
    rb = M.build_robot(M.load_config(""))
    q_bad, _ = M.solve_pose(rb, "left", [0.25, 0.10, 0.14], [1, 0, 0], [0, -1, 0])
    assert geom.clearance(q_bad) < 0.04, geom.clearance(q_bad)
    for p in ([0.30, 0.23, 0.14], [0.30, 0.18, 0.146], [0.373, 0.175, 0.144]):
        q_ok, _ = M.solve_pose(rb, "left", p, [1, 0, 0], [0, -1, 0]); assert geom.clearance(q_ok) >= 0.04, (p, geom.clearance(q_ok))

def test_plan_memo_example():
    # V2_STRATEGY section 3 worked example: can (0.35, 0, 0.13), psi 30 -> IK 0, pitch ~1.4 deg, elbow (0.069, 0.205, 0.130), q (-16, 22, -29, 2) deg
    d, n = geom.grasp_frame(30); P = np.array([0.35, 0.0, 0.13]) - n * 0.043
    q, err, pitch, _ = geom.ik4(P, 30, [0.0, 0.25, 0.0, 1.0, 0.0]); c = geom.pose_checks(q)
    assert err < 0.001 and abs(pitch) < 2.5 and np.linalg.norm(c["elbow"] - np.array([0.069, 0.205, 0.130])) < 0.005, (err, pitch, c["elbow"])
    assert np.allclose(np.degrees(q[:4]), [-16, 22, -29, 2], atol=1.5), np.degrees(q[:4])
    plan, tried = geom.plan_reach([0.35, 0.0, 0.13], 0.033, table_z=0.075)
    assert plan is not None and 20 <= plan["psi"] <= 40, (plan and plan["psi"], [t["psi"] for t in tried if t["ok"]])
    q0, err0, _, _ = geom.ik4(np.array([0.35, 0.0, 0.13]) - geom.grasp_frame(0)[1] * 0.043, 0, [0.0, 0.25, 0.0, 1.0, 0.0])
    assert geom.pose_checks(q0)["upper"] == 0.0            # psi 0: the elbow inside the torso

def test_plane_and_blob():
    rb = M.build_robot(M.load_config("")); rb.arms.enable()
    c = M.SCENE[0]; can, R = c["p"], c["diam"] / 2
    # the v2 pre-grasp (the kill test's pose): the command raised by the sag so the measured hand sits on the plan
    plan, tried = geom.plan_reach([can[0], can[1], M.TABLE_Z + c["h"] / 2 - 0.015], R, table_z=M.TABLE_Z); assert plan is not None
    target = plan["pre"]; q = plan["q"]["pre"].copy(); cmd = target.copy()
    for _ in range(5):
        cmd = cmd + (target - geom.fk_chain_side(q + M.sag_dq(q))[5][:3, 3]); q, err, _, _ = geom.ik4(cmd, plan["psi"], q); q[4] = geom.wrist_roll_for_palm(q, plan["n"])
    rb.arms.set_target("left", q); assert rb.arms.contact_q is None
    f = rb.camera.read(); dets = rb.detector.detect(f.color); assert dets
    cb = dets[0].box; cloud = M.box_cloud(f, (max(0, cb[0] - 150), cb[3] + 5, min(639, cb[2] + 150), 479), rb.frames, step=3, max_points=6000)
    plane = geom.table_plane(cloud, z_hint=M.TABLE_Z); assert plane and abs(plane["z"] - M.TABLE_Z) < 0.01, plane
    model = geom.fk_chain_side(np.asarray(rb.arms.measured("left")))[5][:3, 3]; tp, Rh = rb.arms.true_palm(), rb.arms.true_R(); d = plan["d"]
    assert np.linalg.norm(model - target) < 0.005, (model, target)
    blob = geom.hand_blob(f, rb.frames, model, plane, xdir=d, ndir=plan["n"], exclude_cyl=[(cc["p"], cc["diam"] / 2) for cc in M.SCENE]); assert blob is not None   # every can, as brain.measure
    assert blob["win_edge_px"] >= 8 and not blob["radius_cut"], (blob["win_edge_px"], blob["radius_cut"])    # the whole hand inside the window
    assert float(tp @ d) < blob["front"] < float((tp + Rh[:, 0] * 0.125) @ d), (blob["front"], tp @ d)          # the front is on the hand, ahead of the palm
    assert np.linalg.norm(blob["p"] - tp) < 0.06, (blob["p"], tp)
    assert not geom.obstacle_ahead(f, rb.frames, z_lo=0.15, y_half=0.12)[0]
    # a hand at the image's left border (forearm straight ahead beside the can): the margins say so, the features are not used
    xdir, palm = geom.grasp_vectors(0)
    pre = can - palm * (R + 0.01) + xdir * (-0.096) - palm * 0.05 + np.array([0.0, 0.0, 0.05])     # 5 cm up: the sagged hand above the table
    q2, res = M.solve_pose(rb, "left", pre, xdir, palm); rb.arms.set_target("left", q2); f2 = rb.camera.read()
    model2 = rb.kin.fk("left", rb.arms.measured("left"))[:3, 3]
    b2 = geom.hand_blob(f2, rb.frames, model2 + xdir * 0.08, plane, xdir=xdir, exclude_cyl=[(cc["p"], cc["diam"] / 2) for cc in M.SCENE])
    assert b2 is None or b2["win_edge_px"] < 8 or b2["bbox"][0] < 8, b2 and (b2["win_edge_px"], b2["bbox"])

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
