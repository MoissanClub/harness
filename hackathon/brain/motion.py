"""Motion layer for brain v2: every left-arm move is planned on geom.py's real-palm model (URDF chain, palm 0.246 m along the wrist
roll axis, 4-joint IK with the forearm yaw held, wrist roll from the palm normal) and streamed to g1-fetch's arm streamer as joint
targets. The arm sags under gravity: on Tuesday the measured palm sat 1.9-2.6 cm below the command at the raise and 2.5-4.7 cm at the
high waypoint. So (1) a move can feed the current sag forward (command = goal + the sag measured at rest before the move), which keeps
the measured palm on the line when lowering toward the table; (2) the remaining error is corrected by streaming the command in capped
sub-steps until the MEASURED palm is within 6 mm (never one jump: the per-target cap of 2 cm would refuse it); (3) an approach step
carries the sag and gets one correction unless the hand did not follow (blocked: no harder push, the caller's lag check decides).
Safety: IK error <= tol per target, joint-limit margin, a 2 cm per-target displacement cap, a cross-check of each goal against
g1-fetch's pinocchio FK. Also used by mock_robot (the same code path)."""
import math, time
import numpy as np
import geom


class SkillFailed(RuntimeError): pass


class Arm:
    def __init__(self, rb, cfg, log=None, tol=None, step_s=0.02, max_step=0.02, sub_step=0.01, corr_tol=0.006, corr_speed=0.04,
                 speed_scale=1.0, roll_inward=0.0, check_abort=None, kin_check=True):
        self.rb, self.cfg, self.log, self.step_s, self.max_step, self.roll_inward = rb, cfg, log, step_s, max_step, roll_inward
        self.tol = geom.IK_TOL if tol is None else tol
        self.sub_step, self.corr_tol, self.corr_speed, self.speed_scale = sub_step, corr_tol, corr_speed, speed_scale
        self.check_abort = check_abort or (lambda: None); self.kin_check = kin_check; self.psi = 0.0; self.n = np.array([0.0, -1.0, 0.0]); self.last = {}
        self.trace = None                                                  # optional callback(label) after each streamed target (tests)
        self.last_path = []                                                # the joint targets of the last goto (the raise is replayed backwards to go home)

    # --- model -------------------------------------------------------------------------------------------------------------------------
    def palm(self, q): return geom.fk_chain_side(np.asarray(q, float))[5][:3, 3]
    def q_cmd(self): return np.asarray(self.rb.arms.cmd["left"], float).copy()
    def q_meas(self): return np.asarray(self.rb.arms.measured("left"), float).copy()
    def palm_cmd(self): return self.palm(self.q_cmd())
    def palm_meas(self): return self.palm(self.q_meas())
    def sag(self): return self.palm_cmd() - self.palm_meas()        # where the command sits relative to the measured hand (the sag)
    def tracking(self): return float(self.rb.arms.tracking_error("left"))

    def yaw_now(self): return float(geom.forearm_yaw_pitch(geom.arm_segments(self.q_cmd())["d"])[0])

    def solve(self, p, psi=None, n=None, q_seed=None):
        """q5 for the real palm at p with the forearm yaw psi ("free" = position only, for the raise) and the palm normal n ("keep" =
        the seed's wrist roll).
        Raises SkillFailed beyond tol or the limit margin."""
        psi = self.psi if psi is None else psi; n = self.n if n is None else n; seed = self.q_cmd() if q_seed is None else q_seed
        q, err, pitch, d = geom.ik4(p, None if psi == "free" else psi, seed)
        if err > self.tol: raise SkillFailed("IK error %.1f mm for the palm at %s (psi %s)" % (err * 1000, np.round(p, 3).tolist(), psi))
        keep = psi == "free" or (isinstance(n, str) and n == "keep")          # position-only moves (and n="keep") keep the hand's roll
        q[4] = float(np.asarray(seed)[4]) if keep else geom.wrist_roll_for_palm(q, n, self.roll_inward)
        margin = float(np.min(np.minimum(q - geom.Q_LOWER, geom.Q_UPPER - q)))
        if margin < geom.LIMIT_MARGIN * 0.5: raise SkillFailed("joint %d within %.0f deg of its limit" % (int(np.argmin(np.minimum(q - geom.Q_LOWER, geom.Q_UPPER - q))), math.degrees(margin)))
        return q, err, pitch

    def cross_check(self, q, label=""):
        """g1-fetch's pinocchio FK (model palm 0.15) must agree with geom's chain at the 0.15 point to 5 mm; a disagreement is a modelling
        bug, so the move is refused."""
        if not self.kin_check or not hasattr(self.rb, "kin"): return 0.0
        try: p_g1 = np.asarray(self.rb.kin.fk("left", q))[:3, 3]
        except Exception: return 0.0
        e = float(np.linalg.norm(p_g1 - geom.fk_chain_side(q, "left", ee=0.15)[5][:3, 3]))
        if e > 0.005: raise SkillFailed("%s: geom and g1-fetch FK disagree by %.1f mm at q %s" % (label, e * 1000, np.round(q, 2).tolist()))
        return e

    def set(self, q, label=""):
        """One streamed target with the displacement cap (the commanded palm may not jump more than max_step per target)."""
        self.check_abort(); q = np.asarray(q, float)
        jump = float(np.linalg.norm(self.palm(q) - self.palm_cmd()))
        if jump > self.max_step: raise SkillFailed("%s: a single target would move the palm %.1f cm" % (label, jump * 100))
        self.rb.arms.set_target("left", q)
        if self.trace: self.trace(label)

    def path(self, start, end, psi, n, step, psi_from=None):
        """The joint targets of the straight line start -> end in pieces of at most `step` metres, each solved from the previous one,
        the forearm yaw blended from psi_from to psi (numeric psi): computed BEFORE any motion, so a line that fails anywhere (IK, joint
        margin) is refused with the arm still. Returns [(q, pitch)]."""
        start, end = np.asarray(start, float), np.asarray(end, float)
        k = max(1, int(math.ceil(float(np.linalg.norm(end - start)) / max(1e-4, min(step, self.sub_step))))); q_prev = self.q_cmd(); out = []
        for i in range(1, k + 1):
            a = i / k; psi_i = psi if (psi in (None, "free") or psi_from is None) else psi_from + (psi - psi_from) * a
            q, err, pitch = self.solve(start + (end - start) * a, psi_i, n, q_seed=q_prev); out.append((q, pitch)); q_prev = q
        return out

    def stream(self, start, end, psi, n, label, step, psi_from=None):
        """Stream the COMMANDED palm along the straight line start -> end (the whole path solved first), one target per step_s; every
        target passes the per-target cap. Returns the last (q, pitch)."""
        qs = self.path(start, end, psi, n, step, psi_from)
        for q, _ in qs: self.set(q, label); time.sleep(self.step_s)
        return qs[-1]

    # --- moves -------------------------------------------------------------------------------------------------------------------------
    def replay(self, qs, label):
        """Stream given joint targets (a recorded path, reversed), one per step_s, each through the per-target cap."""
        for q in qs: self.set(np.asarray(q, float), label); time.sleep(self.step_s)

    def goto(self, p_goal, speed=0.08, label="", psi=None, n=None, correct=2, settle=0.4, ff=False, validate=None):
        """Move the palm to p_goal: the COMMANDED palm streams along a straight line (to p_goal + the current sag when ff), then up to
        `correct` correction rounds, each streaming the command by the measured error in capped sub-steps, until the MEASURED palm is
        within corr_tol. Returns the measured palm. Logs a `move` event with the arrival error (before corrections) and the final one."""
        p_goal = np.asarray(p_goal, float); psi = self.psi if psi is None else psi; n = self.n if n is None else n
        psi0 = None if psi == "free" else geom.forearm_yaw_pitch(geom.arm_segments(self.q_cmd())["d"])[0]   # blend the yaw from where the forearm points now
        step = speed * self.speed_scale * self.step_s; sag0 = self.sag() if ff else np.zeros(3)
        try: qs = self.path(self.palm_cmd(), p_goal + sag0, psi, n, step, psi0)
        except SkillFailed:
            if not ff: raise
            sag0 = np.zeros(3); qs = self.path(self.palm_cmd(), p_goal, psi, n, step, psi0)   # near the reach limit: no feed-forward, the corrections close the gap
        pitch = qs[-1][1]; self.cross_check(qs[-1][0], label)
        if validate: validate([q for q, _ in qs], label)                # e.g. the table keep-out, before any motion
        self.last_path = [self.q_cmd()] + [q for q, _ in qs]
        for q, _ in qs: self.set(q, label); time.sleep(self.step_s)
        try: self.rb.arms.wait_settled("left", tol=0.08, timeout=2.0)
        except Exception: pass
        time.sleep(settle); arrival = float(np.linalg.norm(p_goal - self.palm_meas())); rounds = 0
        while rounds < correct:
            e = p_goal - self.palm_meas()
            if np.linalg.norm(e) < self.corr_tol: break
            c0 = self.palm_cmd(); self.stream(c0, c0 + e, psi, n, label + "-corr", self.corr_speed * self.speed_scale * self.step_s)
            time.sleep(0.5); rounds += 1
        m = self.palm_meas(); e = float(np.linalg.norm(p_goal - m))
        self.last = {"label": label, "goal": p_goal, "measured": m, "err": e, "arrival": arrival, "rounds": rounds, "sag_ff": sag0, "q_cmd": self.q_cmd(), "q_meas": self.q_meas(), "psi": psi, "pitch": pitch}
        if self.log: self.log(ev="move", label=label, goal=np.round(p_goal, 3).tolist(), measured=np.round(m, 3).tolist(), err=round(e, 4), arrival=round(arrival, 4), rounds=rounds,
                              sag_ff=np.round(sag0, 3).tolist(), psi=psi if psi == "free" else float(psi), pitch=round(float(pitch), 1), q_cmd=np.round(self.q_cmd(), 3).tolist(), q_meas=np.round(self.q_meas(), 3).tolist(), tag="scripted skill")
        print("  %s: goal %s measured %s err %.3f (arrival %.3f, %d correction rounds%s; psi %s, pitch %.1f)" % (label, np.round(p_goal, 3).tolist(), np.round(m, 3).tolist(), e, arrival, rounds,
              ", sag fed forward %.3f" % float(np.linalg.norm(sag0)) if ff else "", psi, pitch), flush=True)
        return m

    def nudge(self, delta, label="nudge", settle=0.6):
        """Relative move of the MEASURED palm by delta (a servo correction): the sag is fed forward, so the command moves by delta."""
        return self.goto(self.palm_meas() + np.asarray(delta, float), speed=0.04, label=label, correct=2, settle=settle, ff=True)

    def step_along(self, direction, dist, label="step", settle=0.25, target=None, tol=0.003, sag_ref=None):
        """One approach step: the measured palm should reach `target` (default: dist along direction from where it is; a caller on a line
        passes the absolute point so the residuals do not accumulate); the command carries the current sag so the measured hand lands there
        (V2_STRATEGY: re-apply the measured correction every step), then one correction above `tol`, unless the hand followed less than
        half the step (blocked: no harder push; the caller's lag check decides). With sag_ref (the sag at rest before the approach), a
        "sag" more than 1 cm away from it is contact, not gravity: it is not fed forward. Returns (measured palm, tracking error)."""
        direction = np.asarray(direction, float); before = self.palm_meas(); sag = self.sag()
        if sag_ref is not None and float(np.linalg.norm(sag - np.asarray(sag_ref))) > 0.01: sag = np.asarray(sag_ref, float)
        target = before + direction * dist if target is None else np.asarray(target, float); cmd = target + sag
        self.stream(self.palm_cmd(), cmd, None, None, label, self.sub_step); time.sleep(settle)
        e = target - self.palm_meas(); want = float((target - before) @ direction)
        if np.linalg.norm(e) > tol and float((self.palm_meas() - before) @ direction) > 0.5 * want:
            c0 = self.palm_cmd(); self.stream(c0, c0 + e, None, None, label + "-corr", self.sub_step); time.sleep(0.2)
        return self.palm_meas(), self.tracking()
