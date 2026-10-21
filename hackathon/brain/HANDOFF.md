# Handoff: brain v2 (2026-10-20)

What the build session leaves for the robot session. Nothing here has run on the robot; what cannot be checked offline is named below with the reason and the no-motion check that covers it.

## Commit

- Hash, branch: `103d21e` on `hackathon` (pushed; PC2: `cd ~/harness && git pull`)
- Files changed (names only): `hackathon/brain/brain.py geom.py motion.py calib.py calib.json gemma.py mock_robot.py preflight.py brainview.py README.md replay_reach.py test_geom.py check.py`

## Passed offline, with numbers

| Check | Command | Result (n, error, counts) |
| --- | --- | --- |
| `check.py` | `~/miniforge3/envs/brain/bin/python -B hackathon/brain/check.py` | PASS: compile, test_geom (4 tests, incl. the memo's worked example), replay_reach (18 positions), calib (no stale entries), one seeded mock order to `success (autonomous True)` in 23 s |
| FK vs g1-fetch | `test_geom.py` | the URDF chain = pinocchio FK to 0.6 mm on the 2026-10-18 reach pose; three logged (q, IK target) pairs differ by exactly their logged IK errors (0.0068 / 0.028 m) |
| IK vs V2_STRATEGY | ad hoc | can (0.35, 0, 0.13), psi 30: IK 0.0 mm, pitch 1.4 deg, elbow (0.069, 0.205, 0.130), joints (-16, 22, -29, 2) deg: identical to the memo's worked example; psi 0 puts the elbow at (0.004, 0.047): inside the torso |
| Replay (experiment 1) | `replay_reach.py` | 18 logged can positions with the memo's thresholds (upper arm 3 cm): every grasped position accepted at psi 0-25 with the lower upper arm 4.4-10.6 cm from the torso bands; the Oct 19 centre-line block [0.347, 0.008] rejected at psi 0 (upper arm and forearm inside the torso) and accepted at psi 20-40; the refused dry-run can [0.401, 0.03] feasible at psi 15-30; a can 10 cm right of centre at psi 45; pitches within 2 deg |
| Mock | `BRAIN_MOCK_SCENE=three BRAIN_MOCK_ORDERS=silver,black,red BRAIN_MOCK_ERR=0.11 BRAIN_MOCK_ERRK=0.04 brain.py --mock --mock-gemma --orders 3 --K 0.062 -0.052 -0.002 --release-after 5` | order 1 (can at y 0.12): psi 10, servo residual 9 mm, approach 3 steps to contact, hold signature, lift seen (+5.3 cm), in-view offer, release: autonomous. Order 2 (can 8 cm RIGHT of centre): psi 30, one 1 cm servo correction, approach 4 steps to the closure pose, hold, lift seen, release: autonomous. Order 3 (absent description): honest negative, then the ambiguity question, refused. Forced thumb-0.9 and pinky-0.9 patterns each recovered with one correction (earlier run). |
| Perception (Mac Gemma) | ad hoc | descriptions of the office crops "Purple Sprite" (a La Croix, brand misread at 136x160 px) and "Silver Chi", 210-250 ms; a textureless crop "Grey, unknown". Choice against the numbered list: office clips purple -> 1, white in another language -> 2; 11 synthetic clips (en, es, fr, zh; colour, brand, flavour, position, "a coke please" -> none) all sensible, 114-142 ms |

## Cannot be checked offline

| What | Why | No-motion check in the run plan |
| --- | --- | --- |
| The hand blob in the real head camera (dark glove, D435i depth on it, the window around the model palm) | the mock renders a box; the real hand's depth return and visible shape are unknown | kill test: 5 frames per position, the `probe:` line (blob count, scatter, feat - axis) and `measure_probe.jpg`; `--gemma-hand` prints the Gemma box vs the blob |
| The hand constant K | needs an owner-approved aligned pre-grasp | kill test: the owner's `b/c/f`, `l/o/h` judgement at the pre-grasp; the `off` of the approved pose becomes `hand_feature_K` |
| Torso clearance thresholds (0.015 / 0.04 / 0.06 / 0.05 m) and the mesh bands | derived from meshes and logs, not from the stand with straps | air test: the owner's eye on the elbow-to-torso and elbow-to-stand gaps at psi 0, 35, 45 |
| The real tracking baseline per pose and the lag of a corrected step | the mock's sag is synthetic | air test: `baseline` and `ap_step` lines (tracking, moved) |
| The offer pose inside the real camera's view | the URDF camera pose is used, not a measured one | handover: `offer` event `in_view`, the live frame on the view |
| Description quality on the demo cans and the choice from the C922 | Mac crops only | `--dry` orders with the real cans and the owner's voice, before any motion |
| The pulled-can tug (0.03 on a stalled finger, two cycles) and the depth-cluster cue | never exercised on a real hand | handover with the owner's hand, judged live; `hold`, `cluster`, `taken` events |

## How to run it

```bash
# PC2, after the owner's per-boot steps (jetson_clocks, camera services stopped, serve-orin.sh, FSM 500, L2+B)
source ~/miniconda3/etc/profile.d/conda.sh && conda activate g1fetch
cd ~/harness && git pull && cd hackathon/brain && git log --oneline -1          # expect 103d21e
python -B check.py                                                              # expect CHECK: PASS (the mock, no DDS)
python preflight.py                                                             # expect PREFLIGHT: PASS; `geom` PASS "FK error 0.6 mm"
python brainview.py &                                                           # http://10.42.0.1:8000
# no motion: the scene and the plan only
tmux new -s brain 'python brain.py --dry --manual'                              # Enter per order: "scene: ...", "target ... plane ...", "plan: psi N ..." or the refusal reason
# experiment 3 (air): no can within 30 cm of the targets; Enter per target
python brain.py --air --manual --air-can 0.38 0.15 0.13                         # expect "plan: psi 0-10", up/high/pre lines err < 0.010, "tracking baseline", five ap_step lines with moved ~0.010
python brain.py --air --manual --air-can 0.35 0.00 0.13                         # expect psi ~35; owner: elbow gaps >= 5 cm
python brain.py --air --manual --air-can 0.30 -0.05 0.13                        # expect psi ~45
# experiment 2 (kill test): one can; Enter per position (y ~0.15-0.18, ~0.10, ~0.05-0.07)
python brain.py --probe --manual                                                # expect "probe: can ... hand feat ... (N pts) ... off(feat-axis) [d, n, z] ... gemma hand vs blob 0.0xx"; the robot speaks the millimetres
# the loop, once K is known
python brain.py --manual --K D N Z                                              # one can, three positions; then two cans and an absent description; then --orders 10
```

## Parameters and calibration

- `calib.json` entries read (sha printed at start and logged per order): palm_real_m 0.246, palm_half_height_m 0.045 (assumed), grasp_below_mid_m 0.015, palm_to_axis_m 0.01, pregrasp_standoff_m 0.03, can_diameters_m, torso_bands, clearance_m (0.03 / 0.04 / 0.06 / 0.05 per the memo), table_clear_m -0.01, pitch_max_deg 15, ik_tol_m 0.005, lift_m 0.06, lift_rise_tol_m 0.02, offer_delta_m, offer_search_m, camera_pose (URDF), pelvis_height_m 0.84, contact_rise_rad 0.015, hold_signature, high_rise_m 0.12, raise_ahead_m 0.05, raise_side_y_m 0.18, retreat_out_m 0.05, approach_step_m 0.01, fingertip_m 0.08, cluster_radius_m 0.06, near_ahead_m 0.30, hand_feature_K null.
- Deviations from V2_STRATEGY.md, each with its reason in the file: (1) the table rule is "the palm's lowest point may touch the table" (-0.01) instead of ">= 1 cm above it", because with grasp z = table + h/2 - 1.5 cm and a 4.5 cm palm half-height every 12-13.5 cm can would be refused; trial 8 had the pinky edge at the table; a tape measurement of the palm half-height settles it. (2) The approach distance comes from the model (the closure pose minus the measured palm along n), not from the hand's nearest face, which the can hides from the head camera near closure; e_n is logged. (3) K is measured at the aligned pre-grasp, not at the closure pose, for the same occlusion reason. (4) Without a table plane the order is refused ("I cannot see the table"), never the box-centre depth.
- CLI overrides the plan allows (each logged as a deviation): `--K` (from the kill test), `--clear` and `--psi` (only after the owner's air-test gaps disagree with the bands), `--pause`, `--release-after` (rehearsal only).

## Open risks

- The park pose (joint zero) puts the real palm about 36 cm ahead, 15 cm left, at table height: a can standing there is hit when the arm parks. Keep the slots outside that spot or park with `--park home`.
- The raise is position-only from the home pose beside the body; the high move blends the yaw inward at +12 cm above the pre-grasp. For a can right of centre the forearm crosses in front of the chest at that height: the air test must confirm the gap by eye before any can is there.
- The hand's nearest face along n is hidden by the can from the head camera near closure, so the approach distance comes from the model; if the model's lateral error on the robot is larger than the mock's millimetres, the contact abort (2x the baseline) is the backstop and the `end` measurement shows the gap.
- The servo window around the model palm assumes the real hand is within 16 cm of it; a larger model error leaves "hand not seen" and the order proceeds on the model (logged).
- Descriptions: Gemma misreads brands on small crops; the demo cans should differ in colour. The choice prompt lists size and position words, so "the tall one" / "the one on the left" work.
- The mock's camera view is narrower on the left than the real D435i's; a can at y >= 0.19 puts the hand out of the mock view, the real limit is unknown.
