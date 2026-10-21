# hackathon/brain: the drinks-host loop as one long-running program (v2)

One process on PC2 (the G1's Jetson Orin NX) that keeps the robot, the head camera, the YOLOE detector, the BrainCo hand, the
C922 mic/camera and the llama-server connection warm, and runs the bench loop order after order. v1 (2026-10-19/21) merged the verified
spike scripts; v2 follows `V2_STRATEGY.md` (the reviewed redesign) and `DESIGN_REVIEW.md`: orders by any description of a can, reach by
a feasibility search over the forearm yaw on the URDF arm model with the real palm point (no lane, no `--dx`), the hand placed by the
model and then servoed in the head camera, the approach with the measured joint correction re-applied every step, corrections chosen
from the finger stall pattern, the lift verified by the can rising in the head frame, the handover inside the head camera's view, and
every measured number in `calib.json` with provenance.

```
IDLE > LOOK > LISTEN > UNDERSTAND > CONFIRM > LOCATE > PICK (SERVO, APPROACH) > VERIFY > LIFT > CHECK > HANDOVER > (RECOVER) > IDLE ...
```

| Stage | What happens | Decided by |
| --- | --- | --- |
| LOOK | fresh D435i frame, YOLOE can boxes, one short Gemma description per crop ("purple sprite", "silver chi") plus the measured size class and position in code ("silver chi, slim, on the left") | Gemma + code |
| LISTEN | TTS "Tell me which one you'd like.", 4 s `arecord` from the C922, up to 3 attempts; after one `none` the honest negative ("I do not see that. I see purple sprite and silver chi."), after two the ambiguity question ("The purple sprite one, or the silver chi one?") | scripted |
| UNDERSTAND | Gemma hears the clip (any language) with the numbered descriptions in the system prompt and answers the number, or `none` | Gemma |
| CONFIRM | TTS "The silver chi one. Coming up." | scripted |
| LOCATE | fresh frame, the chosen can matched to the new boxes (IoU, else by description), axis = box depth (front surface) + half the classified diameter (55 / 66 mm), the table plane from the depth band beside and under the can (level RANSAC on the points within 6 cm of the can base, the height read from the inliers: `geom.table_plane`), the hard safety (nothing within 0.30 m straight ahead at chest height, at least 70% valid depth or it refuses, the robot's own arm not counted), then the plan | code (geometry) |
| plan | `geom.plan_reach`: the real palm (0.246 m along the wrist-roll axis) at the can axis minus (r + 1 cm) along the palm normal n = d x z, 1.5 cm below the mid-height from the table plane; forearm yaw psi from -30 to 60 deg in 5 deg steps visited outward from the preferred yaw; a 4-joint IK with the yaw held hard (pitch is an outcome); every pose (grasp, pre-grasp 3 cm out, each 1 cm approach pose, the high waypoint) must solve within 5 mm, keep the lower upper arm / forearm / hand 1.5 / 4 / 6 cm from the torso bands (mesh extents per height band), the hand 5 cm from the right arm, every joint 10 deg from its limit, the forearm within 15 deg of level, the palm's lowest point at the table; the smallest pitch wins, ties to the smaller yaw; refusals name the constraint | code |
| PICK | tuck (home), raise from the shoulder (position-only IK, the hand's roll kept; every target recorded as it streams), reach high (the wrist roll blended along the path): both uncorrected, their error logged as the sag baseline (Tuesday 1.9-2.6 / 2.5-4.7 cm; over 7 cm refuses); lower to the pre-grasp with the sag fed forward (stopping 2 cm above, then the last part with the sag measured there), then corrections streamed in capped sub-steps until the measured real palm is within 6 mm; nothing below the table plane + palm half-height + 5 mm; a correction the hand does not follow, or a corrected error over 2 cm, refuses (`motion.Arm`); every path solved before it moves; no joint changes more than 0.02 rad x speed in one 20 ms target | scripted skill |
| SERVO | one head frame gives the can (YOLOE + depth) and the hand (depth blob above the table plane, the cans' own points removed by 3D distance, the front 12 cm of the arm blob along d) in the pelvis frame; features = fingertip front along d, nearest face along n, median z; with the hand constant K (measured once at an owner-approved aligned pre-grasp) the error e = (axis + K) - features drives (e_d, e_z) with clipped 3 cm nudges until both are under 1 cm on two frames (budget 3); a blob touching the image border, its search window (200 x 170 px around the hand, grown once) or its radius is not used; Gemma's box of the robot's hand on the first frame must lie on the blob (50% overlap) or the order ends; without K it measures and logs only, and an order refuses to grasp unless `--model-grasp` | sensor gate |
| APPROACH | thumb opposed, then along +n in 1 cm steps on the line from the start, each re-applying the measured joint correction; the gap is measured: the closure pose from the latest measured can axis minus the measured palm, and the visual near-face gap from the last reading taken clear of the can (model gap >= 2 cm) minus the measured advance; the larger counts and only while they agree within 1 cm: no visual gap or a disagreement means no close; half way, a fresh frame (the can moved > 1.5 cm = pushed, abort); the hand closes only when the measured gap is under 1 cm; a tracking-error rise to 2x the baseline, a cumulative lag of 1.2 cm or an advance beyond the standoff + 1.5 cm is an abort, never a close | code + sensor |
| close | fingers 0.9, thumb lock 0.9 (`--no-thumb-lock` keeps the thumb opposed only); the hand state logged after each stage | scripted |
| stall pattern | hold signature (thumb < 0.3 and 3 of 4 fingers in 0.25-0.70) / forward (thumb 0.9, fingers stalled) -> open, +3 cm along d, re-close / low (pinky 0.9, thumb not stalled) -> open, +2 cm up, re-close / empty (all 0.9) -> re-detect: moved > 2 cm = pushed, else -3 cm along d, re-close; one correction, then the retry and the assisted path | sensor gate |
| VERIFY | the hold signature (`--verify strict` for v1's every-finger rule) | sensor gate |
| LIFT | 6 cm with correction; the can's point in the head frame must rise by 6 +- 2 cm, otherwise it is a miss whatever the stall says | sensor gate |
| CHECK | third-person C922 frame, Gemma "Is the robot holding the soda can in its hand, off the table?" (advisory) | Gemma advisory |
| HANDOVER | offer pose = the calibrated delta from the lift moved forward / toward the midline / up until the real palm projects inside the head camera's view; release on a tug (a stalled finger closing 0.03 further on two cycles with the setpoint re-sent), a new depth cluster within 6 cm of the can on two frames confirmed by one Gemma yes/no, a let-go transcript (never within 2 s of the robot's own sentence), the `r` key or `--release-after` | sensor gate + Gemma |
| RECOVER | unknown order: honest negative, no motion. No plan: the constraint spoken. A can cut off by the image border: refused ("move it toward my centre"). Miss: one mapped correction, retry once (a refused locate ends the order), then the assisted placement verified by the signature. Every failure, abort and quit goes home on a path planned and keep-out checked before any motion: on the recorded raise, the raise retraced from where the arm stopped; over the table, up (only until 5 cm from the can), back to the raise end, the raise retraced; joint space only from below the table top behind the raise. A refused or stopped move holds the arm (stuck): a spoken reminder every 30 s, `h` plans the way out and says it, `y` runs it, `quit!` exits without releasing (after L2+B) | scripted |

Every order ends with the arm held at home (g1-fetch's home_q, the real palm at (0.194, 0.267, -0.174) beside the hip, below the
table top; `--park release` releases it there, announced). The arm is enabled only with `--table-edge` (the keep-out on every raise,
retreat, home and park path) and only when it hangs below the table top behind the raise at start; it is never released away from
home (g1-fetch then ramps the arm_sdk weight to 0 and the controller takes the arm back in a joint-space move). Every move is announced
("Raising.", "Reaching.", "Lowering beside the can.", "Up and back.", "Home.", "Releasing my arm."); `--dry` never enables the arm.
The arm service is switched off once at start and on at exit. `q` / Ctrl-C / SIGTERM bring the arm home first, then open the hand
(thumb last) and release it; a second `q`, `a` or Ctrl-C during that stops the arm where it is (stuck).

## Files

- `brain.py`: the state machine and the main loop. `python brain.py -h` lists every parameter; defaults come from `calib.json` and an
  override is logged as a `deviation`. `--probe` is the kill test (experiment 2 of V2_STRATEGY: pre-grasp, 5 measurements of the hand
  features and the can, no approach); `--air` is experiment 3 (a virtual can: plan, high, pre-grasp, 5 cm along n with the per-step
  correction, back); `--dry` stops before PICK. Keys: `a` abort the order (during a retreat: stop, the arm holds), `q` quit (the arm comes home first),
  `h` (only while stuck) plan the way out, `y` run it, `quit!` exit without releasing (only after L2+B), `r` release the can, `p` no
  new order starts (the arm stays held at home), `o contact=.. pushed=.. grip=.. height=.. note=..` logs the owner's observation,
  Enter starts an order with `--manual` / `--probe` / `--air`.
- `geom.py`: the URDF left and right arm chains (FK equal to g1-fetch's pinocchio FK to 0.6 mm on the logged reach pose), the torso
  as mesh-extent bands, the 4-joint yaw-held IK, the wrist roll from the palm normal, pose checks, the psi sweep (`plan_reach`), the
  RANSAC table plane, the hand blob and features, pelvis-to-pixel projection, the chest-height obstacle check.
- `motion.py`: `Arm`: every move planned on geom's model, its whole path solved before the arm moves, streamed as joint targets
  (speed x `--speed` per 20 ms target); per target a 2 cm palm cap (refused) and a 0.02 rad x speed joint cap (split into
  sub-targets); the wrist roll blended along each path; the sag fed forward on the lowering; corrections streamed in capped sub-steps
  until the measured real palm is within 6 mm, stopped when the hand does not follow; goals and commands floored at the table plane +
  palm half-height + 5 mm; approach steps on a line with one correction each; IK <= 5 mm, 5 degree joint margins, the goal
  cross-checked against g1-fetch's FK; a trail of every target sent (the raise, retraced from wherever it stopped).
- `calib.json`, `calib.py`: every measured number with provenance (value, unit, frame, method, date, pose, can, n, log, validity);
  the brain prints the table at start, logs the sha and the git SHA into every order, logs CLI overrides as deviations, refuses stale
  entries without `--accept-calib`. `hand_feature_K` is null until the kill test measures it.
- `replay_reach.py`: experiment 1 (no robot): the 18 logged can positions of Oct 19-21 through the planner.
- `test_geom.py`, `test_motion.py`, `check.py`: the desk gate (`python -B check.py`, 33 checks in about 75 s): compile, geometry and
  motion tests against values logged on the robot, the replay, calib freshness, the CLI refusals, and 25 mock runs, each checking the
  joint step per target, with the round-1 cases (failing on 2d4f1ca) and the round-2 cases (failing on c39a468; `CHECK_TREE=<tree>`
  runs a case on another version with this mock); see `HANDOFF.md`.
- `gemma.py`: the Gemma calls, each returned as a logged record (`describe_crop`, `hear_choice`, yes/no, transcript, box).
- `preflight.py`: pass/fail table (server, warm-up, geometry self-check, cameras, mic, services, FSM, hands, power, no-cloud).
- `brainview.py`: the page for the laptop, stdlib HTTP + server-sent events, port 8000.
- `mock_robot.py`: Mac-side mock: synthetic RGB-D head frames from the URDF camera mount (table plane, can cylinders, the hand as a box
  at its TRUE position = the model's real palm plus a hidden error, the forearm, an optional obstacle), the URDF FK, a gravity sag fitted
  to Tuesday's 25 uncorrected moves (2.7-4.8 cm at the high waypoints vs 2.5-4.6 logged), contact that holds the measured hand while
  the command runs ahead, closure outcomes from the true palm-to-can geometry, a held can that travels with the hand.
  `BRAIN_MOCK_SCENE`, `BRAIN_MOCK_ORDERS`, `BRAIN_MOCK_HAND`, `BRAIN_MOCK_ERR/ERRK/ERRZ/ERRY` (hidden error), `BRAIN_MOCK_SAG`,
  `BRAIN_MOCK_CONTACT`, `BRAIN_MOCK_OBSTACLE` (`1` or `after:TEXT`), `BRAIN_MOCK_ABORT_AT` (the `a` key at a state), `BRAIN_MOCK_STOP`
  (a, q, Ctrl-C or a g1-fetch failure at a streamed target after a sentence), `BRAIN_MOCK_KEYS` (the operator's keys while stuck),
  `BRAIN_MOCK_TABLE_BIAS` / `_EDGE` (the depth plane low; the table's near edge), `BRAIN_MOCK_DEPTH=zero`, `BRAIN_MOCK_MIN_RANGE`,
  `BRAIN_MOCK_GEMMA_OFF`; the hand meets the real table; `[mock] stats` at exit (joint steps, releases away from home, the reach after
  a stop).
- `runs/` (git-ignored): `live/` for the view; per session `order_NN.jsonl`, frames, clips and replayable frame bundles
  (`bundle_<label>_color.jpg`, `_depth.png` uint16 mm, `_meta.json` with intrinsics, optical-to-pelvis, q_cmd, q_meas, hand state).

## Start on PC2

```bash
# once per boot, owner (sudo): clocks, and free the D435i from the streaming services
sudo jetson_clocks
sudo systemctl stop teleimager-realsense-webrtc.service teleimager-compat.service
# robot in its stand, FSM 500 (R1+X); owner holds the remote on L2+B
~/spike/serve-orin.sh                                 # llama-server, 127.0.0.1:8080, healthy in ~9 s
source ~/miniconda3/etc/profile.d/conda.sh && conda activate g1fetch
cd ~/harness && git pull && cd hackathon/brain
python -B check.py                                    # the desk gate on PC2 too (mock, no DDS)
python preflight.py                                   # table; --venue makes the no-cloud checks hard failures
python brainview.py &                                 # laptop on the robot's AP: http://10.42.0.1:8000
S=$(python calib.py | head -1 | cut -d' ' -f4)        # the calib sha16; the run plan names the expected one
tmux new -s brain "python brain.py --air --manual --park home --expect-calib $S --table-edge E --speed 0.5 --air-table T --air-can 0.38 0.15"   # experiment 3, no can
tmux new -s brain "python brain.py --probe --manual --park home --expect-calib $S --table-edge E"       # experiment 2: the kill test, Enter per can position
tmux new -s brain "python brain.py --K D N Z --manual --park home --expect-calib $S --table-edge E"      # the loop, with K from the kill test
```

`brain.py` changes directory to `~/g1-fetch` itself (so `configs/pc2.yaml` and the detector weights resolve) and imports
`bench/client.py` from this repo; `--g1fetch` or `G1FETCH` override the location.

## Parameters

| Parameter | Default (calib.json) | Meaning |
| --- | ---: | --- |
| `--palm-real` | 0.246 | real palm centre along the wrist-roll axis (g1-fetch's 0.15 + the 0.096 jog) |
| `--pre`, `--grasp-below` | 0.03, 0.015 | pre-grasp standoff along n; palm centre below the can mid-height |
| `--K D N Z` | none | hand feature constant at the aligned pre-grasp (fingertip front along d, nearest face along n, median z, relative to the can axis); without it the brain measures and logs, no servo |
| `--servo-iters`, `--servo-tol`, `--servo-max`, `--frames` | 3, 0.01, 0.03, 2 | iterations, convergence, largest single correction, frames per measurement |
| `--psi`, `--pitch-max`, `--ik-tol`, `--clear` | -30:60:5, 15, 0.005, 0.015 0.04 0.06 0.05 | the sweep, the pitch limit, the IK tolerance, the clearances (upper arm, forearm, hand, right arm) |
| `--contact`, `--lag` | 0.015, 0.012 | aborts during the approach: tracking error over 2x the baseline, cumulative lag behind the commanded advance |
| `--fwd`, `--up`, `--back`, `--no-fix` | 0.03, 0.02, 0.03 | the stall-pattern corrections |
| `--lift`, `--verify`, `--tug`, `--hand-cam`, `--tts-rate` | 0.06, signature, 0.03, head, 0.07 | lift; hold rule; pulled-can threshold; camera for the human-hand question; TTS seconds per character |
| `--near`, `--pause`, `--diam`, `--no-thumb-lock`, `--no-prethumb`, `--park` | 0.30, 4, auto, off, off, home | as named (`--park release` releases the arm at home after each order) |
| `--speed` | 1.0 | in (0, 1]: scales every Cartesian speed, the approach steps and the joint step per target; an override is logged as a deviation |
| `--table-edge` | none (calib `table_edge_m`) | pelvis x of the table's near edge from the tape; required to enable the arm; the keep-out refuses a path whose hand passes within 2 cm of it below the table top + 3 cm |
| `--expect-calib SHA16` | none | refuse to start unless calib.json has this sha16 and the brain tree is clean (every run-plan command) |
| `--model-grasp`, `--pre-offset`, `--pre-stop`, `--stuck-reminder` | off, 0, 0.02, 30 | grasp without K on the model gap (a deviation); the pre-grasp moved back along the forearm (a deviation, for the servo-residual block); the corrected pre-grasp error that refuses; seconds between the stuck reminders |
| `--air-can X Y`, `--air-table T` | 0.38 0.15, none | the air test's virtual can (axis at T + 0.061 + 0.03) and the taped table height in the pelvis frame |
| `--seconds`, `--retries`, `--assist-wait`, `--hold-reminder`, `--release-after`, `--hand-q`, `--orders`, `--manual`, `--probe`, `--probe-can`, `--probe-servo`, `--air`, `--air-can`, `--dry`, `--accept-calib`, `--mock`, `--mock-gemma` | | as in v1 plus the experiment modes |

Frames: pelvis x ahead, y left, z up, metres. For a plan with yaw psi: d = (cos psi, -sin psi, 0) is the forearm direction, n = d x z
the palm normal (toward the can); grasp palm P = axis - (r + 1 cm) n at z = table + h/2 - 1.5 cm; pre-grasp P - 3 cm n; the approach
moves along +n. psi 0 is v1's lateral slide along -y.

## Logs

`runs/<session>/order_NN.jsonl`, one JSON object per line, `ev` in: `order` (parameters), `calib` (sha, git), `deviation`, `say`,
`record`, `gemma`, `scene`, `detect`, `target`, `plane`, `safety`, `plan` (psi, pitch, the checks of every pose, every candidate tried),
`move` (goal, measured, error, psi, pitch, q_cmd, q_meas), `measure` (can, blob, model palm, `feat`, `off` = features - axis, `model_off`,
`err` vs K, blob count, scatter, Gemma's hand box), `servo`, `ap_step` (per approach step: moved, remaining, tracking, base, q), `approach`,
`hand` (per close stage), `stall`, `verify`, `lift_check` (rise, seen), `offer`, `hold`, `cluster`, `taken`, `release`, `obs` (owner),
`park`, `home` (how), `keepout` (each path's reach below the table top), `safety_check` (valid depth, zone points, own-arm points), `stuck`,
`way_out`, `exit_holding`, `stage`, `error`, `result`. `runs/<session>/orders.jsonl` holds one summary line per order. Frames: `look.jpg`, `locate.jpg`,
`measure_<label>.jpg`, `cam3_<stage>.jpg`, `hold_NN.jpg`, the `bundle_*` frame bundles; clips `order_N.wav`, `hold_NN.wav`.

## Validation so far

After the second review (`V2_REVIEW.md` round 2, fixed in 8e226e9, `HANDOFF.md` has the details): the desk gate passes 33 of 33 in about
75 s; each of the five round-2 blockers has a case on a path the verifiers did not use, and each fails on c39a468 with the same mock (a
0.394 rad wrist step in one target; a joint-space home reaching x 0.350 / 0.347 below the table top after a stop in the raise / the
descent; the retry walking the arm 5.3 cm out; the arm released over the table on a second `q`; a second Ctrl-C ignored for 368 targets;
the command 3.4 cm into a table seen 20 mm low; forward errors of 3.9 / 5.4 cm read as 7 / 1 mm). Found on the way: the table plane under
a can near the table's edge was the floor (fixed); the high waypoint leaves the hand below a 13.5 cm can's top, so a transit path across
another can sweeps through it (left for the grasp session; not on the air test or the kill test's path).

After the review (`V2_REVIEW.md`, fixed in c39a468, `HANDOFF.md` has the details): the desk gate passes 13 of 13 in 46 s; the code
blockers and the closure rule each have a case that fails on 2d4f1ca (a 4.7 cm correction refused by the cap; a joint-space park at zero
from beside the can; `--dry` enabling the arm; the air test ignoring the 0.30 m rule; closing on a tracking-error abort with 1.5 cm left).
The home move from the raise waypoint now retraces the raise: the 2d4f1ca joint-space path put the fingertips at the table-top height
38 cm ahead.

On the Mac (2026-10-20, `check.py`): the URDF chain matches g1-fetch's FK to 0.6 mm on the reach pose logged on 2026-10-18 and three
logged (q, IK target) pairs differ by exactly their logged IK errors; the yaw-held IK reproduces V2_STRATEGY's worked example (can at
(0.35, 0, 0.13), psi 30: IK 0 mm, pitch 1.4 deg, elbow (0.069, 0.205, 0.130), joints (-16, 22, -29, 2) deg). Experiment 1 (replay of 18
logged can positions): every grasped position is accepted at psi 0-25 with the elbow 4-11 cm clear; the Oct 19 centre-line block
[0.347, 0.008] is rejected at psi 0 (inside the torso) and accepted at psi 20-40; the refused dry-run can [0.401, 0.03] is feasible at
psi 15-30; a can 10 cm right of centre at psi 45; pitches within 2 deg. The seeded mock order (hidden palm error 1.1 cm beyond the
model plus 4 cm/rad of elbow) runs autonomously: three cans described with size and position, the spoken choice matched, plan psi 10,
the servo converging to 9 mm in one iteration, the approach stopped by contact at the can, the hold signature, the lift seen in the
head frame (+6 cm), an in-view offer pose, release, retreat, park. A can right of the centre line with a neighbour is refused with the
reason; an unknown order gets the honest negative.

Real Gemma 4 E2B on the Mac llama.cpp: descriptions "Purple Sprite" (a La Croix; the brand is misread at 136 x 160 px), "Silver Chi",
210-250 ms, a textureless crop "Grey, unknown"; the spoken choice against the numbered list: the office clips purple -> 1, white in
another language -> 2; 11 synthetic clips (English, Spanish, French, Chinese; colour, brand, flavour, position, "a coke please" -> none)
all sensible, 114-142 ms (expect about 2x on the Orin).

Findings that changed the design on the Mac: a servo correction must move the MEASURED palm (the arm's sag, 3.4 cm on the Oct 19 pose,
otherwise doubles into every correction); the hand's nearest face along n is hidden by the can from the head camera near closure, so
the approach distance comes from the model and K is measured at the aligned pre-grasp; the hand blob must exclude the cans' points by
3D distance (a 2D box clips the hand behind the can and shifts the fingertip feature with distance).

On the robot (v1, 2026-10-21, `spikes/office-tue-brain/`): 4 grasps in a row after the axis fix at can y 0.09-0.13, then misses at
y 0.07-0.085; colour from audio 255-342 ms, crop colour 313-364 ms, yes/no 304-340 ms, build 11.1 s.

**Not yet measured on the robot (v2):** experiment 3 (the swivel and the corrected slide in the air: tracking baselines, elbow-to-torso
gaps by the owner's eye, slide-end z error), experiment 2 (the kill test: the hand features at the pre-grasp at three can positions,
their scatter over five frames, the measured-minus-model offset, one correction's residual), the hand constant K, the torso thresholds,
the offer pose in the real camera's view, the description quality on the demo cans, and the ten-order run.
