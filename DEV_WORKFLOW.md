# Robot development workflow: design, code, test on the G1

Scope: every feature that ends on the robot, from the hackathon demo to the fridge fetch. Companion to `CLAUDE.md` (bench hygiene) and `HACKATHON_PLAN.md` §2 (what is verified, with n). Hard robot rules live in `hackathon/ROBOT_RULES.md`.

## 1. Why

- Oct 18 and 19 (`hackathon/spikes/2026-10-18-orin-sunday.md`, `2026-10-19-office-grab.md`) worked: a no-motion measurement before every motion, one parameter per trial, one JSONL line plus a frame per stage (`office-mon/grab_trials.jsonl`), the owner's eyes picking the jog step (`dx -0.096`). Eight grasps in a row followed.
- Oct 20, Tuesday (`hackathon/spikes/office-tue-brain/README.md`, whose note is dated 2026-10-21 CST, `hackathon/brain/DESIGN_REVIEW.md`) did not: one 1000-message session designed, built, deployed and drove; the robot was used to find a 3.3 cm frame bug (front surface vs can axis) that a ten-line test on the jog log would have caught; `--dx -0.06` and the lane bounds were tuned on battery before the cause was known.
- The Oct 19 stepping incident had the same shape: a sign inversion in a perception-to-motion loop reached the robot without an offline check; L2+B caught it.
- The decisive inputs on every good day came from the owner ("the table edge blocks the fingers", "centred at step 4", "2 cm lower holds better") and are stored as prose written afterwards, never next to the hand state they explain.
- Robot minutes are scarce (about 100 usable per charge, owner present, every miss risks the hand); Mac minutes are free. Only what cannot be computed goes to the robot.

## 2. The loop

Six stages, each gated by the one before; the robot is stage 4 only.

**S0 Run plan (agent writes, owner approves, 30 min).** Input: the last session note, `HACKATHON_PLAN.md` §2, `calib.json`. Output: `hackathon/briefs/<date>-<slug>.md` from `hackathon/templates/RUN_PLAN.md`. The owner checks physical plausibility (reach with the stand straps on, table height, which cans exist) and answers measurement questions with the tape. A plan that "tunes a constant" without a named cause goes back.

**S1 Desk (Mac, seconds).** `python3 -B hackathon/brain/check.py` in `~/miniforge3/envs/brain`: ast parse, `unittest discover hackathon/brain/tests`, `lint_literals.py`, seeded mock runs, fixture replays. Tests cover frames and units (the can point is the axis, `dx` is relative to it, the lane is in axis coordinates), the sign of every perception-to-motion mapping (the Oct 19 bug as a test), FK against logged joint states, camera coverage of the offer pose, the TTS gate. Gate: green, or `deploy.sh` refuses to sync.

**S2 Mock (Mac, minutes).** `brain.py --mock --mock-gemma --orders 10` over scenes two/one/none/centre. `mock_robot.py` loads its palm error from a seed the brain cannot see (`BRAIN_MOCK_ERR`), so green means the servo converges on errors it did not know. A mock is trusted only once it reproduces known failures: the Oct 20 fingertips miss with diameter 0, Oct 19 trials 1-4, the eight grasps at -0.096, the `approach_can` divergence.

**S3 Perception (Mac or PC2, robot off).** YOLOE, the Gemma questions and the localizer over `hackathon/data/<date>-<scene>/` (raw RGB and depth, intrinsics, optical-to-pelvis transform, tape ground truth) with the `CLAUDE.md` hygiene: rotated images, `-np 1 --cache-ram 0`, serial, n per class. Localization error against the tape is the number the servo design needs and does not exist yet.

**S4 Robot session (100 min of one charge).** Section 4. Executes the plan; never redesigns, never edits code on PC2.

**S5 Post-mortem (same day, robot off, fresh session).** `pull_runs.sh`, `session_report.py`, the note `hackathon/spikes/<date>-<tag>/README.md` with the per-run table and one root cause per miss or "unknown, needs X"; each incident traced to the stage that should have caught it, the regression test added there, one line in `hackathon/INCIDENTS.md`; `calib.json` and the plan's verified table updated; the next plan drafted. A post-mortem that cannot name a cause schedules a no-motion measurement, not a parameter.

Who does what: the agent writes plans, code, tests and notes, drives the runbook over ssh, reads logs; the owner approves plans, builds and measures the rig, judges by eye and hand, holds L2+B, keeps time and battery, debriefs.

## 3. Artifacts

| Path | What it is |
| --- | --- |
| `hackathon/templates/RUN_PLAN.md` | The pre-robot one-pager: question; the one deciding number and its tolerance; pass criterion with n per class; held fixed (commit, calib hash, can set, taped slots); exact commands with the output lines expected; minutes per block; stop rules; owner tasks; a "bench evidence" section (check.py, mock and replay counts) filled before the robot is switched on. |
| `hackathon/templates/BRIEF.md` | What a Claude session starts from: goal in one sentence, time box in messages, at most six files to read, the verified/not table, what the session must leave behind. |
| `hackathon/templates/HANDOFF.md` | What a build session leaves: commit hash, what passed offline with numbers, what cannot be checked offline and why (these become the slot's no-motion checks), exact commands and flags, open risks. "We will see on the robot" is not allowed. |
| `hackathon/templates/SESSION_NOTE.md` | The results README: setup table (tape numbers, cans, commit, calib hash), per-run table (params, target, pre_measured, slide, hand_state, obs, result), counts with n per class, one root cause per miss, the test added, calibration deltas, the debrief, open items. The shape of `office-tue-brain/README.md`. |
| `hackathon/brain/calib.json`, `calib.py` | Every measured number with provenance: value, unit, frame, method, session, pose, can, n, who, validity window. Example: `palm_offset_x: -0.096 m, forearm axis, jog_x.py step 4 by the owner's eye, 2026-10-19 office, pre-grasp y 0.23 z 0.14, n 9`. Also `torso_box`, `table_z`, `can_diameters`, `ee_offset_x`, `offer_pose`. `brain.py` loads it, logs its sha256 and the git SHA into every order, logs each CLI override as a `deviation` event, refuses stale values without `--accept-calib`. |
| `hackathon/brain/check.py`, `tests/`, `lint_literals.py` | The Mac CI entry, under two minutes, stdlib unittest: `test_geom.py` (exists, uncommitted), `test_target.py` (jog-log numbers, surface vs axis 3.3 cm), `test_signs.py`, `test_loops.py` (perturb-and-converge for every closed loop), `test_view.py`, `test_tts_gate.py`, `test_calib.py`. The lint fails on a float literal between 0.005 and 1.0 in a move or pose expression unless tagged `# calib:<key>` (about 129 today). |
| `hackathon/brain/replay.py` | Re-runs LOCATE, the plan and the servo correction from a recorded order folder and prints the robot's grasp point next to the one the code computes now; Gemma answers cached in the fixture, re-asked when the server is up. |
| `brain.py` logging | Per decision frame: colour PNG, depth uint16 PNG, intrinsics, optical-to-pelvis 4x4, commanded and measured q5, hand state, stage; q_cmd and q_meas per move and slide step; hand q at 20-100 Hz through close, hold and release; battery; `calib`, `obs` and `note` events. |
| `hackathon/brain/session_setup.py`, `SESSION_CHECKLIST.md` | Console prompts for the owner's tape numbers (table z, can x/y per slot, names, diameters) into `runs/<session>/setup.json` with a scene photo; the printed physical checklist. |
| `hackathon/tools/deploy.sh`, `pull_runs.sh`, `robot_prep.sh`, `session_report.py` | rsync to `g1:~/harness/hackathon/brain` with hash check and dirty-tree refusal; rsync `runs/<session>` with frames and clips back into `hackathon/spikes/<date>-<tag>/`; the per-boot sudo steps (jetson_clocks, stop the teleimager services, serve-orin.sh, `preflight.py --json`) with sudoers lines; per-stage counts, misses by stall pattern, latencies with n. |
| `hackathon/data/<date>-<scene>/` | Labeled robot frames with raw depth and tape ground truth: the localization bench and the Gemma regression set. |
| `hackathon/ROBOT_RULES.md`, `hackathon/research/g1-fetch-learnings/` | Hard rules merged from `CLAUDE.md`, `DESIGN_REVIEW.md` (pump the C922, the robot hears its own TTS, jetson_clocks per boot) and g1-fetch's `docs/05_deploy_learnings.md` and `06_dependency_learnings.md` copied from PC2 (poll lowstate, detector warm-up before the camera, never `pkill -f` a self-matching pattern). The Mac has no copy today. |
| `hackathon/INCIDENTS.md` | One line per incident: date, what, stage that should have caught it, test added. Seeded with the Oct 19 sign bug, the Oct 20 surface/axis bug, the lane coordinates, the self-heard TTS, the blind C922. |
| `hackathon/spikes/<date>-<tag>/DECISIONS.md` | The in-slot log: symptom, cause hypothesis, change, predicted effect, observed. One line before every change. |
| `hackathon/sim/` (after the hackathon) | MuJoCo torso and table clearance from `/Users/junda/robot/xr_teleoperate/assets/g1/g1_body23.urdf` and `brainco_hand/brainco_left.urdf`; never grasp physics. Until then `geom.py` is the kinematic simulator. |

## 4. Robot-session protocol

**Preflight, robot off.** Code frozen at a commit; S1 to S3 green; approved plan with bench evidence; last session's misses have fixtures; `calib.json` in its validity window; `deploy.sh` synced and hash verified.

**Boot, owner, 15 min.** `SESSION_CHECKLIST.md`: battery percentage, stand straps, FSM 500 (R1+X), remote in hand, cans on the taped slots, C922 aimed at the offer pose (checked on `/frame.jpg`), phone filming the hand, factory assistant asleep. `robot_prep.sh`, then `session_setup.py` for the tape numbers.

**Roles.** Owner: safety officer (L2+B through every motion, no stepping in the stand), ground-truth sensor, timekeeper and battery keeper, scene resetter. Agent: driver (runs the plan's commands verbatim, announces each motion by TTS before sending it, compares output to the expected lines, keeps `DECISIONS.md`, writes the note as it goes); never edits code on PC2.

**Timeline, hard stops.** 0-15 boot and preflight. 15-30 no motion: `brain.py --dry` compares perceived can positions to the tape (over 3 cm stays dry until explained); two static frames confirmed by the owner, the C922 seeing the offer pose and the head camera seeing the hand at the pre-grasp; hand-only tests (`hands_test_staged2.py`, the owner feels the thumb lock). 30-40 calibration check only if `calib.json` is stale or the setup moved: one jog, the robot announces "step N" by TTS and holds, the owner presses one key (b behind, c centred, f forward; l low, o ok, h high), never a number; over 1 cm off means recalibrate with provenance. 40-85 the one experiment in two 20-minute blocks, one variable, n fixed. 85-100 the acceptance run (N consecutive orders) only if the criterion passed. Last 15 min: `pull_runs.sh`, the owner dictates, battery to charge.

**Observations as data.** After every trial `brain.py` prompts the owner on the console and writes `{"ev":"obs","contact":..,"pushed":..,"grip":..,"height":..,"note":..}` next to the verify line. Vocabulary: contact palm | fingers | heel | wrist | none; pushed 0 | under 2 | 2-5 | over 5 cm; grip firm | loose | none; height low | ok | high. Comparisons, never centimetres by eye. The owner presses `p` (ARM OFF on the console and the view) before hands enter the workspace; cans move only with the streamer paused.

**Stop rules.**
- No approved plan, S1 or S2 red, dirty tree, calib hash mismatch, preflight failure or an unconfirmed static frame: the robot does not move.
- Any unexpected motion, contact with the table edge, torso, stand or a neighbouring can, or a hand closing on anything but the target: L2+B, arm parked, no motion until the cause is written.
- The same fault twice without a new written hypothesis, or two misses with the same stall pattern (thumb 0.9, pinky 0.9, all 0.9): the block ends, frames and hand states go to the bench; no third attempt.
- A parameter moves only after the fault is reproduced in a saved frame or log, one parameter, predicted effect written first; an undeclared change or a code edit on PC2 ends the session.
- The jog disagrees with `calib.json` a second time in one session: something physical changed, the session ends.
- The can moves during the slide: stop and re-locate. Pre-registered n reached: stop, even on a streak.
- Battery under 30 percent, 100 minutes elapsed or the owner's named cutoff: no new trials.
- Any doubt about a sign, frame or unit: back to S1. Stepping only free-standing, with a spotter, a displacement cap and its own plan.

**Post-session.** `pull_runs.sh`; the owner's five-question debrief (what surprised you, what did the hand do on each miss, what would you veto, what felt right, what to measure next time) into the note; the driver session ends; the post-mortem starts fresh.

## 5. What the owner can do

On the robot:
- Hold L2+B for the whole slot and call every stop rule; never extend a block.
- Be the sensor the stack lacks: the jog keys, the obs record after every trial, the grip felt (thumb lock after the fingers), where the can ended and which fingers touched.
- Reset the scene to the taped marks, only with the arm paused; read the LEDs and the remote state when the logs and the robot disagree; keep the clock and the battery.
- Run the boot checklist and `robot_prep.sh`; test the onboard mic with PC1 offline after a reboot.

Off the robot:
- Approve every plan and brief; send back any plan that tunes a constant without a cause; cut scope there, not on the robot.
- Measure once with the tape and photograph: table height above the pelvis origin, chest front and shoulder width (the torso box), camera height and pitch, wrist to palm centre (g1-fetch's `ee_offset_x`, still marked MEASURE; a tape value retires the per-session jog). These become `calib.json` entries.
- Build the rig: taped table grid and stand position, numbered can slots, a fixed C922 mount aimed at the offer pose, the same can set every session, named and photographed.
- Run the two no-motion PC2 jobs: `make_fk_fixtures.py` once (pinocchio FK in the `g1fetch` env) and `pull_runs.sh` after each session; tape-measure can positions for the labeled frame set; speak test orders in the promised languages into the C922 so `replay.py` has real clips.
- Tell the agent the hardware history before a plan is written (the right thumb motor, the stand straps, the voice service needing PC1 internet), not after a miss.
- Give the debrief and read the session note for physical accuracy before it is committed.

Never asked to: read a screen beside an enabled arm, estimate centimetres by eye, debug Python on PC2 during a block, run a fifth block on one battery, or be the agent's memory of what changed.

## 6. Session lifecycle

One pinned coordinator session per project, in a sidebar group "G1", never writes code. It owns `HACKATHON_PLAN.md`, the robot-slot calendar and this file; it starts each worker with a brief path, receives the handoff paragraph (what changed, verified-table deltas, blockers, commit), updates the verified table and archives the worker. Workers never start workers; a redesign is a new brief and a new session, never a message into a running build. The v2 session now running was started by the v1 worker: the coordinator adopts it by sending it `BRIEF.md` to fill before it touches the robot.

| Session | Reads | Leaves | Time box |
| --- | --- | --- | --- |
| `design-<feature>` | plan, last note, `DESIGN_REVIEW.md` | `BRIEF.md` with numeric pass criteria, the decisive measurement, offline checks | 40 messages, no code |
| `build-<feature>` | the brief, at most six files | code against recorded data, tests, `HANDOFF.md`, commit | 150 messages or 1.5x the estimate |
| `robot-<date>` | `RUN_PLAN`, `HANDOFF`, `calib.json`, `ROBOT_RULES`, the checklist | logs, `DECISIONS.md`, the note skeleton | wall clock and battery |
| `postmortem-<date>` | the synced run, the debrief | `README.md`, a fixture and test per miss, `calib.json`, `INCIDENTS.md`, next plan draft | 60 messages |

When to stop: a second change for the same symptom without a `DECISIONS.md` line naming a cause; a robot session re-deriving what the plan states or passing about 150 messages (hand off through the note, start fresh); a build that wants to "see on the robot" or a robot session that needs the build history (the handoff is incomplete, send it back). The session that writes code never holds the robot; the session on the robot never holds the build context; the session that judges the day never made its decisions.

## 7. The first things to build

1. `hackathon/ROBOT_RULES.md`, `hackathon/INCIDENTS.md` seeded with the known incidents, the four templates in `hackathon/templates/` (done 2026-10-20 evening); copy g1-fetch's learnings docs from PC2 at the next robot session (PC2 was unreachable).
2. Commit `hackathon/brain/test_geom.py` and add `check.py` that runs it in `python3 -B` form.
3. `calib.json` and `calib.py`; `brain.py` loads them, logs the hash, git SHA and every CLI override; `--dx`, `--lane-x`, `--lane-y`, `--diam` default from the file.
4. `target.py` extracted from `brain.py` (box plus depth to can axis, diameter class, grasp, pre-grasp and offer points, in-view check; numpy only) with `test_target.py` (surface vs axis on the jog-log numbers), `test_signs.py` (the `approach_can` inversion), `test_view.py`, `test_tts_gate.py`. Sequence with the v2 session editing `brain.py` now; do not fork it.
5. Frame-bundle logging and the `obs`, `calib`, `note` events in `brain.py`: the next session must produce replayable data; today the Mac holds empty order folders and no depth.
6. `deploy.sh`, `pull_runs.sh`, `robot_prep.sh` with the sudoers lines (owner), `session_setup.py`, preflight additions (battery, free disk, hash equals the Mac's, calib freshness, the two static frames).
7. The plan for the next session: v2 step 1, the palm-to-can offset measured in the head camera against the model at six poses with the tape beside it, pass within 1 cm on 5 of 6; no grasps.
8. After that session: `replay.py` over its bundles, `hackathon/data/<date>-<scene>/` with tape ground truth, `session_report.py`, the first miss fixtures.
9. `mock_robot.py` hidden error model and the four known-failure reproductions; `lint_literals.py`.
10. After the hackathon: `make_fk_fixtures.py` on PC2, `hackathon/sim/` for clearance only, a software workspace box and per-step displacement caps so L2+B is the last line, not the first.
