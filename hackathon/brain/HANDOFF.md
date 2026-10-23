# Handoff: brain v2 after V2_REVIEW round 4 (2026-10-21)

What the build session leaves for the robot session. Nothing here has run on the robot; what cannot be checked offline is named below
with the reason and the no-motion check or observation that covers it.

## Commit

- Code: `7869c62` on `hackathon` (round 4), NOT pushed to GitHub (the coordinator's rule for this session). Later commits change
  documents only. In `hackathon/brain`:
  `git diff --quiet 7869c62 HEAD -- '*.py' calib.json ../../bench/client.py && echo CODE 7869c62` must print `CODE 7869c62`.
- On PC2 (2026-10-22, no motion): `~/harness` fast-forwarded from 83d7c0e to `da3215a` from a git bundle (`~/deploy/`); the 29
  untracked files the fast-forward replaced were byte-identical to the committed ones (copies in
  `~/deploy/untracked-before-ff-20261023T025637`). There: `CODE 7869c62`, the brain folder clean, `calib calib.json sha
  ae553548d47b677a git da3215a` with no `(dirty)`, `test_geom` 4/4 and `test_motion` 5/5 (54 s), `preflight.py` 11 pass with
  `cam_services` and `fsm` failing until the owner's boot steps (stop the teleimager services, R1+X), and the three no-cloud items as
  warnings.
- `calib.json` sha16: `ae553548d47b677a` (`python calib.py | head -1`), unchanged in round 4: 36 entries, none stale. Every run-plan
  command carries `--expect-calib ae553548d47b677a`; without it the brain refuses on the robot, and it refuses another sha, a dirty tree (the
  brain folder and `bench/client.py`) or a tree that is not a git clone. On the Mac the line shows `(dirty)` only because the
  coordinator's untracked `V2_REVIEW*` files sit in the brain folder.

## What the code does (round 4)

- **Stops.** `q`, `a`, Ctrl-C, SIGTERM and SIGHUP add one to a stop counter and nothing else; `check_abort` raises one exception,
  `Stopped`, whenever the counter is ahead of the count armed at the start of the order or at the last `y`. It runs before every
  streamed target (raise, high, lowering, corrections, approach and air steps, retreats, the way home), in every wait, at the start of
  every stage and before every hand command. The arm freezes at its next 20 ms target and holds.
- **Hold.** A stop, a refusal (the 0.30 m rule, a head camera that cannot be read), a `SKILL FAILED`, an error with the arm out, an
  `ENABLE MISMATCH` and the end of every probe all end in the same place: `hold()` records why and where, `hold_loop()` plans the way
  home from where the arm is (`plan_retreat`, keep-out checked), says it ("The way home: ... Press y to run it.", every 30 s) and runs it
  only on `y`. A stop on the way home holds again and the new way home is said; a stop while the brain waits for `y` drops the
  announced move and says the way home again. There is no automatic retreat after a failure. "I have no safe way home" asks for L2+B
  and `quit!`.
- **Exit.** The run ends after any stop, `quit!`, or the last order. The program releases the arm only at home ("Releasing my arm.");
  `quit!` (or `quit`) exits without moving or releasing anything (only after L2+B). The shutdown with the arm away from home runs the
  same hold loop.
- **Keys.** One meaning each in every state: Enter starts the order the brain waits for (else "ignored"); `q` / `a` / Ctrl-C stop; `y`
  runs the announced move (else "ignored"); `quit!` exits holding; `r` releases a held can at the handover; `o k=v ..` logs an
  observation; anything else prints the key list. `p`, `h`, the pause and the stuck state are gone. Control flags: 9 (`stops`, `armed`,
  `quit_now`, `answer`, `go`, `release_now`, `held`, `waiting`, `wait_enter`), of which the keys and signals write 5 (`stops`, `quit_now`,
  `answer`, `go`, `release_now`); 13bff01 had 15 (`quit`, `abort`, `release_now`, `paused`, `go`, `stuck`, `home_req`, `retreating`,
  `in_shutdown`, `freeze_req`, `force_quit`, `quit_after_home`, `hold_on_quit`, `pause_released`, `answer`). One exception class instead
  of four names.
- **One process per run.** The run plan starts the brain with `--orders 1` for every run; each process parks, runs one order and exits
  at home with the arm released; the can is moved between processes.
- **The raise.** `plan_raise` solves and keep-out checks both lines of the raise (up 2 cm behind the hip to the table top + 3 cm, then
  the raise waypoint) before anything moves; the pick, the assist and the `--dry` line of an order, a probe and the air test all use it.
  `--dry` prints `dry raise from home (candidate y Y): up-low below z Z stays behind x A, up behind x B (taped table edge E)`.
- **The table floor.** Per order the open hand's lowest point stays above the higher of the fitted plane and `--table-z`, plus
  `--floor-margin` (printed: `table floor: ...`); the fitted plane more than 2 cm from `--table-z` refuses the order in every mode (no
  motion). The final line onto a goal near that floor is watched per target and stops when the measured hand falls more than 6 mm
  behind the command (`contact_lag`); the largest lag is printed (`final line near the table floor: largest lag ...`). The contact
  rules of round 3 stay (a hand resting above its goal near the floor, the stop 2 cm above the goal).
- **The 0.30 m rule.** Before high, before the lowering, before every air, back and approach step, before every servo correction and
  before a stall-fix nudge: nothing within 0.30 m straight ahead at chest height, at least 70% valid depth, and no connected region of
  invalid depth over `--blind-max` of the frame, in every state; with the arm out its projected silhouette (each segment's radius + 2 cm)
  is left out of the blind map, and its points within 7-8 cm of the measured arm do not count. Every check prints `valid depth NN%,
  largest blind region MM%`. `--blind-max` (default 0.08) is in the order params and logged as a deviation when changed.
- **The probe.** After the measurement it flags (stores `off_flagged`, says why and "Not used.") a blob that is cut off, a near face
  inside the can, a missing Gemma box or one under 50% on the blob, or `off - model_off` outside d 0.03-0.12, n 0-0.04, z 0-0.07; then
  it holds. With `--probe-servo` each correction is announced ("Correcting N millimetres along my forearm and M up. Press y to run it.")
  and runs only on `y`.

## Round 4: what changed, and the gate case that shows it

Scope: the seven items of the coordinator's round-4 message. Each gate case runs on this commit and on 13bff01 with the same mock
(`CHECK_TREE=<13bff01 tree> python check.py`). "new / 13bff01" below.

| Item | Change | Gate case: new / 13bff01 |
| --- | --- | --- |
| 1. The dry line plans the old straight raise (plan blocker) | `plan_raise` is the one raise planner: the pick, the assist and the `--dry` line of an order, a probe and the air test; the line prints both lines' reach and the candidate y | `dryprobe` / the kill test, `dryair125` / `air`, `dryair140` / `air140`: the dry line equals the moving raise within 1 mm, (0.296, 0.307), (0.295, 0.304), (0.309, 0.320 vs 0.319) / the dry line 0.350 and 0.365 (the straight raise) against the same moving raise; the probe printed none |
| 2. Stops, one meaning per key | one stop counter and one exception; the hold, the way home on `y`, the exit only at home or on `quit!` (above); flags 15 -> 9; the automatic retreats after a failure, the stuck state, `h`, the freeze and quit-after-home latches are gone | the key table (21 rows: raise + q / a / Ctrl-C / quit! / y / Enter / p, lowering + a, pre-grasp pause + q, held + q / quit! / Enter, the way home + Ctrl-C, the air slide + q, the normal retreat + a, idle + q, idle + p / y / Enter, a failure + y / quit!, the servo's wait + q, LOOK + q): at most 1 target from each stop to the next `y`, home and released there, `quit!` exits holding with nothing released / 16 rows fail on the behaviour (11-13 targets after a stop in the raise, 383 at the lowering, 433 in the pause, 452 in the slide, 11 after a failure, all homing by themselves; the probe never held; 0.43 m from home at exit after Ctrl-C on the way home or `a` in the retreat; `p` paused and hung), 3 only on the result name or message (raise + quit!, LOOK + q, raise + Enter), 2 pass (raise + y, idle + q). The stop cases `abort` (the retreat after `y`), `raisefail`, `descent`, `walk` (the new way home's retreat ends where the first one did), `quit2`, `sigint2`, `secondq`, `wayfail`: 0-1 targets before `y`, home / all 8 fail (the retreat by itself; 219 targets after the raise failure; 5-6 after the first q; 0.38-0.47 m from home at exit with only `y` typed) |
| 3. Pause | `p` and the pause are gone (an unknown key); the plan runs one process per run (`--orders 1`), each ending at home with the arm released; the can is moved between processes | key rows raise + p and idle + p / y / Enter: "[p] not a key", the order runs / the run paused, no order, the case hung |
| 4. The probe's pause and gap_n | gap_n is out of the plan; the probe ends holding; with `--probe-servo` each correction is announced and runs only on `y` | key rows held + q / quit! / Enter, servo's wait + q, pause + q (above); `servoblock`: 1 correction, each after its `y` / corrected with no `y` |
| 5. Table contact | the mock's hand box against the table (its corners and the points where its 12 edges cross the near edge); the final line onto a goal near the floor stops per target when the hand falls 6 mm behind the command, its largest lag printed; the floor on the higher of the fitted plane and `--table-z` (printed); the plane more than 2 cm from `--table-z` refuses in every mode; the fourth air run at `--floor-margin 0.02` | `killtable` (slot y 0.12, `--floor-margin 0.02`, the tape and the plane both 15 mm low, the hand 2 cm low): stopped at a 7 mm lag, push 5.0 mm, 11 contacts, held / the line streamed to its end, 12.7 mm, 29 contacts. `table` (the plane 15 mm low, the tape right): the floor 0.080 on the tape, no contact / 29 contacts. `planetape` (the tape 3 cm below the plane, a probe): no motion / the probe ran (853 targets). `servoblock` (slot y 0.09, K from the margin-0.02 probe there): no contact, residual (-0.003, 0.005) / no contact. `airfloor`: lag 0.000, pre-grasp 2.6 mm / passes (no change) |
| 6. Obstacle | the 0.30 m rule before every servo correction and stall-fix nudge; the blind-region rule in every state, the arm's projected silhouette left out; every check prints the largest blind region; `--blind-max` in the order params and logged as a deviation | `servoobst` (a box after the probe's result): held before the nudge / nudged. `armhand` (a hand 10 cm from the chest after "Raising.", 0.28 m minimum range): held before high, "one region of 14%" / reached, "largest blind region 17%" read clear. `armclear` (the same range, no hand): the probe runs, 0% / passes (control). `camfail` (the head camera stops after "Reaching."): held, no lowering / an error, home by itself. `nearhand50` (`--blind-max 0.5`): passes, the deviation logged / not logged |
| 7. Documents | README, this file and the run plan describe the code at 7869c62; the stuck, `h`, `p`, ARM OFF, gap_n and quit-after-home text is deleted; the plan's E window comes from the dry line, by F | the run plan's table |

## Earlier rounds: the fixes that still hold, and their cases (all pass at 7869c62)

| Round | Fix | Case |
| --- | --- | --- |
| 1 | the servo corrects a hidden error the model misses; a model-only close is not a grasp; contact 1 cm early: no close; `--dry` never enables; the air test refuses a box at chest height | `servo`, `model`, `contact`, `dry`, `block`, `air` |
| 2 | no joint moves more than 0.02 rad x speed in one target (every mock run checks it); the raise recorded as it streams and retraced from any stop; the floor and contact rules; the hand window and its margins; the visual gap must agree with the model; Gemma's box on the blob; no pick without K; fail-closed depth; the air test's table check; no assist after a refused locate; `--speed` and `--expect-calib` refusals | `speed`, `raisefail`, `descent`, `table`, `fwd39`, `fwd54`, `nerr`, `gemma`, `noK`, `zero`, `minrange`, `tape`, `tape8`, `assist` |
| 3 | the start-up check after a release; the hand inside the D435i's minimum range; the keep-out of a 12.5 cm hand through the two-stage raise; a re-check before high, the lowering and every step; no Gemma box: no approach; `--no-grasp`; the plan's air commands at half speed | `released`, `nearhand`, `reach`, `lateobst`, `lateobst2`, `gemmanone`, `nograsp`, `air2`, `air3`, `airfloor` |

The stop cases of rounds 2 and 3 (`abort`, `walk`, `quit2`, `sigint2`, `secondq`, `wayfail`) now gate the round-4 stop model (above).

## Passed offline, with numbers

| Check | Command | Result |
| --- | --- | --- |
| `check.py` | `~/miniforge3/envs/brain/bin/python -B hackathon/brain/check.py` | 84 of 84 pass in 125 s: compile, test_geom (4), test_motion (5), replay_reach, calib, five CLI refusals (`--speed 5`, `--speed 0`, `--fingertip 1.25`, `--table-z 7.5`, the calib mismatch), two mock kill tests (K [0.088, -0.052, 0.000] at the default can; [0.095, -0.052, 0.017] at slot y 0.09 with `--floor-margin 0.02`), 69 mock runs (the cases above and the 21-row key table, each checking the joint step per target: 0.020 rad at speed 1, 0.010 at 0.5), three dry-line comparisons |
| Round-4 cases on 13bff01 | `CHECK_TREE=<13bff01 tree> CHECK_TIMEOUT=240 check.py` | every round-4 case above fails there on the behaviour it tests, except raise + y, idle + q, `armclear` and `airfloor` (no change, by design) and raise + quit!, LOOK + q, raise + Enter (only the result name or the message differ); the unchanged cases of rounds 1-3 pass there |
| The E window by F | `--dry` runs of the four air targets and the four slots | in the run plan |

## Cannot be checked offline

| What | Why | Covered by |
| --- | --- | --- |
| The real hand's depth blob and features | the mock renders a box with full depth returns | the kill test (`probe:` line with margins, `measure_probe.jpg`, Gemma's box overlap, the near-face check) |
| The torso bands and clearances against the stand with straps | meshes and logs, not the rig | the air test, the owner's `o gap_torso=clear\|close\|contact ..` |
| The real sag and tracking baseline per pose, the hand's orientation on arrival and the real lag on the final line | the mock's sag is fitted | the air test's `sag baseline`, `tracking baseline` and the fourth run's `final line near the table floor: largest lag` |
| The table's height and near edge, the hand's length, half-height and thickness | only the tape knows them | `--table-z T`, `--table-edge E`, `--fingertip F`, `--palm-half-height H`; the dry run's plane and raise lines |
| What the D435i sees near the chest, and its blind regions with nothing in front | the mock only blanks a minimum range and reads 0% blind otherwise | the no-motion block: the largest blind region with nothing in front sets `--blind-max`; a hand at 10, 15 and 30 cm |
| What the arm does when the brain exits with the arm out | read on PC2 (g1-fetch `d3043d3`): enable sets the target and the command to the measured pose and ramps the arm_sdk weight to 1 over 2 s, disable ramps it to 0 over 2 s, `close` only stops the 50 Hz thread, effective `max_joint_vel` 1.2 rad/s; what the controller does when the messages stop with the weight at 1 is not in that code | the brain releases only at home and holds on an enable that holds another pose; `quit!` only after L2+B |
| The palm face offset (`palm_to_axis_m` 0.01) | assumed, n 0 | the owner's tape; grasps only |
| The 30 s hold reminder and the tty Enter gating | the mock types the keys | the first motion process on the robot |

## How to run it

The run plan `hackathon/briefs/2026-10-21-v2-kill-test.md` has every command and the expected lines; in short, on PC2 after the
per-boot steps: `git pull`, `git status --porcelain` (empty), the identity line, `test_geom.py`, `test_motion.py`, `preflight.py`; the
no-motion runs (the blind region with nothing in front sets `--blind-max`, a hand at 10, 15 and 30 cm, the air targets, the four
slots); the air test at four targets at half speed (the fourth floor-bound with `--floor-margin 0.02`); the kill test with
`--floor-margin 0.02`; the servo residual with `--pre-offset 0.025` at y 0.09 and 0.06. One process per run (`--orders 1`), each
ending at home with the arm released; every command carries `--park home --no-grasp --expect-calib ae553548d47b677a --table-z T` and,
after the first no-motion run, `--table-edge E --fingertip F --palm-half-height H --blind-max BM`.

## Left for later (the grasp session; not in this plan)

- The visual gap is not independent of the model along the palm normal once K is probed with the same error (the mock closed 2.4 cm
  short while the two agreed); K needs provenance (value, frame, psi, standoff, can diameter, session and order, scatter) and a
  refusal when psi, standoff or diameter differ.
- The stall-pattern fix nudges 2-3 cm blind and re-closes with no measured gap.
- Transit height (round 2): the high waypoint (12 cm above the pre-grasp, about 5 cm lower with the sag) leaves the hand below a
  13.5 cm can's top; a transit path across another can sweeps through it (the mock's three-can scene). The kill test's path stays
  5.1 cm from the can axis at the near face.
- The keep-out tests commanded joints and three points per pose against a T + 3 cm band; for low paths over the table (grasp retreats
  with a can) evaluate it on the sagged pose with the hand box. The bridge onto the raise end is a joint-space wrist roll of 0.6-1.3
  rad at transit height, with no clearance check (pose_checks on retreat targets).
- Matching the recorded raise uses the streamer's command (within two joint steps); if g1-fetch re-seeds it (an exception, a
  re-enable) a stop mid-raise finds no match and holds (safe): keep the brain's own last-sent target, or match by palm distance.
- Split sub-targets are joint-interpolated and not checked against the keep-out or clearances; refuse a planned target that needs
  more than about five joint steps (a branch flip).
- The Gemma cross-check is a box overlap (both ways); an undetected object merged with the blob, or a box shifted under half its
  length, can still pass. Exclude the can by the per-frame estimate with a larger margin; the near-face check catches the worst case.
- A fresh obstacle check before the offer (orders only); `--table-edge` cross-checked against the edge seen in depth; `quit!` refused
  unless the FSM reads damping; a stop at the handover opens the hand on `y` wherever the arm is (the way home drops a held can).
- The floor's hand drop across the body: at (0.40, -0.08) the predicted lowest point is 11.7 cm below the commanded palm (fingertips
  down at psi 35), so the correction commands are raised to z 0.197; at F 0.14 the reviewer saw (0.35, 0.00) refuse at the
  pre-grasp. Measure the real hand's orientation there in the air test before grasps across the body.
- The mock: a continuous forearm and finger gaps (the box hand gives K_d 0.086; a continuous forearm 0.056), the sag refit from v2's
  logged q_cmd/q_meas after the air test (it under-predicts the raise and has no can load).
- From round 2: the can-axis bias (1-1.5 cm for cans at y >= 0.17 and right of centre), `palm_to_axis_m` (palm centre vs palm face),
  `--palm-real` not reaching the kinematics, the stall signature mapping; the other 111 round-1 findings in `V2_REVIEW_findings.json`.
