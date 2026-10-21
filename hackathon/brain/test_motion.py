"""Offline checks for motion.py on the mock arm with the gravity sag fitted to Tuesday's logs (no robot). Run: python test_motion.py
Blocker 1 of V2_REVIEW.md: the pre-grasp correction must stream in capped sub-steps (a 3-5 cm error in one target hits the 2 cm cap),
and the lowering to the pre-grasp must not dip below the target (the table is 4-5 cm under the palm there).
MOTION_MODULE=/path/to/old/motion.py runs the same checks on another version (the regression check: the 2d4f1ca version fails)."""
import importlib.util, os, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.environ.setdefault("BRAIN_MOCK_SCENE", "mid"); os.environ.setdefault("BRAIN_MOCK_SLEEP", "0.02")
import geom, mock_robot as M
M.install(None)                                                    # fake g1_fetch modules, scaled time.sleep
if os.environ.get("MOTION_MODULE"):
    spec = importlib.util.spec_from_file_location("motion", os.environ["MOTION_MODULE"]); motion = importlib.util.module_from_spec(spec); spec.loader.exec_module(motion)
else:
    import motion


def setup():
    rb = M.build_robot(M.load_config("")); rb.arms.enable(); arm = motion.Arm(rb, None)
    c = M.SCENE[0]; plan, tried = geom.plan_reach([c["p"][0], c["p"][1], M.TABLE_Z + c["h"] / 2 - 0.015], c["diam"] / 2, table_z=M.TABLE_Z)
    assert plan is not None, tried[:3]
    arm.psi, arm.n = plan["psi"], plan["n"]
    return rb, arm, plan


def test_sag_matches_the_logs():
    # Tuesday (spikes/office-tue-brain, v1, model palm 0.15): uncorrected high waypoints 2.5-4.6 cm below the command
    rb, arm, plan = setup(); q = plan["q"]["high"]; dq = M.sag_dq(q)
    s15 = float(np.linalg.norm(geom.fk(q)[:3, 3] - geom.fk(q + dq)[:3, 3]))
    assert 0.025 <= s15 <= 0.05, s15
    assert 0.04 <= float(np.max(np.abs(dq))) <= 0.08                 # tracking-error baselines 0.044-0.069 rad on Tuesday


def test_pregrasp_correction_streams_and_never_dips():
    rb, arm, plan = setup(); low = []
    arm.trace = lambda label: low.append((label, float(arm.palm_meas()[2])))
    home = arm.palm_cmd(); up = np.array([home[0] + 0.05, max(plan["pre"][1], 0.18), plan["high"][2]])
    arm.goto(up, 0.10, "up", psi="free", correct=0)
    m_high = arm.goto(plan["high"], 0.08, "high", correct=0)
    raw = float(np.linalg.norm(plan["high"] - m_high))
    assert raw > arm.max_step, "the uncorrected high waypoint must show the logged sag (2.5-4.7 cm), got %.3f" % raw
    del low[:]
    kw = {"ff": True} if "ff" in motion.Arm.goto.__code__.co_varnames else {}
    m_pre = arm.goto(plan["pre"], 0.05, "pre", correct=4, **kw)
    assert float(np.linalg.norm(plan["pre"] - m_pre)) < 0.006, m_pre
    dip = plan["pre"][2] - min(z for _, z in low)
    assert dip < 0.01, "the measured palm dipped %.3f m below the pre-grasp while lowering (the table is under it)" % dip


def test_servo_nudge_and_steps():
    rb, arm, plan = setup()
    home = arm.palm_cmd(); arm.goto(np.array([home[0] + 0.05, max(plan["pre"][1], 0.18), plan["high"][2]]), 0.10, "up", psi="free", correct=0)
    arm.goto(plan["high"], 0.08, "high", correct=0); arm.goto(plan["pre"], 0.05, "pre", correct=4, ff=True)
    m0 = arm.palm_meas(); m1 = arm.nudge(np.array([0.03, 0.0, -0.01]) @ np.eye(3), "servo")   # a 3 cm servo correction: streamed, not one jump
    assert np.linalg.norm(m1 - (m0 + np.array([0.03, 0.0, -0.01]))) < 0.006, m1 - m0
    before = arm.palm_meas(); meas, te = arm.step_along(plan["n"], 0.01, "ap0")
    assert abs(float((meas - before) @ plan["n"]) - 0.01) < 0.004, meas - before


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
