"""Offline checks for motion.py on the mock arm with the gravity sag fitted to Tuesday's logs (no robot). Run: python test_motion.py [names]
MOTION_MODULE=/path/to/other/motion.py runs the same checks on another version (the regression check: c39a468's fails the round-2 ones).
The mock here has no model error (ERR 0.096 = the real-palm model, ERRK 0, ERRZ 0), so the model palm is the hand the table meets.
- V2_REVIEW blocker 1: the pre-grasp correction streams in capped sub-steps (a 3-5 cm error in one target hits the 2 cm cap).
- round 2 blocker 1: no joint changes by more than joint_step x speed in one streamed target, on every move (the wrist roll of the
  high move snapped 0.59 rad in one target), at speed 1.0 and 0.5.
- round 2 blocker 4 and round 3: the open hand's LOWEST point (the palm box and the fingertips through pitch and roll; the mock's
  12.5 cm hand) stays above the table at every target, for the 12.2 and the 13.5 cm can and for a 3 cm servo nudge toward the table;
  at the kill test's 2 cm floor margin, with the depth plane 5/10/20 mm low, also with the hand 1 cm lower than the model, no
  correction is streamed onto the table and the push stays under 10 mm (8e226e9 streamed the first round before its follow check)."""
import importlib.util, os, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
for k, v in (("BRAIN_MOCK_SCENE", "mid"), ("BRAIN_MOCK_SLEEP", "0.02"), ("BRAIN_MOCK_ERR", "0.096"), ("BRAIN_MOCK_ERRK", "0"), ("BRAIN_MOCK_ERRZ", "0")): os.environ.setdefault(k, v)
import geom, mock_robot as M
M.install(None)                                                    # fake g1_fetch modules, scaled time.sleep
geom.FINGERTIP = M.HAND_BOX[0][1]                                  # the floor's hand = the mock's hand (12.5 cm fingers), as check.py's --fingertip
if os.environ.get("MOTION_MODULE"):
    spec = importlib.util.spec_from_file_location("motion", os.environ["MOTION_MODULE"]); motion = importlib.util.module_from_spec(spec); spec.loader.exec_module(motion)
else:
    import motion
HALF_H, MARGIN, KILL_MARGIN = 0.045, 0.005, 0.02                   # calib palm_half_height_m; the floor margin (calib table_floor_margin_m); the kill test's --floor-margin



def setup(h=0.135, xy=None, speed=1.0, table_z=M.TABLE_Z, margin=MARGIN):
    """The mock arm at home and the plan for a can of height h at xy (default: the scene's can) on a table believed at table_z."""
    rb = M.build_robot(M.load_config("")); rb.arms.enable(); arm = motion.Arm(rb, None, speed_scale=speed)
    c = M.SCENE[0]; p = c["p"] if xy is None else np.array([xy[0], xy[1], 0.0])
    plan, tried = geom.plan_reach([p[0], p[1], table_z + h / 2 - 0.015], c["diam"] / 2, table_z=table_z)
    assert plan is not None, tried[:3]
    arm.psi, arm.n = plan["psi"], plan["n"]; arm.floor_after = table_z + margin       # set after the high waypoint, as the brain does
    return rb, arm, plan


def set_floor(arm):
    """The table floor after the high waypoint, as the brain sets it (floor_z: the same floor for 8e226e9's motion.py, palm centre based)."""
    arm.table_floor = arm.floor_after; arm.floor_z = arm.floor_after + HALF_H


def trace_into(arm, rec):
    """Record (label, commanded q, measured palm) at every streamed target."""
    arm.trace = lambda label: rec.append((label, arm.q_cmd(), arm.palm_meas()))


def raise_arm(arm, plan, table_z=M.TABLE_Z):
    """The brain's raise: up beside the hip 2 cm behind it to the table top + 3 cm, then the raise waypoint (both from home_q's palm)."""
    home = arm.palm(M.HOME_Q); y = max(plan["pre"][1], 0.18)
    arm.goto(np.array([home[0] - 0.02, y, table_z + 0.03]), 0.10, "up-low", psi="free", correct=0)
    return arm.goto(np.array([home[0] + 0.05, y, plan["high"][2]]), 0.10, "up", psi="free", correct=0)


def to_pre(arm, plan, correct=4):
    raise_arm(arm, plan); arm.goto(plan["high"], 0.08, "high", correct=0); set_floor(arm)
    return arm.goto(plan["pre"], 0.05, "pre", correct=correct, ff=True)


def test_sag_matches_the_logs():
    # Tuesday (spikes/office-tue-brain, v1, model palm 0.15): uncorrected high waypoints 2.5-4.6 cm below the command
    rb, arm, plan = setup(); q = plan["q"]["high"]; dq = M.sag_dq(q)
    s15 = float(np.linalg.norm(geom.fk(q)[:3, 3] - geom.fk(q + dq)[:3, 3]))
    assert 0.025 <= s15 <= 0.05, s15
    assert 0.04 <= float(np.max(np.abs(dq))) <= 0.08                 # tracking-error baselines 0.044-0.069 rad on Tuesday


def test_pregrasp_correction_streams_and_the_palm_stays_above_the_table():
    for h in (0.122, 0.135):                                       # the purple La Croix leaves 1 mm under the planned palm, the Chi 7.5 mm
        rb, arm, plan = setup(h); rec = []; trace_into(arm, rec)
        raise_arm(arm, plan); m_high = arm.goto(plan["high"], 0.08, "high", correct=0)
        assert float(np.linalg.norm(plan["high"] - m_high)) > arm.max_step, "the uncorrected high waypoint must show the logged sag"
        set_floor(arm); M.STATS["table_contacts"] = 0; m_pre = arm.goto(plan["pre"], 0.05, "pre", correct=4, ff=True)
        goal = arm.last["goal"]                                     # the pre-grasp, raised by the floor where it binds
        assert float(np.linalg.norm(goal - m_pre)) < 0.006, (h, m_pre, goal)
        lows = [geom.hand_lowest(q + M.sag_dq(q))[0] for _, q, p in rec if p[0] > M.TABLE_X[0]]            # the settled hand at every target over the table
        assert min(lows) >= M.TABLE_Z, "can %.3f: the hand's lowest point went %.1f mm under the table top while lowering" % (h, (M.TABLE_Z - min(lows)) * 1000)
        assert M.STATS["table_contacts"] == 0, M.STATS["table_contacts"]


def test_servo_nudge_toward_the_table_and_steps():
    for h in (0.122, 0.135):
        rb, arm, plan = setup(h); to_pre(arm, plan); rec = []; trace_into(arm, rec); M.STATS["table_contacts"] = 0
        m0 = arm.palm_meas(); m1 = arm.nudge(np.array([0.03, 0.0, -0.03]), "servo")      # 3 cm forward and 3 cm down: the servo's largest step
        goal = arm.last["goal"]
        assert np.linalg.norm(m1 - goal) < 0.006, (m1, goal)
        lows = [geom.hand_lowest(q + M.sag_dq(q))[0] for _, q, p in rec if p[0] > M.TABLE_X[0]]
        assert min(lows) >= M.TABLE_Z, "can %.3f: the servo nudge put the hand's lowest point %.1f mm under the table top" % (h, (M.TABLE_Z - min(lows)) * 1000)
        assert M.STATS["table_contacts"] == 0, M.STATS["table_contacts"]
        before = arm.palm_meas(); meas, te = arm.step_along(plan["n"], 0.01, "ap0")
        assert abs(float((meas - before) @ plan["n"]) - 0.01) < 0.004, meas - before


def test_joint_step_per_target():
    for speed in (1.0, 0.5):
        rb, arm, plan = setup(speed=speed); q_prev = [arm.q_cmd()]; worst = [0.0, ""]
        def tr(label):
            q = arm.q_cmd(); m = float(np.max(np.abs(q - q_prev[0]))); q_prev[0] = q
            if m > worst[0]: worst[:] = [m, label]
        arm.trace = tr
        to_pre(arm, plan); arm.nudge(np.array([0.02, 0.0, 0.01]), "servo")
        for i in range(3): arm.step_along(plan["n"], 0.01, "ap%d" % i)
        arm.goto(arm.palm_meas() + np.array([0.0, 0.0, 0.06]), 0.04, "lift", correct=2)
        cap = 0.02 * speed + 1e-9
        assert worst[0] <= cap, "speed %.1f: %s moved a joint %.3f rad in one target (cap %.3f)" % (speed, worst[1], worst[0], cap)


def test_corrections_stop_on_the_table():
    for errz in (0.0, -0.01):                                       # the true hand as modelled, and 1 cm lower than the model
        M.ERRZ = errz
        for bias in (0.005, 0.01, 0.02):                            # the depth plane this much below the real table
            rb, arm, plan = setup(0.122, table_z=M.TABLE_Z - bias, margin=KILL_MARGIN); rec = []; trace_into(arm, rec); M.STATS["push"] = 0.0
            to_pre(arm, plan)
            assert M.STATS["push"] <= 0.010, "plane %d mm low, hand %d mm low: the settled command sits %.1f mm under the hand on the table" % (bias * 1000, -errz * 1000, M.STATS["push"] * 1000)
            if arm.last.get("blocked"): assert "contact" in arm.last["blocked"] or "followed" in arm.last["blocked"], arm.last["blocked"]
    M.ERRZ = 0.0


if __name__ == "__main__":
    want = sys.argv[1:]
    for name, fn in list(globals().items()):
        if name.startswith("test_") and (not want or any(w in name for w in want)): fn(); print("ok", name, flush=True)
