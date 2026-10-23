# Review of brain v2 (2d4f1ca) before the first robot session

Six reviewers read the v2 code, the run plan `hackathon/briefs/2026-10-21-v2-kill-test.md` and `HANDOFF.md` against `V2_STRATEGY.md`, `DEV_WORKFLOW.md` and `hackathon/ROBOT_RULES.md` on 2026-10-20 evening. The cross-check stage ran out of usage credits, so the coordinator verified the blockers by hand. Everything below marked **verified** was checked in the code, in Tuesday's logs or by running the mock. The full list of 113 reviewer findings is in `V2_REVIEW_findings.json`; apart from the items below, it is unverified.

## Verdict

The run plan cannot be approved as written. The first motion would most likely end in a refused correction and then an uncapped park move toward the can slots, and the "no motion" block moves the arm. All the fixes are small. The design itself (yaw search, table-plane z, calib with provenance, description-based choice) checks out offline.

## Blockers, verified

1. **The pre-grasp correction will hit the 2 cm cap.** `motion.py:74` applies the whole measured error as one target, and `motion.py:53` refuses any target that moves the palm more than 2 cm. Tuesday's logs show uncorrected errors of 2.0 to 2.5 cm at the raise and 3.2 to 4.7 cm at the high waypoint (`spikes/office-tue-brain/2026*/order_*.jsonl`, `move` events). The mock's sag is under 1 cm, which hides this. Fix: stream the correction in capped sub-steps until under 6 mm, or feed the current sag forward as `step_along` already does.
2. **After any failed skill the arm parks in joint space from beside the can.** `brain.py:814-818` opens the hand and calls `park()` directly, skipping the up-first retreat. The default park pose is joint zero, whose real palm sits at x 0.362, y 0.149, z 0.095 with the fingertips to x 0.44 (computed with `geom.fk_chain_side`). That is on the plan's first slot (x 0.36-0.40, y 0.17). Fix: retreat up and back before any park when the arm is over the table, and run every command with `--park home`.
3. **The "No motion" block moves the arm.** `brain.py:949` parks at startup unless `--park release`, also under `--dry`, unannounced, while the cans are on their slots. Fix: skip the park under `--dry`, announce every park and home move by TTS, and add `--park release` or `--park home` to the plan's commands.
4. **The air test's own stop rule fires on the first target.** The plan stops on an `up:`, `high:` or `pre:` line with err over 2 cm, but `brain.py:537-540` runs the raise and high moves with `correct=0`, so their printed err is the raw sag (2.0 to 4.7 cm on Tuesday). Fix: apply the rule to the corrected `pre:` line only, and record up and high as the sag baseline.
5. **The air test skips the 0.30 m obstacle rule.** `air()` at `brain.py:882` never reads a camera frame. `obstacle_ahead` is only called in `locate()` at `brain.py:507`. This is a hard rule in `ROBOT_RULES.md`. Fix: read one head frame and refuse as `locate()` does before `to_pregrasp`.
6. **The handoff names a stale commit.** `HANDOFF.md:7` and `:38` name 103d21e and expect it after `git pull`. HEAD is 2d4f1ca, which carries the directive changes (3 cm upper-arm clearance, table-plane refusal, Gemma cross-check). The boot check would fail, or a driver would check out the old code. Fix: name the final commit and its calib sha16 in the handoff and in the plan's Held fixed.

## Plan problems, verified from the text

- **Slot 1 contradicts the pass criterion.** The plan requires scatter under 1 cm at 3 of 3 slots, yet its own risk line expects "hand not seen" at the far-left slot. Use slots the camera covers, for example y 0.12, 0.09 and 0.06, or report slot 1 separately as an edge probe.
- **The air targets need the real table height.** `air()` builds a virtual table 6.1 cm under the target. At z 0.13 the open hand's lowest point is about 7 cm above the pelvis origin; Tuesday's can heights put the real table near 8 cm. Set each air target's z from the tape plus a 3 cm margin, and tape the palm half-height, which `calib.json` marks as assumed with n 0.

## Must fix before any can is grasped, verified by running the mock

- **A tracking-error abort becomes the closure trigger.** `brain.py:601-602` turns an abort into "ok" when the model's gap is under 2 cm. Both mock scenes I ran closed this way, one with 1.5 cm of gap left. The memo makes tracking error an abort only and closes when the measured gap is under 1 cm.
- **The desk gate does not test the servo.** In the gate's seeded order and in both scenes the servo made zero corrections (errors of 3 to 5 mm at the first frame, `corrections: 0`). Seed the gate with a hidden error the model alone misses and assert that at least one correction happened.

## Not reproduced

- The claim that mock scenes "two" and "centre" fail at the gate's hidden error. One order each, order "silver", succeeded on 2d4f1ca. The reviewer may have used different orders or `--orders 10`; that was not rerun.

## Reviewer findings still to triage (unverified)

These came from single reviewers and need the build session to confirm or refute each before acting. Highlights, by the reviewers' severity:
- `--palm-real` and `palm_real_m` never reach the kinematics, because `geom.py` binds `ee=PALM_REAL` as a default argument at import.
- The servo's z reference uses the box-centre depth point, not the table-plane grasp z.
- The table height is taken at the pelvis origin, not under the can, and a 25 degree plane tilt is accepted.
- The can height comes from the box height and reads 1 to 2 cm short.
- The stall pattern maps Tuesday's hand-low signature (thumb 0.9 and pinky 0.9) to the forward correction.
- The handover's let-go transcript is gated 2 s after an estimated TTS end; the rule says 4 s.
- The raise waypoint and the yaw-blended path to the high waypoint are never clearance-checked.
- Literal copies of calib numbers remain in `geom.py`, and the replay and tests run on them.
- "Half speed" in the plan does not exist in the code.

## What checks out

The desk gate passes on the Mac. The URDF chain matches g1-fetch's FK to 0.6 mm, and the yaw-held IK reproduces the memo's worked example. The replay of 18 logged positions accepts every grasped position and rejects the Oct 19 centre-line block at psi 0. Grasp z comes only from the table plane, with no box-depth fallback. Every calib entry carries provenance and its sha is logged per order. The description choice was right on 13 of 13 clips on the Mac.

# Round 2: c39a468 (code) and 89ff132 (handoff, plan), 2026-10-21

Eight agents each tried to show one fix does not hold, reading every code path and running scratch copies of the mock; a critic looked for new risks. Full results: `V2_REVIEW_round2.json`. The coordinator re-ran the gate (13 of 13 pass) and confirmed the wrist-roll snap independently.

## Verdict

Not ready for robot time. Blocker 6 (the commit and calib sha in the handoff) is fixed. The other five are fixed on the path the gate tests but not on all paths, and the fixes added two new risks to the air test's first motion. The gate passes because each case exercises one path per blocker.

## New blockers for the air test (the first motion)

1. **A 34 degree wrist snap in one 20 ms target.** Position-only moves now keep the seed's wrist roll (`motion.py:46-47`), so the first target of the high move jumps the roll to the planned value at once. The per-target cap checks palm position only (`motion.py:62-66`), so it passes. Confirmed by the coordinator on the mock at `--speed 0.5`: "BIG dq 0.592 rad on joint 4" on every air order. 2d4f1ca rolled at most 0.016 rad per target. Fix: cap the joint change per target (for example 0.02 rad times the speed scale) and blend the roll along the high path as psi is blended.
2. **A stop during the raise or the home descent falls back to a joint-space home with the fingertips under the table top.** The raise path is recorded only after the up move returns (`brain.py:566`), and `go_home_safe` falls back to joint space when the palm is more than 5 cm from the raise end (`brain.py:910-916`). Reproduced on the mock at air target (0.35, 0.00): fingertip x 0.35-0.36 at z 0.044-0.057, 2-3 cm under a 0.075 table. With `table_edge_m` null this is only printed. Fix: record the raise as it streams and retrace the sent prefix on any stop; never take the joint-space branch above table height.
3. **There is no safe way out of "stuck".** The streamer holds the last target with no timeout. `q` ends in `arms_disable` over the table, which hands the arm to the controller's joint-space move. A refused retreat-back repeats retreat-up on every retry, so the arm walks outward (y 0.20 to 0.32, x to 0.52 with h presses). The `h` key latches when pressed at any other time and triggers the next retry with no input. Fix: no arm move while stuck without an operator confirmation; never disable the streamer away from home; accept `h` only while stuck; write the stuck procedure into the plan's stop rules.

## Blockers for the kill test

4. **The correction rounds push into the table.** `motion.py:111` adds the same error each round without checking that the hand moved. The purple 12.2 cm can leaves the palm 1 mm above the table at the pre-grasp, and `table_clear_m` -0.01 accepts poses 1 cm under it. With the depth plane 5, 10 or 20 mm low, the mock with table contact drove the command 1.7, 3.6 or 7.9 cm down while the palm rested on the table. Nudges and servo moves have no table floor either. Fix: stop when the hand did not follow; never command below table plus palm half-height plus a margin; a table-contact case in the gate.
5. **The fingertip feature is the edge of the search window, not the hand.** `geom.py:163`: the blob's top equals the window top at every forward error, so forward errors of 2.4 to 5.4 cm read 6 to 9 mm and produce no correction. This makes the kill test's scatter along the forearm and its "off minus model_off" meaningless, which is the plan's question. Fix: widen the window so the whole hand fits and treat a blob touching the window edge as not seen.

## Must fix before any can is grasped

- **The hand still closes on the model gap** when the visual gap is missing, disagrees by more than 1.5 cm, or reads longer (`brain.py:623`). A failed Gemma cross-check stops only the servo, and the approach then closes (`brain.py:587`). `pick()` has no guard when K is null, which is the shipped state. Close only on a valid visual gap that agrees with the model within about 1 cm; refuse to pick with K null unless a logged flag allows it.
- **The obstacle check fails open** on an empty or mostly invalid depth frame (`geom.py:194`), and the air test's table check proceeds when no plane is fitted (`brain.py:1042`). After a refused locate on the retry, `assist()` moves the arm with no obstacle check (`brain.py:987`).
- **`--speed` does not reach the approach steps or the home bridge** (`motion.py:137`, `brain.py:912`), and it accepts any float, so `05` means five times faster.
- **Nothing enforces the calib hash.** Add an expected-sha argument that refuses to start on a mismatch or a dirty tree, on every plan command.

## Run plan changes

- Drop the 2 cm lower bound on the raise sag: Tuesday logged 1.9 cm on healthy moves.
- Drop "off minus model_off changes by 2-4 cm across the slots" from the pass criterion: the memo stated it for slots spread along x, and the plan's slots vary in y only (the mock gives 1.1 cm).
- The servo-residual block cannot command a correction: at the planned slots the mock's servo error is under the 1 cm tolerance. Add a logged pre-grasp offset of 2-3 cm, or drop the block from this plan.
- The time boxes add up to 110 minutes against the 100-minute rule.
- The `p` key only blocks the next order; it does not pause the streamer as the plan and the rules assume.
- Judge the elbow gaps by comparison (clear, close, contact), not centimetres by eye.

## Fixed and holding

- Blocker 6: the handoff and the plan name c39a468, the calib sha16 d26f244ab4d4f575 matches the file, and the boot line works at 89ff132.
- The per-target palm cap: no failures over 107 planned targets at 1 to 2.2 times the logged sag; corrections converge in bounded rounds.
- The mock's sag matches Tuesday's high waypoints (2.4-4.9 cm against 2.5-4.6 logged); it under-predicts the raise and has no can load.
- `--dry` no longer enables or parks the arm; the air test now refuses on the 0.30 m rule in the gate's case; the closure no longer turns a tracking abort into a close.

# Round 3: 8e226e9 (code) and ec4c0d0 (handoff, plan), 2026-10-21

Eight agents each tried to break one fix or the plan on paths the 33 gate cases do not use; a critic looked for new risks. Full results: `V2_REVIEW_round3.json`, where every item is marked by whether it can bite in this plan. The coordinator re-ran the gate (33 of 33 pass) and confirmed the start-up park finding in the code.

## Verdict

Closer, still not ready. The wrist-snap fix holds on every path (largest joint step 0.010 rad at half speed over the three air targets, the kill slots, the servo block and six injected stops; 0.394 rad on c39a468). No new safety blocker was found in the fixes themselves. Two plan problems would end the session on their own, and about a dozen must-fix items can still bite in this plan.

## Plan blockers (the session would stop itself)

1. **The kill test cannot start after the air test.** Outside `--air`, the table height used by the home check is 0.0 (`brain.py:117`, `:999`), and the home pose's own wrist sits at z +0.026, so `home_region` is never true and `park()` (`brain.py:1130`) accepts only an arm within 0.05 rad of home on every joint. Every quit releases the arm and switches the arm service on, so the next start is refused ("My arm is not at my side"). The mock always starts at home, so the gate never sees it. Use the taped table height in every mode, or judge the home region on the palm and fingertips only; add a gate case that starts from a released pose.
2. **The no-motion hand test contradicts the code.** The plan requires a hand held 30 cm in front of the chest to be refused, but the zone ends at pelvis x 0.30 and the chest front is at x 0.08, so 30 cm out is x 0.38, outside it. The mock reports "clear". Test at 10 and 20 cm from the chest, at belly height, and expect "clear" at 30 cm.

## Must fix that can bite in this plan

- **Stuck exits (`brain.py:305`, `:1081`).** A q or Ctrl-C while stuck sets the quit flag, after which every confirmed way-out run aborts at its first target, leaving L2+B with the arm over the table as the only exit. A g1-fetch failure or a lost arm state during a way-out escapes `run_retreat`: from idle the shutdown then moves the arm home without confirmation, and from shutdown the process exits with the arm out. `quit` is spoken but only `quit!` is accepted, with no feedback for unknown lines.
- **The table push in the kill test (`motion.py:162`, `:57`).** The first correction round streams the whole error into the table before the follow check, and the floor uses the palm centre minus 4.5 cm, ignoring pitch, roll and fingers. The mock's probe at slot (0.38, 0.12) with the purple can pushed 45 mm; the open hand's lower front corner sits up to 13 mm under the table at the servo block's nudge. Raise the kill pre-grasp 1.5-2 cm above the floor (offset K_z by the known amount), floor the hand's lowest point, and stop on contact before streaming. The plan's stop rules must name the brain's "(contact?)" refusals, and the taped palm half-height needs a route into the code.
- **The fingertip reach in the keep-out.** Calib's `fingertip_m` 0.08 (n 0) against the mock hand's 12.5 cm: the raise and every way home sweep the forearm level at table height, so the real fingertips pass x 0.34-0.35 under the table top while the keep-out reports "behind x 0.306". Tape the palm-to-fingertip length before the air test and set the table edge from the printed reach plus 2 cm.
- **The obstacle check runs once per order with the arm at home.** Re-check before high, pre, each air step and each approach step, and hold the arm on a refusal.
- **The off-minus-model_off stop rule fires at the nominal reading** (9 cm along d with zero model error). State expected ranges per axis instead.
- **The Gemma cross-check fails open when Gemma returns no box** (server down, timeout). Treat a missing box as a failure in the servo block.
- **Can resets with the streamer holding the arm** conflict with the hard rule that cans move only with ARM OFF shown. Either add a real streamer pause or change the rule through a post-mortem with its reason. Enter typed while paused is latched and starts the next order the moment p resumes.

## Must fix before grasping (not in this plan)

- The visual gap is not independent of the model along the palm normal once K is probed with the same error: the mock closed 2.4 cm short while the two agreed.
- The stall-pattern fix nudges 2-3 cm blind and re-closes with no measured gap.

## Fixed and holding

- The joint-step cap on every streamed target, including splits, the startup park, the retraced home and shutdown.
- `--speed` bounded to (0, 1] and reaching the approach steps and joint-space moves; `--expect-calib` refusing a mismatch or a dirty tree; the air table fitted without the tape hint; no assist after a refused locate; K null refuses a grasp unless `--model-grasp`.
- The hand window: forward errors of 3.9 and 5.4 cm now read 3.7 and 5.0 cm and are corrected.

# Round 4: 13bff01 (code) and abe447a (handoff, plan), 2026-10-21

Eight agents and a critic, as before; full results in `V2_REVIEW_round4.json`. The gate passes 50 of 50 on the Mac.

## Verdict

No new safety blocker in the fixes for the second round running. The round-3 plan blockers are fixed: the kill test starts from a released arm, and the no-motion hand test matches the zone. One new plan blocker would stop the session at the no-motion block. About ten must-fix items remain, almost all in the stop and pause paths or in compound-error table contact of about 1 cm.

The critic's judgment decides the next step. The normal path is predictable from the plan. The stop and pause paths are not: about 17 flags written by the stdin thread, the signal handler and the main loop; q, a, Ctrl-C, quit, quit! and p each change meaning with the state; and the plan, HANDOFF and README disagree with the code in at least five places. Four rounds of patching these paths have each produced new interaction bugs. The next round should simplify them rather than patch them.

## Plan blocker

- **The dry run's raise line plans the old straight raise** (`brain.py:1349`), not the two-stage raise the arm actually runs. At a fingertip length of 11.4-12.5 cm it prints a reach of 0.34-0.35 m against 0.30 m for the real raise, so the plan's rule (reach at most E - 2 cm, E at most 0.347) has no valid table edge and the session stops before the air test. Found independently by two verifiers. Plan the same two waypoints in the dry line and gate it against the moving run's line.

## Must fix that can bite in this plan

- **Stops.** `quit!` typed in the 1-2 s between a failure and the recovery retreat is printed as honoured, yet the whole retreat streams (901 targets in the air-test contact case). A second q or Ctrl-C while the shutdown plans its retreat is printed as "holds" and the arm goes home. A typed `a` between orders stays latched and cancels the next order.
- **Pause.** After a refused take-back, the next p prints "taken back at home" with the arm off, and the next order enables the arm without the start-pose or enable checks (`brain.py:589`).
- **Hands in the workspace.** The kill test asks the owner to measure the palm gap with a feeler during the 4 s pause while the streamer is live; the brain then measures with that hand in the window and retreats or nudges 2.7 cm by itself. This breaks the ARM OFF rule and corrupts the measurement.
- **Table contact.** The mock's table contact tests only the hand box's corners, so the kill-table case's 3.4 mm push is an artifact; with the box intersected properly it is about 1 cm and the slot is refused. The final lowering line streams the whole residual before the follow check. The kill test never compares the fitted plane with the taped one. The fourth air run lacks `--floor-margin 0.02`.
- **Obstacle re-checks.** No re-check before the servo block's 2.7 cm nudge; the blind-region rule is skipped while the arm is out, so a hand inside the camera's minimum range is not seen during the air test.
- **The blind-region baseline is unmeasured.** If the real camera's largest invalid region at the table is 8% or more, every locate refuses. This fails safe but would waste the session; record it in the no-motion block and set the threshold from it as a logged value.

## Recommended simplification for the next round

- One meaning per key in every state: any stop (q, a, Ctrl-C) freezes and holds; the brain then says the way home and runs it only on `y`; the process exits only at home; L2+B stays the emergency stop.
- No pause or retake inside a process: one process per slot (`--orders 1`), exiting at home; cans are reset between processes with the arm released at home. This removes the pause and take-back paths from the plan.
- Drop the feeler measurement from this plan.
- Keep the servo block optional and last, behind the kill test's pass.
