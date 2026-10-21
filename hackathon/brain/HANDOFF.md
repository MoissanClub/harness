# Handoff: brain v2 after V2_REVIEW (2026-10-20)

What the build session leaves for the robot session. Nothing here has run on the robot; what cannot be checked offline is named below
with the reason and the no-motion check or observation that covers it.

## Commit

- Code: `c39a468` on `hackathon` ("brain v2: fix the six V2_REVIEW blockers, close on the measured gap, a gate that catches each"),
  NOT pushed (the coordinator's rule for this session); push before the session so PC2 can `git pull`. Later commits change documents
  only; `git log -1 --format='%h %s' -- hackathon/brain/brain.py hackathon/brain/motion.py hackathon/brain/geom.py hackathon/brain/calib.json`
  must print `c39a468`.
- `calib.json` sha16: `d26f244ab4d4f575` (`python calib.py | head -1`), 30 entries, none stale.
- Files changed in c39a468: `brain.py motion.py calib.json mock_robot.py check.py test_motion.py` (new).

## The six blockers of V2_REVIEW.md, and how each is now caught

| Blocker | Fix | Test that fails on 2d4f1ca |
| --- | --- | --- |
| 1. The pre-grasp correction hits the 2 cm cap | `motion.goto` streams every correction in capped sub-steps until the measured palm is within 6 mm; the lowering feeds the sag measured at rest forward; every path is solved before the arm moves | `test_motion.py` with the mock sag fitted to Tuesday's logs: raw high-waypoint error 4.8 cm, pre-grasp corrected to 2 mm, no dip below it. On 2d4f1ca: `pre-corr: a single target would move the palm 4.7 cm` |
| 2. A failed skill parks in joint space beside the can | `recover_fast` and every park go through `retreat`: up (forearm yaw held), back to the raise waypoint (the reach retraced), home by retracing the recorded raise, park at `home` (now the default); a refused move holds the arm and marks the brain stuck (`h` retries, `q` quits) | check.py `abort`: retreat-up, retreat-back, then home ("the raise retraced") and park at home. On 2d4f1ca: the order's SkillFailed was followed straight by a joint-space park at zero |
| 3. `--dry` moves the arm | `--dry` never enables the arm (an enable raises), no park, no home; every park and home is announced ("Parking.", "Home.") | check.py `dry`: no "arm streamer enabled", no "Parking.", no "Home.". On 2d4f1ca: enabled and parked at zero |
| 4. The air test's stop rule fires on uncorrected moves | up and high stay uncorrected and print/log `sag baseline at up/high`; the plan's 2 cm rule applies to the corrected `pre:` line | check.py `air`: sag 2.3 / 4.9 cm, pre err 3 mm |
| 5. `--air` skips the 0.30 m rule | `air()` reads one head frame first: the obstacle rule (refused as locate refuses) and the table under the target against `--air-table` (2 cm) | check.py `block` (a box at chest height): refused before any motion |
| 6. The handoff names a stale commit | this file and the plan name `c39a468` and the calib sha16; the boot block checks both | the boot block's expected lines |

Also fixed, from the review's "must fix before any can is grasped":
- The approach closes only on a measured gap under 1 cm (the closure pose from the latest measured can axis minus the measured palm;
  the visual near-face gap is used only when it agrees within 1.5 cm); a tracking-error rise to 2x the baseline or a cumulative lag of
  1.2 cm is an abort, never a close. check.py `contact` (contact 1 cm before the closure pose): aborted at 2.1 cm lag, the first close
  only after the retreat. On 2d4f1ca: `ok (tracking error 0.148 over base 0.000), remaining gap 0.015`, then the hand closed.
- The gate seeds a hidden error the model alone misses (true palm 3.6 cm behind the model, 1 cm high): with K (from the mock kill test)
  one servo correction and a first close that grasps (`servo`); without K the first close is "forward" (`model`).

## Found while fixing (not in the review), fixed in c39a468

- The joint-space move home from the raise waypoint swung the forearm down through horizontal: palm (0.304, 0.239, 0.072) and fingertips
  (0.383, 0.247, 0.064) at the table-top height, over the slots (FK of 2d4f1ca's path; v1's configuration swung out to y 0.37 at z 0.092
  instead, which is why it never touched). Home now retraces the recorded raise: below the table top + 3 cm the hand stays behind x 0.308,
  the same as the raise. Every raise and descent prints `... path: below z Z the hand stays behind x X`; `table_edge_m` (null until the
  owner tapes it) makes the brain refuse a path within 2 cm of the edge.
- Position-only moves forced the plan's palm normal, so the wrist roll hit its limit on the retreat from a cross-body reach (yaw 45); they
  now keep the hand's roll, and the retreat retraces the planned family with position-only IK as the fallback.
- A hand blob at the image border (the hand at the pre-grasp for cans at y >= 0.17) gave a visual gap of 0 while the model said 2.9 cm:
  the hand closed 3 cm short. Blobs within 8 px of the border are measured but not used (no servo, no visual gap).
- A can box at the image border gave a wrong diameter, axis and height (an IK failure mid-move, a no-plan): such a can is now refused
  ("at the edge of my view, please move it toward my centre").
- The approach's half-way re-correction along the forearm acted on a reading that drifted 1.9 cm with the hand still (K holds only at
  the standoff where it is measured): removed; e_d at half way is logged.
- `--speed` scales every Cartesian speed and joint-space duration (calib `speed_scale` 1.0; an override is logged as a deviation).

## Passed offline, with numbers

| Check | Command | Result |
| --- | --- | --- |
| `check.py` | `~/miniforge3/envs/brain/bin/python -B hackathon/brain/check.py` | 13 of 13 pass, 46 s (the table above, plus compile, test_geom 4 tests, test_motion 3 tests, replay_reach, calib, the mock kill test K (0.071, -0.052, -0.012) from 2844 hand points) |
| Mock sag fit | the fit in `mock_robot.py` | stiffness 50/30/40/30 Nm/rad, masses 0.8/0.5/0.8 kg; Tuesday's 25 uncorrected moves: high waypoints 2.7-4.8 cm predicted vs 2.5-4.6 logged, raise 1.5-1.7 vs 1.9-2.5, rms 9.5 mm; tracking baselines 0.054-0.072 rad vs 0.044-0.069 logged |
| Air targets, half speed | `brain.py --mock --air --speed 0.5 --air-table 0.075 --air-can X Y` | (0.38, 0.15) yaw 10, (0.35, 0.00) yaw 35, (0.30, -0.05) yaw 45: pre-grasp 2-3 mm, slide end 1-2 mm, retreat and retraced home completed |
| Six-scene regression | 11 orders, K from the gate, default hidden error | 5 successes, 1 honest negative, 2 refusals at the image edge, 3 misses: cans at y 0.17-0.21 (hand at the image edge, no servo) and 8 cm right of centre, all from a 1-1.5 cm error of the measured can axis (see the risks); every miss ended in the safe path (abort or short close, retry, assist, retreat) |

## Cannot be checked offline

| What | Why | Covered by |
| --- | --- | --- |
| The real hand's depth blob and features | the mock renders a box | the kill test (`probe:` line, `measure_probe.jpg`, Gemma's hand box) |
| The torso bands and clearances against the stand with straps | meshes and logs, not the rig | the air test, the owner's `o gap_torso=.. gap_stand=..` |
| The real sag and tracking baseline per pose | the mock's sag is fitted, not measured on v2's poses | the air test's `sag baseline` and `tracking baseline` lines |
| The table's near edge | only the tape knows it; the raise and the descent cross the table-top height with the fingertips at x about 0.31 (mock) | the owner's tape into `table_edge_m`, compared with every `... path:` line |
| The camera mount against the real view | the mock uses the URDF pose | the dry run's target and plane against the tape; the kill test frames |
| The palm half-height and the palm face offset | assumed (0.045, 0.01), n 0 | the owner's tape |

## How to run it

The run plan `hackathon/briefs/2026-10-21-v2-kill-test.md` has every command and the expected lines; in short, on PC2 after the per-boot
steps: `git pull`, the identity check, `check.py`, `preflight.py`, the dry runs (`--dry --manual --park home`, `--dry --air ...`), the air
test (`--air --manual --park home --speed 0.5 --air-table T --air-can X Y` at three targets), the kill test (`--probe --manual --park home`),
the servo residual (`--probe --probe-servo --K D N Z`).

## Parameters and calibration

- Read from `calib.json` (sha16 `d26f244ab4d4f575`): palm_real_m 0.246, palm_half_height_m 0.045 (assumed), grasp_below_mid_m 0.015,
  palm_to_axis_m 0.01, pregrasp_standoff_m 0.03, clearance_m 0.03/0.04/0.06/0.05, table_clear_m -0.01, pitch_max_deg 15, ik_tol_m 0.005,
  high_rise_m 0.12, raise_ahead_m 0.05, raise_side_y_m 0.18, retreat_out_m 0.05, approach_step_m 0.01, lift_m 0.06, lift_rise_tol_m 0.02,
  near_ahead_m 0.30, speed_scale 1.0, contact_rise_rad 0.015, hold_signature, torso_bands, camera_pose (URDF), hand_feature_K null,
  table_edge_m null.
- CLI overrides the plan allows (each logged as a deviation): `--speed 0.5` (air test), `--K` (from the kill test), `--pause`. Not
  `--palm-real`: it does not reach the kinematics (confirmed: `geom` binds the palm length as a default argument at import).

## Open risks

- The motion layer has never moved the real arm; the air test is its first run, at half speed, hand open, no can.
- The table edge: the raise and the retraced descent cross the table-top height with the fingertips at about x 0.31 (mock, URDF camera
  and arm). If the edge is nearer than about 0.33, they touch it; tape the edge before the first motion.
- Grasp success (not in this plan): the measured can axis is biased 1-1.5 cm along the approach for cans away from the image centre
  (the axis-aligned box of a slanted can; Tuesday's 58 mm Chi measured 70 mm and classed 66), so the approach aborts on contact or
  closes short there. The fix is the axis and diameter from the depth points of the can, a build task for the grasp session.
- Confirmed from the review's unverified list, not fixed (out of this session's scope): `--palm-real` does not reach the kinematics;
  Tuesday's thumb-0.9-and-pinky-0.9 signature (V2_STRATEGY: the hand low) maps to the "forward" correction, and pinky 0.9 with the
  thumb stalled counts as a hold under the signature rule, so the "low" correction almost never fires. Both matter for grasps only.
- The other 111 findings in `V2_REVIEW_findings.json` are not triaged.
