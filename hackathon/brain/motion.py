"""Motion layer for brain v2: every left-arm move is planned on geom.py's real-palm model (URDF chain, palm 0.246 m along the wrist
roll axis, 4-joint IK with the forearm yaw held, wrist roll from the palm normal) and streamed to g1-fetch's arm streamer as joint
targets. The arm sags under gravity: on Tuesday the measured palm sat 1.9-2.6 cm below the command at the raise and 2.5-4.7 cm at the
high waypoint. So (1) a move can feed the current sag forward (command = goal + the sag measured at rest before the move), which keeps
the measured palm on the line when lowering toward the table; (2) the remaining error is corrected by streaming the command in capped
sub-steps until the MEASURED palm is within 6 mm, and a round the hand did not follow ends the rounds (contact: no harder push);
(3) an approach step carries the sag and gets one correction unless the hand did not follow (the caller's lag check decides).
Safety per streamed target (Arm.set): the palm may not jump more than max_step (refused before it is sent), and no joint may change by
more than joint_step x speed_scale (the target is split into joint-interpolated sub-targets, one per step_s; g1-fetch's streamer clips
at max_joint_vel 1.2 rad/s = 0.024 rad per 20 ms tick, so the brain's own cap keeps the streamed command equal to the target). A path's
wrist roll is blended from where it is to the planned roll over the path (V2_REVIEW round 2 blocker 1: no snap at its first target).
Every target sent is appended to the open `trail` (the raise is retraced from wherever it stopped, blocker 2). Near the table every goal
and every command is floored so the open hand's LOWEST point (the palm box and the fingertips through the measured pitch and roll,
geom.hand_lowest) stays at table_floor = table + margin or above (round 2 blocker 4, round 3); a downward correction is never streamed
while the hand rests above its goal there (contact). Also IK error <= tol, joint-limit margin, a cross-check of each goal against
g1-fetch's pinocchio FK. Also used by mock_robot (the same code path)."""
import math, time
import numpy as np
import geom


class SkillFailed(RuntimeError): pass


class Arm:
    def __init__(self, rb, cfg, log=None, tol=None, step_s=0.02, max_step=0.02, sub_step=0.01, corr_tol=0.006, corr_speed=0.04,
                 speed_scale=1.0, roll_inward=0.0, check_abort=None, kin_check=True, joint_step=0.02, step_speed=0.05, contact_lag=0.006,
                 rest_tol=0.015):
        self.rb, self.cfg, self.log, self.step_s, self.max_step, self.roll_inward = rb, cfg, log, step_s, max_step, roll_inward
        self.tol = geom.IK_TOL if tol is None else tol
        self.sub_step, self.corr_tol, self.corr_speed, self.speed_scale = sub_step, corr_tol, corr_speed, speed_scale
        self.rest_tol = rest_tol                                           # the hand this far above the stop 2 cm over a goal near the table = resting on something
        self.joint_step, self.step_speed = joint_step, step_speed       # rad per target at speed 1; approach-step speed (m/s at speed 1)
        self.contact_lag = contact_lag                                     # near the table floor: the hand this far behind the commanded advance = contact
        self.check_abort = check_abort or (lambda: None); self.kin_check = kin_check; self.psi = 0.0; self.n = np.array([0.0, -1.0, 0.0]); self.last = {}
        self.trace = None                                                  # optional callback(label) after each streamed target (tests)
        self.last_path = []                                                # the joint targets of the last goto
        self.trail = None                                                  # open: every target sent is appended (the raise, as it streams)
        self.table_floor = None                                            # the lowest allowed point of the open hand (table + margin) while a table is known
        self.sent = 0                                                      # targets streamed (logged)
        self.lag_max = None                                                # the largest follow lag of the last line near the table floor

    # --- model -------------------------------------------------------------------------------------------------------------------------
    def palm(self, q): return geom.fk_chain_side(np.asarray(q, float))[5][:3, 3]
    def q_cmd(self): return np.asarray(self.rb.arms.cmd["left"], float).copy()
    def q_meas(self): return np.asarray(self.rb.arms.measured("left"), float).copy()
    def palm_cmd(self): return self.palm(self.q_cmd())
    def palm_meas(self): return self.palm(self.q_meas())
    def sag(self): return self.palm_cmd() - self.palm_meas()        # where the command sits relative to the measured hand (the sag)
    def tracking(self): return float(self.rb.arms.tracking_error("left"))
    def joint_cap(self): return self.joint_step * self.speed_scale

    def yaw_now(self): return float(geom.forearm_yaw_pitch(geom.arm_segments(self.q_cmd())["d"])[0])

    def open_trail(self): self.trail = [self.q_cmd()]
    def close_trail(self):
        t, self.trail = self.trail, None
        return t or []

    def drop_at(self, q):
        low, pz = geom.hand_lowest(q); return max(pz - low, geom.PALM_HALF_HEIGHT)

    def hand_drop(self, p=None, psi=None, n=None, command=False):
        """How far the open hand reaches below the palm centre (pitch, roll, fingers), at least the palm half-height: now (the measured
        joints) or, for a target p, on arrival there: the joints that command it (p + the sag now, as the feed-forward commands a goal;
        p itself for a command point) with the current sag deflection applied. Mock: within 0.5 mm of the drop on arrival at five
        pre-grasps, where the drop measured at high was up to 1 cm off (the forearm pitches -16 deg at high, +5 to -10 at the pre-grasp)."""
        q_now = self.q_meas()
        if p is None: return self.drop_at(q_now)
        try: q, _, _ = self.solve(np.asarray(p, float) + (np.zeros(3) if command else self.sag()), psi, n); return self.drop_at(q + (q_now - self.q_cmd()))
        except SkillFailed: return self.drop_at(q_now)

    def palm_floor(self, p=None, psi=None, n=None, command=False):
        """The lowest palm z for a target: the table floor + the hand's drop on arrival (+ the sag for a command: it sits a sag above its hand)."""
        if self.table_floor is None: return None
        return self.table_floor + self.hand_drop(p, psi, n, command) + (max(0.0, float(self.sag()[2])) if command else 0.0)

    def floored(self, p, what="", psi=None, n=None, command=False):
        """p with its z raised so the open hand's lowest point on arrival stays at the table floor; printed when it binds."""
        p = np.asarray(p, float); f = self.palm_floor(p, psi, n, command)
        if f is None or p[2] >= f: return p
        print("  %s: z %.3f raised to the table floor %.3f (hand %.3f below the palm)" % (what, p[2], f, f - self.table_floor), flush=True)
        return np.array([p[0], p[1], f])

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
        """One target: refused when the commanded palm would jump more than max_step; a joint change above joint_step x speed_scale is
        split into joint-interpolated sub-targets, one per step_s (the caller sleeps after the last). Each sent target joins the trail."""
        self.check_abort(); q = np.asarray(q, float); q0 = self.q_cmd()
        jump = float(np.linalg.norm(self.palm(q) - self.palm(q0)))
        if jump > self.max_step: raise SkillFailed("%s: a single target would move the palm %.1f cm" % (label, jump * 100))
        k = max(1, int(math.ceil(float(np.max(np.abs(q - q0))) / self.joint_cap() - 1e-9)))
        for i in range(1, k + 1):
            qi = q0 + (q - q0) * (i / k)
            if i > 1: time.sleep(self.step_s); self.check_abort()
            self.rb.arms.set_target("left", qi); self.sent += 1
            if self.trail is not None: self.trail.append(qi.copy())
            if self.trace: self.trace(label)

    def path(self, start, end, psi, n, step, psi_from=None, q_start=None):
        """The joint targets of the straight line start -> end in pieces of at most `step` metres, each solved from the previous one,
        the forearm yaw blended from psi_from to psi (numeric psi) and the wrist roll from q_start's to the planned one: computed BEFORE
        any motion, so a line that fails anywhere (IK, joint margin) is refused with the arm still. Returns [(q, pitch)]."""
        start, end = np.asarray(start, float), np.asarray(end, float)
        k = max(1, int(math.ceil(float(np.linalg.norm(end - start)) / max(1e-4, min(step, self.sub_step)))))
        q_prev = self.q_cmd() if q_start is None else np.asarray(q_start, float).copy(); roll0 = float(q_prev[4]); out = []
        for i in range(1, k + 1):
            a = i / k; psi_i = psi if (psi in (None, "free") or psi_from is None) else psi_from + (psi - psi_from) * a
            q, err, pitch = self.solve(start + (end - start) * a, psi_i, n, q_seed=q_prev)
            q[4] = roll0 + (float(q[4]) - roll0) * a                         # the roll blended along the path (V2_REVIEW round 2 blocker 1)
            out.append((q, pitch)); q_prev = q
        return out

    def stream(self, start, end, psi, n, label, step, psi_from=None):
        """Stream the COMMANDED palm along the straight line start -> end (the whole path solved first), one target per step_s; every
        target passes the per-target caps. Returns the last (q, pitch)."""
        qs = self.path(start, end, psi, n, step, psi_from)
        for q, _ in qs: self.set(q, label); time.sleep(self.step_s)
        return qs[-1]

    # --- moves -------------------------------------------------------------------------------------------------------------------------
    def replay(self, qs, label):
        """Stream given joint targets (a recorded path, reversed), one per step_s, each through the per-target caps."""
        for q in qs: self.set(np.asarray(q, float), label); time.sleep(self.step_s)

    def line(self, p_goal, speed, label, psi, n, ff, validate=None, sag_cap=None, watch=None):
        """One planned straight line of the commanded palm to p_goal (+ the sag measured now when ff; with sag_cap, a sag more than 1 cm
        from it is not fed forward), solved and validated before it streams; `watch()` after every target may stop it (a reason string).
        Returns (sag fed forward, pitch at the end, the reason it stopped or "")."""
        psi0 = None if psi == "free" else geom.forearm_yaw_pitch(geom.arm_segments(self.q_cmd())["d"])[0]   # blend the yaw from where the forearm points now
        step = speed * self.speed_scale * self.step_s; sag0 = self.sag() if ff else np.zeros(3)
        if ff and sag_cap is not None and float(np.linalg.norm(sag0 - np.asarray(sag_cap))) > 0.01: sag0 = np.asarray(sag_cap, float)
        try: qs = self.path(self.palm_cmd(), self.floored(p_goal + sag0, label + " command", psi, n, command=True), psi, n, step, psi0)
        except SkillFailed:
            if not ff or self.table_floor is not None: raise                 # near the table no fallback: without the sag fed forward the hand lands a full sag (4-5 cm) low
            sag0 = np.zeros(3); qs = self.path(self.palm_cmd(), p_goal, psi, n, step, psi0)   # near the reach limit: no feed-forward, the corrections close the gap
        self.cross_check(qs[-1][0], label)
        if validate: validate([q for q, _ in qs], label)                # e.g. the table keep-out, before any motion
        self.last_path = [self.q_cmd()] + [q for q, _ in qs]
        for q, pitch in qs:
            self.set(q, label); time.sleep(self.step_s)
            why = watch() if watch else ""
            if why: return sag0, pitch, why
        return sag0, qs[-1][1], ""

    def follow_watch(self, label):
        """A per-target contact check for a line near the table floor: the measured palm's advance along the commanded advance; more than
        contact_lag behind (beyond the lag at the line's start) is contact, and the line stops there, before it streams the rest into the
        table (V2_REVIEW round 4). The largest lag is kept in self.lag_max (printed: the air test's floor-bound run measures the real one)."""
        c0, m0 = self.palm_cmd(), self.palm_meas(); self.lag_max = 0.0
        def watch():
            dc = self.palm_cmd() - c0; L = float(np.linalg.norm(dc))
            if L < 1e-4: return ""
            lag = L - float((self.palm_meas() - m0) @ (dc / L)); self.lag_max = max(self.lag_max, lag)
            return "the hand stopped following %.3f behind the commanded advance on the final line (contact?)" % lag if lag > self.contact_lag else ""
        return watch

    def goto(self, p_goal, speed=0.08, label="", psi=None, n=None, correct=2, settle=0.4, ff=False, validate=None, above=0.02, sag_max=None):
        """Move the palm to p_goal (floored near the table): the COMMANDED palm streams along a straight line (to p_goal + the current
        sag when ff), then up to `correct` correction rounds, each streaming the command by the measured error in capped sub-steps, until
        the MEASURED palm is within corr_tol. Near the table (ff, a goal within `above` of the floor) the line stops `above` higher first
        and the last part carries the sag measured there: the sag grows with the reach, so one long line dips mid-path (4.5-6.4 mm for a
        3 cm servo nudge, V2_REVIEW round 2). A round the hand did not follow (moved under half the commanded change) or that did not
        shrink the error ends the rounds: last['blocked'] (contact; the caller decides). Returns the measured palm. Logs a `move` event."""
        psi = self.psi if psi is None else psi; n = self.n if n is None else n; p_goal = self.floored(p_goal, label + " goal", psi, n); blocked = ""
        pf = self.palm_floor(); sag_hi = self.sag()
        pf_goal = self.palm_floor(p_goal, psi, n); goal_near = pf_goal is not None and p_goal[2] < pf_goal + 2 * above   # a goal near the table floor
        self.lag_max = None
        if ff and pf is not None and p_goal[2] < pf + above and self.palm_meas()[2] > p_goal[2] + above * 0.5:
            stop = p_goal + np.array([0.0, 0.0, above])
            self.line(stop, speed, label + "-above", psi, n, True, validate)
            try: self.rb.arms.wait_settled("left", tol=0.08, timeout=2.0)
            except Exception: pass
            time.sleep(settle); held = float(self.palm_meas()[2] - stop[2])
            if held > self.rest_tol: blocked = "the hand rests %.3f above its stop 2 cm over the goal (contact?)" % held   # something under it: no lowering onto it
            elif held > self.corr_tol: print("  %s: the hand settled %.3f above its stop (the sag fed forward from high is larger than here; the final line carries the sag measured here)" % (label, held), flush=True)
        if not blocked:
            sag_cap = sag_hi if sag_max is None else sag_max                  # a "sag" grown by more than 1 cm since high is the hand resting on something
            sag0, pitch, why = self.line(p_goal, speed, label, psi, n, ff, validate, sag_cap=sag_cap if ff else None, watch=self.follow_watch(label) if goal_near else None)
            if why: blocked = why
            try: self.rb.arms.wait_settled("left", tol=0.08, timeout=2.0)
            except Exception: pass
            time.sleep(settle)
            if goal_near: print("  %s: final line near the table floor: largest lag behind the command %.3f m (contact at %.3f)" % (label, self.lag_max or 0.0, self.contact_lag), flush=True)
        else: sag0, pitch = np.zeros(3), float(geom.forearm_yaw_pitch(geom.arm_segments(self.q_cmd())["d"])[1])
        arrival = float(np.linalg.norm(p_goal - self.palm_meas())); rounds = 0; e_prev = None
        while rounds < correct and not blocked:
            m0 = self.palm_meas(); e = p_goal - m0; en = float(np.linalg.norm(e))
            if en < self.corr_tol: break
            if e_prev is not None and en > e_prev - 0.001: blocked = "the error did not shrink (%.3f after %.3f)" % (en, e_prev); break
            if e[2] < -self.corr_tol and goal_near:                           # the hand rests above its goal near the table: contact, never pushed into
                blocked = "the hand rests %.3f above its goal near the table (contact?)" % -e[2]; break
            c0 = self.palm_cmd(); c1 = self.floored(c0 + e, label + "-corr command", psi, n, command=True); dc = float(np.linalg.norm(c1 - c0))
            if dc < 1e-4: blocked = "the table floor stops the correction"; break
            self.stream(c0, c1, psi, n, label + "-corr", self.corr_speed * self.speed_scale * self.step_s)
            time.sleep(0.5); rounds += 1; e_prev = en
            dm = self.palm_meas() - m0; moved = float(dm @ (c1 - c0)) / dc; dz = float((c1 - c0)[2])
            if moved < 0.5 * dc: blocked = "the hand followed %.3f of a %.3f correction" % (moved, dc); break
            if goal_near and abs(dz) > 0.003 and float(dm[2]) / dz < 0.5: blocked = "the hand followed %.3f of a %.3f vertical correction near the table" % (float(dm[2]), dz); break
        if blocked: print("  %s: stopped: %s (contact: no harder push)" % (label, blocked), flush=True)
        return self.report(p_goal, label, psi, pitch, arrival, rounds, blocked, sag0, ff)

    def report(self, p_goal, label, psi, pitch, arrival, rounds=0, blocked="", sag0=None, ff=False):
        """The end of a move: self.last, a `move` event and the console line (goal, measured, error, arrival, rounds, psi, pitch)."""
        sag0 = np.zeros(3) if sag0 is None else sag0; m = self.palm_meas(); e = float(np.linalg.norm(p_goal - m))
        self.last = {"label": label, "goal": p_goal, "measured": m, "err": e, "arrival": arrival, "rounds": rounds, "sag_ff": sag0, "q_cmd": self.q_cmd(), "q_meas": self.q_meas(), "psi": psi, "pitch": pitch, "blocked": blocked}
        if self.log: self.log(ev="move", label=label, goal=np.round(p_goal, 3).tolist(), measured=np.round(m, 3).tolist(), err=round(e, 4), arrival=round(arrival, 4), rounds=rounds, blocked=blocked,
                              sag_ff=np.round(sag0, 3).tolist(), psi=psi if psi == "free" else float(psi), pitch=round(float(pitch), 1), q_cmd=np.round(self.q_cmd(), 3).tolist(), q_meas=np.round(self.q_meas(), 3).tolist(),
                              lag_max=None if self.lag_max is None else round(self.lag_max, 4), tag="scripted skill")
        print("  %s: goal %s measured %s err %.3f (arrival %.3f, %d correction rounds%s; psi %s, pitch %.1f)" % (label, np.round(p_goal, 3).tolist(), np.round(m, 3).tolist(), e, arrival, rounds,
              ", sag fed forward %.3f" % float(np.linalg.norm(sag0)) if ff else "", psi, pitch), flush=True)
        return m

    def run_path(self, qs, p_goal, label, settle=0.4):
        """Stream joint targets solved beforehand (the raise: both of its lines solved and keep-out checked before anything moves), then
        report like goto with no correction."""
        self.lag_max = None; self.cross_check(qs[-1], label); self.last_path = [self.q_cmd()] + list(qs)
        for q in qs: self.set(q, label); time.sleep(self.step_s)
        try: self.rb.arms.wait_settled("left", tol=0.08, timeout=2.0)
        except Exception: pass
        time.sleep(settle)
        return self.report(np.asarray(p_goal, float), label, "free", geom.forearm_yaw_pitch(geom.arm_segments(self.q_cmd())["d"])[1], float(np.linalg.norm(np.asarray(p_goal) - self.palm_meas())))

    def nudge(self, delta, label="nudge", settle=0.6):
        """Relative move of the MEASURED palm by delta (a servo correction): the sag is fed forward, so the command moves by delta."""
        return self.goto(self.palm_meas() + np.asarray(delta, float), speed=0.04, label=label, correct=2, settle=settle, ff=True)

    def step_along(self, direction, dist, label="step", settle=0.25, target=None, tol=0.003, sag_ref=None):
        """One approach step: the measured palm should reach `target` (default: dist along direction from where it is; a caller on a line
        passes the absolute point so the residuals do not accumulate); the command carries the current sag so the measured hand lands there
        (V2_STRATEGY: re-apply the measured correction every step), streamed at step_speed x speed_scale; then one correction above `tol`,
        unless the hand followed less than half the step (blocked: no harder push; the caller's lag check decides). With sag_ref (the sag
        at rest before the approach), a "sag" more than 1 cm away from it is contact, not gravity: it is not fed forward. Target and
        command are floored near the table. Returns (measured palm, tracking error)."""
        direction = np.asarray(direction, float); before = self.palm_meas(); sag = self.sag()
        if sag_ref is not None and float(np.linalg.norm(sag - np.asarray(sag_ref))) > 0.01: sag = np.asarray(sag_ref, float)
        target = self.floored(before + direction * dist if target is None else target, label + " target"); cmd = self.floored(target + sag, label + " command", command=True)
        step = self.step_speed * self.speed_scale * self.step_s
        self.stream(self.palm_cmd(), cmd, None, None, label, step); time.sleep(settle)
        e = target - self.palm_meas(); want = float((target - before) @ direction)
        if np.linalg.norm(e) > tol and float((self.palm_meas() - before) @ direction) > 0.5 * want:
            c0 = self.palm_cmd(); self.stream(c0, self.floored(c0 + e, label + "-corr command", command=True), None, None, label + "-corr", self.corr_speed * self.speed_scale * self.step_s); time.sleep(0.2)
        return self.palm_meas(), self.tracking()
