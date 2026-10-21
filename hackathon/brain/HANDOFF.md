# Handoff: brain v2 after V2_REVIEW round 2 (2026-10-21)

What the build session leaves for the robot session. Nothing here has run on the robot; what cannot be checked offline is named below
with the reason and the no-motion check or observation that covers it.

## Commit

- Code: `8e226e9` on `hackathon` ("brain v2: fix the five V2_REVIEW round-2 blockers and the must-fix list, ..."), NOT pushed (the
  coordinator's rule for this session); push before the session so PC2 can `git pull`. Later commits change documents only. In
  `hackathon/brain`: `git diff --quiet 8e226e9 HEAD -- '*.py' calib.json && echo CODE 8e226e9` must print `CODE 8e226e9`.
- `calib.json` sha16: `9a8165bf6976c20f` (`python calib.py | head -1`), 33 entries (new: `joint_step_rad` 0.02, `table_floor_margin_m`
  0.005, `visual_gap_agree_m` 0.01), none stale. Every run-plan command carries `--expect-calib 9a8165bf6976c20f`, which refuses another
  sha or a dirty tree (a failed `git status` counts as dirty). On the Mac the line shows `(dirty)` only because `V2_REVIEW.md`,
  `V2_REVIEW_findings.json` and `V2_REVIEW_round2.json` are untracked (the coordinator's files, not committed by this session).
- Files changed in 8e226e9: `brain.py motion.py geom.py calib.json calib.py mock_robot.py check.py test_geom.py test_motion.py`.

## The five round-2 blockers, and how each is now caught

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

## The must-fix list

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

## Plan changes (`hackathon/briefs/2026-10-21-v2-kill-test.md`)

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

## Also fixed (from the verifiers' should-fix and notes)

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
| `check.py` | `~/miniforge3/envs/brain/bin/python -B hackathon/brain/check.py` | 33 of 33 pass in 75 s: compile, test_geom (4), test_motion (5), replay_reach, calib, 3 CLI refusals, the mock kill test (K 0.086, -0.052, -0.006 from 2147 hand points), 24 mock cases (above, plus servo: 2 corrections, the first close a grasp, closed at a measured gap of 0.2 mm; model with --model-grasp: the first close "forward"; contact: aborted on a 1.7 cm lag, no close; abort: retreat-up, retreat-back, the raise retraced; dry: no target streamed; block: refused; air: sag 2.3 / 4.9 cm, pre-grasp 3 mm, five steps 7-11 mm, slide end 1.7 mm) |
| Round-2 cases on c39a468 | `CHECK_TREE=... BRAIN_MOCK_TABLE_EDGE=0.27 check.py --cases speed,raisefail,descent,walk,quit2,sigint2,table,fwd39,fwd54,nerr,gemma,noK,zero,minrange,tape8,assist` | every one fails on the behaviour it tests (numbers in the tables above); `tape` (3 cm) passes there: c39a468 caught a tape error under 6 cm |
| Air targets, half speed | `brain.py --mock --air --speed 0.5 --air-table 0.075 --table-edge 0.34 --air-can X Y` | (0.38, 0.15) yaw 10, (0.35, 0.00) yaw 35, (0.40, -0.08) yaw 35: completed, largest joint step 0.010 rad per target, retreat and retraced home, released at home; raise low reach 0.306-0.308 |
| Seven-scene regression | 11 orders, K from the gate, the default hidden error | 4 successes, 2 refusals of a can at the image edge, 5 misses with no close (the hand at the image edge for cans at y 0.17-0.30: no visual gap; round 1 on c39a468 had 5 successes in 11 with the looser close rule); no release away from home, every order ended at home |

## Cannot be checked offline

| What | Why | Covered by |
| --- | --- | --- |
| The real hand's depth blob and features | the mock renders a box | the kill test (`probe:` line with margins, `measure_probe.jpg`, Gemma's box overlap) |
| The torso bands and clearances against the stand with straps | meshes and logs, not the rig | the air test, the owner's `o gap_torso=clear\|close\|contact ..` |
| The real sag and tracking baseline per pose | the mock's sag is fitted, not measured on v2's poses | the air test's `sag baseline` and `tracking baseline` lines |
| The table's near edge and height | only the tape knows them | `--table-edge E`, `--air-table T`; the dry run's plane and raise lines |
| What the D435i sees inside its minimum range | the mock only blanks it | the no-motion block: a hand at 20 and 30 cm must be refused |
| What the arm does when the brain exits with the arm out | g1-fetch's `ArmStreamer.close` not read | `quit!` only after L2+B (the stop rules) |
| g1-fetch's streamer clip on PC2 | `pc2.yaml` not in this repo (`default.yaml`: max_joint_vel 1.2 rad/s) | the boot notes: `grep -n max_joint_vel ~/g1-fetch/configs/*.yaml` |
| The palm half-height and the palm face offset | assumed (0.045, 0.01), n 0 | the owner's tape |

## How to run it

The run plan `hackathon/briefs/2026-10-21-v2-kill-test.md` has every command and the expected lines; in short, on PC2 after the per-boot
steps: `git pull`, the identity check, `check.py`, `preflight.py`, the dry runs, the air test at three targets, the kill test, the servo
residual with `--pre-offset 0.025`.

## Left for later (not blockers for this plan)

- Transit height: the high waypoint is 12 cm above the pre-grasp, so even unsagged the hand's bottom is 7.5 mm below a 13.5 cm can's top,
  and the uncorrected high move sags another 4.5-4.9 cm. A transit path that crosses another can sweeps through it (the mock's three-can
  scene: 23-28 pushes of the middle can). The air test has no can and the kill test's path stays 7-8 cm beside its one can. Fix in the
  grasp session: the transit height from the table + the tallest can + the palm half-height + a margin + the sag, the high move
  corrected, the transit path checked against the other cans.
- The obstacle check runs before locate, the air test and the assist (the robot's own arm masked); the verifiers also asked for fresh
  checks before the air slide, the stall-fix nudge and the offer.
- The hand blob can take in an object the detector misses within 25 cm of the hand (only detected cans are excluded).
- The can-axis bias (1-1.5 cm for cans at y >= 0.17 and right of centre) and `palm_to_axis_m` (the closure pose puts the palm centre,
  not the palm face, r + 1 cm from the axis): grasp-session items, with `--palm-real` not reaching the kinematics and the stall
  signature mapping of round 1.
- The mock's sag under-predicts the raise (1.6-1.8 vs 1.9-2.5 cm) and has no can load: refit from v2's logged q_cmd/q_meas after the
  air test.
- The other 111 round-1 findings in `V2_REVIEW_findings.json` are not triaged.
