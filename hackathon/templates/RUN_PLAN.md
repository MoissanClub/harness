# Run plan: <slug> (<date>)

Copy to `hackathon/briefs/<date>-<slug>.md`. Written by the agent (S0), approved by the owner before the robot is switched on. One experiment per plan. A plan that tunes a constant without a named cause goes back.

## Question

One sentence. Example: "Does the head camera measure the palm-to-can offset within 1 cm of the tape at the pre-grasp?"

## The deciding number

- Measured quantity, unit, frame:
- Tolerance:
- Pass criterion with n per class (example: within 1 cm on 5 of 6 poses, slim and standard cans):
- Fail means (what we conclude, what the next plan measures instead):

## Held fixed

- Commit hash:
- `calib.json` sha256 and validity window:
- Can set (names, diameters, photo):
- Taped slots (x, y per slot in the pelvis frame, table height):
- Stand position, camera mounts:

## Bench evidence (filled before the robot is switched on)

- `check.py`: pass/fail, tests run:
- Mock runs (`brain.py --mock`): orders, outcomes:
- Replay over recorded data: n, error:
- What cannot be checked offline and why (each becomes a no-motion check below):

## Blocks (minutes, hard stops)

| Block | Minutes | What | Commands (verbatim) | Expected output lines |
| --- | --- | --- | --- | --- |
| Boot and preflight | 0-15 | `ROBOT_RULES.md` boot checklist | | |
| No motion | 15-30 | dry run against the tape; two static frames confirmed by the owner; hand-only test | | |
| Calibration check | 30-40 | only if `calib.json` is stale or the setup moved: one jog, owner presses b/c/f and l/o/h | | |
| Experiment | 40-85 | one variable, n fixed, in two 20-minute halves | | |
| Acceptance | 85-100 | N consecutive orders, only if the criterion passed | | |
| Close | last 15 | `pull_runs.sh`, debrief, battery to charge | | |

## Stop rules for this plan

The general rules in `DEV_WORKFLOW.md` §4 apply. Plan-specific ones (example: "the measured offset disagrees with the model by more than 5 cm: stop, the camera transform is wrong"):

- 

## Owner tasks

- Before: 
- During (keys, observations, resets): 
- After (debrief questions): 

## Risks

- 
