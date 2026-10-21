"""Motion layer for brain v2: every left-arm move is planned on geom.py's real-palm model (URDF chain, palm 0.246 m along the wrist
roll axis, 4-joint IK with the forearm yaw held, wrist roll from the palm normal) and streamed to g1-fetch's arm streamer as joint
targets; after every move, and after every approach step, the MEASURED palm (the same model on the measured joints) is corrected
toward the goal, so the arm's sag never accumulates. Safety: IK error <= tol per step, joint-limit margin, a per-step displacement
cap, a cross-check of each waypoint against g1-fetch's pinocchio FK, and the tracking-error / lag aborts (safety only).
Also used by mock_robot (same code path)."""
import math, time
import numpy as np
import geom


class SkillFailed(RuntimeError): pass


class Arm:
    def __init__(self, rb, cfg, log=None, tol=geom.IK_TOL, step_s=0.02, max_step=0.02, roll_inward=0.0, check_abort=None, kin_check=True):
        self.rb, self.cfg, self.log, self.tol, self.step_s, self.max_step, self.roll_inward = rb, cfg, log, tol, step_s, max_step, roll_inward
        self.check_abort = check_abort or (lambda: None); self.kin_check = kin_check; self.psi = 0.0; self.n = np.array([0.0, -1.0, 0.0]); self.last = {}

    # --- model -------------------------------------------------------------------------------------------------------------------------
    def palm(self, q): return geom.fk_chain_side(np.asarray(q, float))[5][:3, 3]
    def q_cmd(self): return np.asarray(self.rb.arms.cmd["left"], float).copy()
    def q_meas(self): return np.asarray(self.rb.arms.measured("left"), float).copy()
    def palm_cmd(self): return self.palm(self.q_cmd())
    def palm_meas(self): return self.palm(self.q_meas())
    def sag(self): return self.palm_cmd() - self.palm_meas()        # where the command sits relative to the measured hand (the sag)

    def solve(self, p, psi=None, n=None, q_seed=None):
        """q5 for the real palm at p with the forearm yaw psi ("free" = position only, for the raise) and the palm normal n.
        Raises SkillFailed beyond tol or the limit margin."""
        psi = self.psi if psi is None else psi; n = self.n if n is None else n; seed = self.q_cmd() if q_seed is None else q_seed
        q, err, pitch, d = geom.ik4(p, None if psi == "free" else psi, seed)
        if err > self.tol: raise SkillFailed("IK error %.1f mm for the palm at %s (psi %s)" % (err * 1000, np.round(p, 3).tolist(), psi))
        q[4] = geom.wrist_roll_for_palm(q, n, self.roll_inward)
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
        """One streamed target with the displacement cap (the palm may not jump more than max_step per target)."""
        self.check_abort(); q = np.asarray(q, float)
        jump = float(np.linalg.norm(self.palm(q) - self.palm_cmd()))
        if jump > self.max_step: raise SkillFailed("%s: a single target would move the palm %.1f cm" % (label, jump * 100))
        self.rb.arms.set_target("left", q)

    # --- moves -------------------------------------------------------------------------------------------------------------------------
    def goto(self, p_goal, speed=0.08, label="", psi=None, n=None, correct=2, settle=0.4):
        """Straight line of the COMMANDED palm to p_goal (streamed IK, step_s), then up to `correct` corrections so the MEASURED palm
        reaches p_goal. Returns the measured palm. Logs a `move` event."""
        p_goal = np.asarray(p_goal, float); psi = self.psi if psi is None else psi; n = self.n if n is None else n
        q_goal, err_goal, pitch = self.solve(p_goal, psi, n); self.cross_check(q_goal, label)
        start = self.palm_cmd(); dist = float(np.linalg.norm(p_goal - start)); steps = max(1, int(math.ceil(dist / (speed * self.step_s))))
        q_prev = self.q_cmd(); psi0 = geom.forearm_yaw_pitch(geom.arm_segments(q_prev)["d"])[0]      # blend the yaw from where the forearm points now
        for i in range(1, steps + 1):
            a = i / steps; p = start + (p_goal - start) * a; psi_i = psi if psi == "free" else psi0 + (psi - psi0) * a
            q, err, _ = self.solve(p, psi_i, n, q_seed=q_prev)
            self.set(q, label); q_prev = q; time.sleep(self.step_s)
        try: self.rb.arms.wait_settled("left", tol=0.08, timeout=2.0)
        except Exception: pass
        time.sleep(settle); cmd = p_goal.copy()
        for _ in range(correct):
            e = p_goal - self.palm_meas()
            if np.linalg.norm(e) < 0.006: break
            cmd = cmd + e; q, err, _ = self.solve(cmd, psi, n, q_seed=self.q_cmd()); self.set(q, label + "-corr"); time.sleep(0.5)
        m = self.palm_meas(); e = float(np.linalg.norm(p_goal - m))
        self.last = {"label": label, "goal": p_goal, "measured": m, "err": e, "q_cmd": self.q_cmd(), "q_meas": self.q_meas(), "psi": psi, "pitch": pitch}
        if self.log: self.log(ev="move", label=label, goal=np.round(p_goal, 3).tolist(), measured=np.round(m, 3).tolist(), err=round(e, 4), psi=psi if psi == "free" else float(psi), pitch=round(float(pitch), 1), q_cmd=np.round(self.q_cmd(), 3).tolist(), q_meas=np.round(self.q_meas(), 3).tolist(), tag="scripted skill")
        print("  %s: goal %s measured %s err %.3f (psi %s, pitch %.1f)" % (label, np.round(p_goal, 3).tolist(), np.round(m, 3).tolist(), e, psi, pitch), flush=True)
        return m

    def nudge(self, delta, label="nudge", settle=0.6):
        """Relative move of the MEASURED palm by delta (the servo's correction)."""
        return self.goto(self.palm_meas() + np.asarray(delta, float), speed=0.04, label=label, correct=2, settle=settle)

    def step_along(self, direction, dist, label="step", settle=0.25):
        """One approach step: the measured palm should move by dist along direction; the command carries the current sag so the
        measured hand lands there (V2_STRATEGY: re-apply the measured correction every step). Returns (measured palm, tracking error)."""
        direction = np.asarray(direction, float); target = self.palm_meas() + direction * dist
        cmd = target + self.sag(); q, err, _ = self.solve(cmd); self.set(q, label); time.sleep(settle)
        e = target - self.palm_meas()
        if np.linalg.norm(e) > 0.006:
            q, err, _ = self.solve(cmd + e); self.set(q, label + "-corr"); time.sleep(0.2)
        return self.palm_meas(), float(self.rb.arms.tracking_error("left"))

    def tracking(self): return float(self.rb.arms.tracking_error("left"))
