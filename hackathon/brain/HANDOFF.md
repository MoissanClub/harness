# Handoff: brain v2 after V2_REVIEW round 3 (2026-10-21)

What the build session leaves for the robot session. Nothing here has run on the robot; what cannot be checked offline is named below
with the reason and the no-motion check or observation that covers it.

## Commit

- Code: `13bff01` on `hackathon` (round 3), NOT pushed (the coordinator's rule for this session); push before the session so PC2 can
  `git pull`. Later commits change documents only. In `hackathon/brain`:
  `git diff --quiet 13bff01 HEAD -- '*.py' calib.json ../../bench/client.py && echo CODE 13bff01` must print `CODE 13bff01`.
- `calib.json` sha16: `ae553548d47b677a` (`python calib.py | head -1`), 36 entries (round 3 added `raise_back_m` 0.02, `hand_back_m` 0.045,
  `hand_half_thickness_m` 0.02, the last two assumed), none stale. Every run-plan command carries `--expect-calib ae553548d47b677a`; without it
  the brain refuses on the robot, and it refuses another sha, a dirty tree (the brain folder and `bench/client.py`) or a tree that is not
  a git clone. On the Mac the line shows `(dirty)` only because the coordinator's untracked `V2_REVIEW*` files sit in the brain folder.

## Round 3: what was fixed, and the gate case that shows it

Scope: the items of `V2_REVIEW_round3.json` marked in_this_plan. Each gate case runs a path other than the one fixed and fails on 8e226e9
with the same mock (`CHECK_TREE=<8e226e9 tree> python check.py --cases ...`). "new / 8e226e9" below.

| Item | Fix | Gate case: new / 8e226e9 |
| --- | --- | --- |
| 1. The kill test cannot start after a release (plan blocker) | `table_top()` uses the taped table height (`--table-z`, alias `--air-table`) in every mode before a plane is fitted; the home region is judged on the palm and the fingertips (home_q's own wrist is at z +0.026); the start pose is printed and logged; after enable, a streamer holding a pose more than 0.1 rad from the measured one is released at once; the mock's enable now takes the measured pose, as g1-fetch's does | `released`: the kill probe starting from a pose 0.06-0.14 rad off home_q: accepted, probe / "park refused", no order |
| 2. The 30 cm hand test contradicts the zone (plan blocker) | the plan tests 10 and 20 cm from the chest at belly height and expects clear at 30 cm, and states the zone (pelvis x < 0.30, 17-22 cm from the chest, z 0.99-1.34 m above the floor); the 0.30 m rule also refuses one blind region over 8% of the frame with the arm at home (`--blind-max`; something inside the D435i's minimum range) | `nearhand` (a hand-sized box 10 cm from the chest inside a 0.28 m minimum range, `--dry`): refused, "one region of 17% ... no depth" / clear (83% valid) |
| 3. Stuck exits | q / Ctrl-C while stuck only ask to quit once the arm is home (no flag aborts a confirmed way out); a freeze is set only while a retreat moves and is cleared at y; a second q before the first was acted on holds the arm; `run_retreat` turns any exception into stuck; the shutdown waits in stuck until the arm is home or `quit!` and never exits or moves by itself with the arm out; `quit!` (and `quit` while stuck) exits without moving or releasing anything; unknown lines get a key list; latches cleared at every state change; Ctrl-C stays live through the shutdown | `qstuck` (stuck in idle, q, h, y): home, released at home, then the quit / ended 0.44 m from home. `wayfail` (a g1-fetch failure in the confirmed way out, idle loop): 0 targets before the next way out / 316 (homed with no confirmation). `wayfail1` (the same from the shutdown loop): home / ended 0.44 m out. `secondq` (two q at once while lowering): 1 target, holds / 405 targets, homed |
| 4. Table push | the floor is on the open hand's lowest point (the palm box and the fingertips, `geom.hand_lowest`) through the orientation predicted on arrival (the command's joints plus the current sag deflection: within 0.5 mm in the mock, where the drop measured at high was up to 1 cm off); a downward correction is never streamed while the hand rests more than 6 mm above a goal near the floor (contact), the stop 2 cm above the goal checks the same and bounds the fed-forward sag, following is judged vertically near the floor; the kill test runs with `--floor-margin 0.02` (the hand's lowest point 2 cm above the fitted table: no correction runs near the table; K_z includes the printed raise); `--palm-half-height` and `--fingertip` carry the tape; the mock's contact uses the hand box | `killtable` (the kill probe at the purple can's slot, plane 2 cm low, hand 1 cm low): push 3.4 mm / 26 mm. `servoblock` (`--probe-servo --pre-offset 0.025`): no table contact, the correction announced / 50 contacts, refused on contact. `test_motion` (plane 5/10/20 mm low, hand 0/1 cm low, 2 cm margin): push under 10 mm / 21 mm; the hand's lowest point above the table at every target for both cans and a servo nudge / 6.7 mm under |
| 5. Fingertip reach | the raise goes up first 2 cm behind the hip to the table top + 3 cm (`raise_back_m`), then to the raise waypoint, both from home_q's palm; with a 12.5 cm hand the keep-out reach drops from 0.351 to 0.304-0.307 at all plan targets (joint margins 6-11 degrees, clearances 5.6 cm or more); the plan tapes F and checks E against the printed reach | `reach` (air (0.35, 0.00), half speed): under the table top the commanded 12.5 cm hand reaches x 0.308 / 0.338 (limit 0.32 with E 0.34) |
| 6. One obstacle check per order | `clear_or_hold` before high, before the lowering, before every air slide and back step and every approach step; a refusal holds the arm (stuck), no forward motion, no automatic retreat | `lateobst` (a box after "Reaching." in the air test): no lowering, no slide / both. `lateobst2` (a box after "Approaching." in an order): no approach step / 3 steps, grasped |
| 7. The off - model_off rule fires at the nominal reading | the plan states expected ranges per axis (d 0.03-0.12, n 0.00-0.04, z 0.00-0.07; mock 0.098 / 0.020 / 0.043); the brain flags a blob whose near face lies inside the can ("NEAR FACE INSIDE THE CAN: not used") | plan text; the flag is code |
| 8. A missing Gemma box | the servo's first frame fails without a box (unless `--no-gemma-hand`, logged); the probe line prints "gemma hand box: none"; the overlap is required both ways (Gemma's box on the blob's and the blob's on Gemma's) | `gemmanone` (an order, Gemma returns no box): no approach / approached and grasped |
| 9. Can resets with the arm held | `p` between orders releases the arm at home ("Releasing my arm for the reset.", `== ARM OFF`), `p` again takes it back with the start-up checks ("Taking my arm.", `== ARM ON`), Enter typed while paused is ignored and a fresh Enter is needed: ROBOT_RULES' ARM OFF rule holds without a rule change | `pause`: released at home, Enter ignored, no order started / no release, the order started on the latched Enter |

Also from the in-plan should-fix list: `--no-grasp` on every plan command (`nograsp`: stopped before the pick / grasped); `--pre-offset`,
`--no-gemma-hand` and `--air-margin` logged as deviations and every round-3 flag in the order params; "Correcting." before each servo
nudge; the probe neither speaks nor records `off` from a flagged blob (`off_flagged`), and the flags come from every frame, not the last;
the retreat's description names the bridge's wrist turn in degrees and announces it ("Turning my wrist."); `o` lines between orders go
to `observations.jsonl`; `--table-edge` refused outside 0.30-0.55; `--speed` and `--table-edge` parse errors and the missing
`--expect-calib` end the program before anything is built; the air slide and back steps stop on a stall (a step under 5 mm or the
tracking over the baseline + contact rise) instead of feeding the lag forward; `--air-margin 0` gives the floor-bound lowering with no
can (the plan's fourth air run); Gemma's box is scaled to the frame's own size; `calib.py` reports "not a git clone" apart from "dirty"
and covers `bench/client.py`; `a` typed between orders no longer cancels the next one.

## Round 2 (8e226e9): the five blockers, still holding

Each gate case runs a path other than the one the verifiers used (`V2_REVIEW_round2.json`). "c39a468" = that case run on the c39a468
tree with this mock (`CHECK_TREE=<tree> BRAIN_MOCK_TABLE_EDGE=0.27 python check.py --cases ...`; c39a468's plane fit fails with the
mock table's edge at 0.30 or 0.34, so its runs use 0.27).

| Blocker | Fix | Gate case: new / c39a468 |
| --- | --- | --- |
| 1. Wrist snap in one target | `Arm.set` splits any target that moves a joint more than `joint_step_rad` x speed (0.02 rad = 1 rad/s, under g1-fetch's streamer clip of 1.2 rad/s) into joint-interpolated sub-targets; `Arm.path` blends the wrist roll from where it is to the planned roll; the palm cap (2 cm) stays | `speed`: a whole order at --speed 0.5 (raise, high, pre, servo, approach, lift, offer, retreat): max joint step 0.010 rad / 0.394 rad (the wrist, after "Reaching."). Every mock run checks it (0.020 at speed 1). `test_motion` joint step at speeds 1 and 0.5 / 0.427 rad on high |
| 2. A stop during the raise or the descent goes home in joint space | the raise is recorded as it streams (`Arm.trail`, kept on any stop); the way home is planned before any motion (`plan_retreat`): on the recorded raise, the raise retraced from there; over the table, up (only until 5 cm from the can), back to the raise end at that height, a capped joint-space bridge, the retrace; joint space only with the wrist and palm below the table top and behind the raise waypoint; anything else holds (stuck) | `raisefail` (a g1-fetch failure at z 0.20 of the raise in an order): after it the hand below the table top + 3 cm reaches x 0.308 = the raise's 0.308 / 0.350, "joint space". `descent` ('a' 7 cm down the retraced descent of air (0.35, 0.00), half speed, then h + y): 0.306 = the raise, ends at home / 0.347 |
| 3. No safe way out of stuck | `set_stuck`: the arm holds, a spoken reminder every 30 s; `h` (only while stuck, else "ignored") plans the way out from where the arm is and says it, nothing moves; `y` runs it (announced; a finished retreat-up is never repeated, so retries cannot walk); `a`/`q`/Ctrl-C during a retreat or the shutdown stops the arm there (SIGINT stays live); the arm is never released away from home: `q` brings it home first, `quit!` (after L2+B) exits without releasing | `walk` ('a' at the approach, 'a' again during the retreat back, h + y): the palm never went further out or up (0.0 cm) / 5.3 cm out. `quit2` ('q' at the pre-grasp, 'q' again during the shutdown's retreat): holds, no release away from home / released at (0.425, 0.218, 0.237). `sigint2` (the same with Ctrl-C): 1 target after the second / 368 |
| 4. The corrections push into the table | goals, correction commands and approach steps are floored at plane + palm half-height + 5 mm; a correction round the hand did not follow (under half the commanded change) or that did not shrink the error ends the rounds; a blocked pre-grasp or servo nudge refuses the move; a lowering near the table stops 2 cm above and finishes with the sag measured there; the mock's hand meets the real table | `table` (the depth plane 20 mm low, a full order): lowest command 0.142 over a floor of 0.105, push 9 mm, refused at the pre-grasp / push 34 mm (the command 3.4 cm under the resting hand). `test_motion`: plane 5/10/20 mm low: push 1/8/23 mm / 32 mm at 10 mm; the palm bottom above the table at every target for the 12.2 and 13.5 cm cans and a 3 cm servo nudge toward it / table contact |
| 5. The fingertip feature is the window's edge | the hand window is 200 x 170 px with a 25 cm radius, centred 4 cm ahead of the palm, grown once (1.4x) when touched; a blob within 8 px of the window, cut by the radius or at the image border is measured but not used; the margins are printed | `fwd39` / `fwd54` (forward hidden errors 3.9 / 5.4 cm, K from the mock kill test): servo0 e_d -0.037 / -0.050, 1-2 corrections, the first close a grasp / e_d -0.007 / -0.001, no correction, the first close empty |

### Round 2 must-fix list

| Item | Fix | Gate case |
| --- | --- | --- |
| The hand closes on the model gap | the gap counts only from a visual reading taken clear of the can (model gap >= 2 cm; nearer, the can hides the near face) minus the measured advance; the larger of visual and model counts, and only when they agree within `visual_gap_agree_m` (1 cm); otherwise no close. The approach is capped at the standoff + 1.5 cm | `nerr` (2 cm along the palm normal): "visual 0.049 vs model 0.029: no close" (c39a468 closed) |
| A failed Gemma cross-check | the cross-check is now whether Gemma's hand box lies on the depth blob's box (under 50% overlap fails; the old 3D distance compared two different hand points and grew with the forward error: 3.8 / 5.0 cm); a failure ends the order, no approach | `gemma` (Gemma's box 15 cm off): skill_failed, no approach (c39a468: grasped) |
| No pick with K null | `no_K` unless `--model-grasp` (a logged deviation) | `noK`: refused, nothing moves (c39a468: a model-only grasp, 977 targets) |
| The obstacle check fails open | `geom.obstacle_ahead` returns (blocked, why, valid fraction, points): under 70% valid depth refuses ("cannot see ahead"); every check is printed and logged; `assist()` checks before any move; points within 7-8 cm of the robot's own arm (measured joints) do not count (a cross-body reach put 264-311 forearm points in the zone and refused the assist) | `zero` (no valid depth), `minrange` (a box inside the D435i's 0.28 m minimum range leaves 12% valid): refused (c39a468: moved) |
| The air test proceeds without a plane | the table under the target is fitted without the tape hint; no level plane = refused; more than 2 cm from the tape = refused | `tape` (3 cm high), `tape8` (8 cm low, the dangerous side): refused (c39a468: the palm commanded to z -0.043) |
| Assist after a refused locate | a refused locate on the retry ends the order | `assist` (a box appears after the miss): ended at the locate, no assist (c39a468: assisted) |
| `--speed` | in (0, 1] at parse time; reaches the approach steps (0.05 m/s x speed) and every joint-space move (the joint cap) | `--speed 5`, `--speed 0` refused; `speed` |
| Nothing enforces the calib hash | `--expect-calib SHA16` exits before anything is built on a mismatch or a dirty tree; on every run-plan command | `--expect-calib` mismatch refused |

### Round 2 plan changes

- The raise sag has no lower bound (recorded; over 0.07 m the brain stops by itself; a corrected pre-grasp over 2 cm too).
- `off - model_off` is recorded per slot, not judged (the slots vary in y only).
- The servo-residual block runs at two slots with `--pre-offset 0.025` (a logged deviation: the pre-grasp 2.5 cm back along the forearm
  gives the servo an error to remove).
- The blocks fit 100 minutes (12 + 10 + 18 + 32 + 13 + 15).
- `p` is described as what it does: no new order starts, the arm stays held at home.
- The elbow gaps are judged by comparison: `clear` / `close` / `contact`.
- The stuck procedure, `q`/Ctrl-C (not a stop: the arm comes home first), `(dirty)` and `CALIB IDENTITY FAILED` are in the stop rules;
  `--expect-calib` and `--table-edge` are on every command; the code identity is `git diff --quiet 8e226e9 HEAD -- '*.py' calib.json`.
- The no-motion block checks the valid-depth line, a hand held at 20 and 30 cm (must be refused), the home_q line and the dry raise's
  low reach against E.
- The third air target moved from (0.30, -0.05) to (0.40, -0.08): with E beyond 0.33 the old one has no table under it (the brain
  refuses it); the new one plans at yaw 35 with the tightest upper-arm clearance of the three (4.6 cm).

### Round 2, also fixed

- TTS before every retreat ("Up and back."), the air slide ("Sliding.", "Back.") and the release ("Releasing my arm."); air() sets the
  table height from the tape (the keep-out used a 0.075 literal); the keep-out runs on every raise, retreat, bridge, home and park
  path and needs `--table-edge` (the arm is not enabled without it); the startup park refuses (nothing enabled) unless the measured arm
  hangs below the table top behind the raise, and then moves home on the brain's own capped stream (no g1-fetch `move_to`); `--park
  zero` is gone; `Abort`/`OrderAborted` are BaseExceptions (no broad `except` swallows a stop); a blocked stall-fix nudge is not
  re-closed; the probe line prints the margins, the scatter and "hand not seen"; the dry air run prints the raise's low reach; `git_dirty`
  treats a failed `git status` as dirty.
- Found while fixing: the table plane under a can 4-6 cm from the table's edge was the floor (the band under the can sees past the
  edge): the fit now keeps points within 6 cm of the can base, considers level candidates only, starts the band at the can's mid-height
  and reads the height from the inliers (the plane's value at the pelvis origin extrapolated a 1.4 degree tilt of a 3.5 cm strip to
  +1 cm). The mock's push moved every can ahead of the fingers; now only the one touched.

## Passed offline, with numbers

| Check | Command | Result |
| --- | --- | --- |
| `check.py` | `~/miniforge3/envs/brain/bin/python -B hackathon/brain/check.py` | 50 of 50 pass in 95 s: compile, test_geom (4), test_motion (5), replay_reach, calib, 3 CLI refusals, the mock kill test (K from 2100+ hand points), and 41 mock runs (the round 1-3 cases above; the plan's air commands at half speed: (0.38, 0.15), (0.35, 0.00), (0.40, -0.08) and (0.38, 0.15) with `--air-margin 0`: pre-grasp 1.5-4 mm, slide end 1.3-1.9 mm, largest joint step 0.010 rad, home and release at home) |
| Round-3 cases on 8e226e9 | `CHECK_TREE=<8e226e9 tree> check.py --cases released,nearhand,qstuck,wayfail,wayfail1,secondq,killtable,servoblock,reach,lateobst,lateobst2,gemmanone,pause,nograsp` | all 14 fail on the behaviour they test (numbers in the round-3 table) |
| Motion tests on 8e226e9's motion.py | `MOTION_MODULE=<8e226e9>/motion.py python test_motion.py <name>` | the lowest-point, servo-nudge and table-push tests fail (6.7 mm under the table, stopped short on contact, 21 mm push); the joint-step test passes (round 2's fix) |
| Seven-scene regression (round 2) | 11 orders | 4 successes, 2 edge refusals, 5 misses with no close; grasps are not in this plan |

## Cannot be checked offline

| What | Why | Covered by |
| --- | --- | --- |
| The real hand's depth blob and features | the mock renders a box with full depth returns | the kill test (`probe:` line with margins, `measure_probe.jpg`, Gemma's box overlap, the near-face check) |
| The torso bands and clearances against the stand with straps | meshes and logs, not the rig | the air test, the owner's `o gap_torso=clear\|close\|contact ..` |
| The real sag and tracking baseline per pose, and the hand's orientation on arrival | the mock's sag is fitted | the air test's `sag baseline` and `tracking baseline` lines; the fourth air run (`--air-margin 0`) shows the floor-bound lowering with no can |
| The table's height and near edge, the hand's length, half-height and thickness | only the tape knows them | `--table-z T`, `--table-edge E`, `--fingertip F`, `--palm-half-height H`; the dry run's plane and raise lines |
| What the D435i sees near the chest | the mock only blanks a minimum range | the no-motion block: a hand at 10, 20 and 30 cm |
| What g1-fetch does at enable, at disable and when the brain exits with the arm out | `g1_fetch/control/arm.py` is not in this repo (the excerpts read: enable holds the measured pose, disable ramps the weight to 0 over 2 s, `max_joint_vel` 1.2 rad/s in `default.yaml`) | the boot block reads arm.py and pc2.yaml; the brain refuses an enable that holds another pose; `quit!` only after L2+B |
| The palm face offset (`palm_to_axis_m` 0.01) | assumed, n 0 | the owner's tape; grasps only |

## How to run it

The run plan `hackathon/briefs/2026-10-21-v2-kill-test.md` has every command and the expected lines; in short, on PC2 after the per-boot
steps: `git pull`, `git status --porcelain` (empty), the identity line, `test_geom.py`, `test_motion.py`, `preflight.py`, the dry runs
(with the hand at 10, 20 and 30 cm), the air test at four targets at half speed, the kill test with `--floor-margin 0.02`, the servo
residual with `--pre-offset 0.025` at y 0.09 and 0.06. Every command carries `--park home --no-grasp --expect-calib ae553548d47b677a --table-z T`
and, when the arm may move, `--table-edge E --fingertip F --palm-half-height H`.

## Left for later (the grasp session; not in this plan)

From round 3 (marked not in this plan, or in-plan notes left as notes):
- The visual gap is not independent of the model along the palm normal once K is probed with the same error (the mock closed 2.4 cm short
  while the two agreed); K needs provenance (value, frame, psi, standoff, can diameter, session and order, scatter) and a refusal when
  psi, standoff or diameter differ; the owner's `gap_n` at the kill test is the first data for it.
- The stall-pattern fix nudges 2-3 cm blind and re-closes with no measured gap.
- Transit height (round 2): the high waypoint (12 cm above the pre-grasp, about 5 cm lower with the sag) leaves the hand below a 13.5 cm
  can's top; a transit path across another can sweeps through it (the mock's three-can scene). The kill test's path stays 5.1 cm from the
  can axis at the near face.
- The keep-out tests commanded joints and three points per pose against a T + 3 cm band; for low paths over the table (grasp retreats
  with a can) evaluate it on the sagged pose with the hand box. The bridge onto the raise end is a joint-space wrist roll of 0.6-1.3 rad
  at transit height, with no clearance check (pose_checks on retreat targets).
- Matching the recorded raise uses the streamer's command (within two joint steps); if g1-fetch re-seeds it (an exception, a re-enable)
  a stop mid-raise finds no match and holds (safe): keep the brain's own last-sent target, or match by palm distance with the sag.
- Split sub-targets are joint-interpolated and not checked against the keep-out or clearances; refuse a planned target that needs more
  than about five joint steps (a branch flip).
- The Gemma cross-check is a box overlap (both ways now); an undetected object merged with the blob, or a box shifted under half its
  length, can still pass. Exclude the can by the per-frame estimate with a larger margin; the near-face check catches the worst case.
- Fresh obstacle checks before the stall-fix nudge and the offer (orders only); `--table-edge` cross-checked against the edge seen in
  depth; `quit!` refused unless the FSM reads damping.
- The 30 s stuck reminder, the 30 s y window and the tty Enter gating run only on the robot (the mock types keys); a fake-clock test.
- The mock: a continuous forearm and finger gaps (the box hand gives K_d 0.086; a continuous forearm 0.056), the sag refit from v2's
  logged q_cmd/q_meas after the air test (it under-predicts the raise and has no can load).
- From round 2: the can-axis bias (1-1.5 cm for cans at y >= 0.17 and right of centre), `palm_to_axis_m` (palm centre vs palm face),
  `--palm-real` not reaching the kinematics, the stall signature mapping; the other 111 round-1 findings in `V2_REVIEW_findings.json`.
