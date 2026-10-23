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

## Open

- The order step picked a can on "Hm."; LOOK named a lychee "apple" and missed a fruit (crops are about 70 x 130 px).
- The hand's depth: white tape or a tag on the back of the hand, or the fingertip from the colour silhouette; RGB 1280x720 would widen
  the view to about 69 deg (now 56 x 43 deg) but not fix the depth and changes every pixel window in the brain.
- The hand box around the palm point (above); the kill test measures it with a can. The run plan's `CODE 7869c62` lines name the old commit.
