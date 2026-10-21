# <date> (<time>, <place>): <what the session was for>

Copy to `hackathon/spikes/<date>-<tag>/README.md`. The skeleton is written during the session by the driver; the per-run table and the root causes are completed in the post-mortem. Logs and frames: where they are (PC2 path, synced path).

## Setup

| Item | Value |
| --- | --- |
| Commit | |
| `calib.json` sha256 | |
| Table height (tape, pelvis frame) | |
| Can slots (x, y per slot) | |
| Cans (name, diameter, photo) | |
| Battery start / end | |
| Owner present on L2+B | |

## Runs

| Run | Params | Target (axis, m) | Pre-grasp measured | Slide | Hand state at verify | Owner obs (contact, pushed, grip, height) | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

## Counts

- Per class (slim / standard; left / centre-left / centre): n, successes, misses by stall pattern.

## Root causes

One per miss, or "unknown, needs <measurement>". Each traced to the stage of `DEV_WORKFLOW.md` §2 that should have caught it and the test added (one line in `hackathon/INCIDENTS.md`).

- 

## Calibration deltas

- (entry, old, new, method, n) or "none"

## Debrief (owner)

- What surprised you:
- What did the hand do on each miss:
- What would you veto:
- What felt right:
- What to measure next time:

## Open items

- 
