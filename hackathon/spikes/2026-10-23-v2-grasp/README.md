# 2026-10-23 (Fri, office, PC2 over ssh): brain v2 dry run without tape, the reach taught by hand, a level table fit

Robot in its stand, FSM 500; the owner ran `jetson_clocks` and stopped the camera services; E2B server via `serve-orin.sh`; preflight
PASS (the three no-cloud warnings only). Brain code `7869c62`, calib sha16 `ae553548d47b677a`. Driver: the owner's review session.

**Deviation from the approved plan** (`hackathon/briefs/2026-10-21-v2-kill-test.md`), on the owner's direction: no tape numbers (the
table and its edge come from depth), no air test and no kill test; instead one dry run, then the reach calibrated by hand-guiding the
arm with `hackathon/spikes/scripts/teach_reach.py` (new). The arm moved only under the owner's hand (kp 0) or holding still (kp 60),
plus two slow returns home (2.1 s and 1.5 s). L2+B (damping) is not usable for hand-guiding: the legs go limp and drop the robot.

## Dry run (`20261024T022515/`, `console/dry-3cans-1.log`)

- LOOK, three cans (Gemma per crop, 407-539 ms): "silver song forest apple" (the can shows a lychee), "silver chi peach", "silver chii
  sparkling" (no fruit named). The fruit picture must face the robot.
- LISTEN: the three clips transcribe (Gemma) as "The water manner", "ठीक", "Hm."; hear_choice answered none, none, then **1 on "Hm."**
  (a pick from no order). Fixture for the order step: `order_01/order_3.wav`.
- LOCATE: target (0.52, 0.157, 0.035), plane -0.077: "out of my reach" (correct). From the same depth frame (`table_from_depth.py`,
  scratch): floor -0.852 (pelvis 0.852 above it; calib 0.84), desk -0.081 level within 4 mm over x 0.40-0.70, near edge x 0.40.

## Reach

- v2 planner (`geom.plan_reach`, the brain's thresholds), 165 can cells x 0.28-0.56, y -0.14..0.26, by table height and forearm-pitch
  limit (15 = calib): desk 77 cm 0 / 34 (pitch 25) / 61 (35); +5 cm 21 / 79 / 85; +10 cm 90 / 101 / 101; +15 cm 111 / 113 / 113. The
  pitch limit, not the arm, closes low tables. The owner raised the standing desk to about 88 cm (table z +0.045).
- `teach-2/` (soft, unlabelled: the labels were typed without Enter): 211 soft frames, 7 of 9 grasp-height spots the hand reached
  (palm 3-7 cm above the desk) are accepted by the planner; the two refusals sit at the 15 deg pitch limit. Analysis:
  `teach-2-analysis.txt`. The camera check there is unusable: the recorder has no can detector, so the cans and the owner's hand
  merged into the hand blob.
- `teach-3/` (held still, hands away, no cans near the hand, 6 poses x 3 frames): the 3 frames of a pose agree within 1 mm. The black
  glove's fingers return little depth, so the depth blob ends at the palm (p5: front 4.5 cm behind the model palm). Only p5 is fully
  in view (p1, p4 at the left/top edge, p2 at the bottom edge; p3, p6 took the cans at the back of the desk). In colour
  (`teach-3/pose_0018.jpg`) the model palm point (green) sits on the finger base, about 4 cm ahead of the palm centre by the URDF
  hand proportions; teach-2 hinted about 5 cm (`pose_0049.jpg`). This fits `palm_real_m` 0.246 being the grasp point found by the Oct
  19 jog rather than the palm centre; the hand box around it (`fingertip_m` 0.125 ahead in the plan, `hand_back_m` 0.045 behind) is
  then probably off by about 4 cm. n = 1 clean pose: calib not changed.

## Fixed today

- `geom.table_plane`: tables are level (owner). The free RANSAC fit leaned 3.4 deg (dry run) to 16 deg (through can sides) while the
  IMU read pitch 1.1 deg, the floor was flat and the desk level within 1 cm; it is now the modal height as a level plane, refusing a
  flat histogram (can sides, no table). `check.py` 84 of 84 on the Mac; 8 synthetic scenes right.
- `teach_reach.py`: the floor was fitted as the table (fixed); the first D435i frames after opening read the desk at 0.187 m (2 s
  warm-up, the table re-measured per pose); a label typed while soft now holds the arm, says "Hands away" and records after 3 s.

## Grasps (afternoon, `runs-pc2/`, `console/grasp-N.log`)

Desk raised to about 88 cm (table z +0.045-0.054 from depth), near edge x 0.365 from depth; the Chi Sparkling Pomelo Zest can
(66 mm) about (0.40, 0.14-0.20). Every run: `--orders 1 --park home --model-grasp --speed 0.5 --table-z 0.048 --table-edge 0.365
--fingertip 0.125 --palm-half-height 0.045` (table and edge from depth, not tape; no K: the kill test was not run). The owner on the
robot and the stop keys; the agent drove from the Mac. Second try within an order = the brain's own retry.

| Run (code) | Order heard | Pre-grasp error | Approach | Close / hold signature | After | Result |
| --- | --- | --- | --- | --- | --- | --- |
| 1 `033336` (`10c1b8d`) | lemon | - | - | - | stopped at the stop 2 cm over the pre-grasp: the hand settled 7 mm above it (corr_tol 6 mm), nothing under it (C922) | false contact, hold, home on `y` |
| 2 `034032` (`2d04e98`) | "apple" (left can) | 3 / 4 mm | pushed the can 1.8 / 1.5 cm from a model gap of 2.3-2.5 cm | owner placed the can: 0.51, GRASPED | Gemma "in hand" said no; released on the owner | assisted |
| 3 `034634` | water | - | - | - | can at the image edge | refused, no motion |
| 4 `034752` (`2fa1446`) | number one | - | 4 steps, closing at gap -0.006 | **0.47, GRASPED on its own** (thumb 0.19, fingers 0.38-0.54) | lift 6 cm; camera rise 0.002 (tilted can cut by the left image border) = "miss": the hand opened, the can fell | dropped |
| 5 `035520` (`d62542d`) | the left one | 2 mm | 5 steps, gap 0.004 | **0.47, GRASPED on its own** | lift 6 cm; camera rise -0.002 (box 10 px from the border) = "miss": the hand opened, the can fell | dropped |
| 6 `035958` (`109c1ca`) | the left one | 3 mm | 3 steps, gap 0.004 | **0.47, GRASPED on its own** | lift 12 cm (camera rise 0.109, logged only); offer goal (0.442, 0.219, 0.474) reached (0.468, 0.221, 0.398): 7.6 cm sag, about 1.24 m above the floor; "take it" heard as "A cake." / "Packet"; released on `r` ("Enjoy.") | held: no way home |

Changes made on the robot day, each committed before its run: `2d04e98` the stop's rest check gets its own tolerance (calib
`pre_rest_tol_m` 0.015); `2fa1446` calib `palm_to_axis_m` 0.01 -> 0.035 (the push onsets) and `geom.plan_reach` reads it (was a
literal), offer +0.18 z; `d62542d` image-border rule for the lift check (superseded); `109c1ca` no camera veto after the grasp
(owner), calib `lift_m` 0.06 -> 0.12, `offer_delta_m` [0.06, 0.0, 0.24].

Learned:
- The v2 motion layer places the hand beside the can within 2-4 mm on every run (sag fed forward 2.2-2.5 cm, 0 correction rounds).
- With the closure 2.5 cm farther out the hand closed with the hold signature 3 of 3 (runs 4-6): v2 grasps on the model alone at a
  can about 40 cm ahead and 14-15 cm left.
- The box-centre point of a held, tilted can is not its height (the median depth of its box falls on the table behind it): 0.2 and
  -0.2 cm rises for 6 cm lifts. At a 12 cm lift it read 10.9 cm.
- When the brain exits (`quit!`) with the arm away from home, the controller keeps the last arm_sdk target: the arm stayed at the
  offer pose (palm (0.461, 0.217, 0.428)), stiff, FSM 500. The arm service was left off.
- The head camera's 56 deg view puts cans more than about 15-18 cm left at the image edge (refusals in runs 3 and 5's retry).

## Open (for the next session)

- **The way home from the new offer pose.** `plan_retreat` has no path from above and ahead of the raise end: up first, back at that
  height, then the joint-space bridge, which must start within 5 cm of the raise end (run 6: 0.254 m), so every handover at the new
  offer ends in a hold. Needs a checked descent (back over the edge, then down to the raise end behind it) before the next run.
- The release: the let-go words were misheard ("A cake.", "Packet"); the tug did not fire (unknown whether the owner pulled); the
  head-camera cluster cannot see the raised offer. Run 6 was released with `r`.
- `check.py` on the Mac: 82 of 86 pass; servo, contact, fwd39, fwd54 fail since `palm_to_axis_m` 0.035 because the mock hand is the
  model hand (it now closes 2.5 cm short). Give the mock the real hand's near face. The unfinished stop-rest motion test is
  `wip/test_motion_stop_rest.patch` (its object case pushes 16.5 mm on the old and the new code alike).
- Identification (next session, other lighting): names change between looks (Sprite, iced tea, water, apple for lychee, peach,
  pomelo), a pick on "Hm." and "They aren't", back-of-desk cans counted.
- The hand's depth: white tape or a tag on the back of the hand, or the fingertip from the colour silhouette; RGB 1280x720 would widen
  the view to about 69 deg (now 56 x 43 deg) but not fix the depth and changes every pixel window in the brain.
- The kill test (K) was never run; the run plan's `CODE 7869c62` lines name the old commit.
