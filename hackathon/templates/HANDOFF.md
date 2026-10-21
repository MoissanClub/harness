# Handoff: <feature> (<date>)

What a build session leaves for the robot session. "We will see on the robot" is not allowed: anything that cannot be checked offline is named, with the reason, and becomes a no-motion check in the run plan.

## Commit

- Hash, branch:
- Files changed (names only):

## Passed offline, with numbers

| Check | Command | Result (n, error, counts) |
| --- | --- | --- |
| `check.py` | `python3 -B hackathon/brain/check.py` | |
| Mock | `brain.py --mock --mock-gemma --orders 10` | |
| Replay | `replay.py <bundle>` | |
| Perception | (fixture set, n per class) | |

## Cannot be checked offline

| What | Why | No-motion check in the run plan |
| --- | --- | --- |
| | | |

## How to run it

Exact commands and flags, in order, with the output lines expected; nothing the robot session has to work out.

```bash
```

## Parameters and calibration

- `calib.json` entries read, sha256:
- CLI overrides the plan allows (each one logged as a deviation):

## Open risks

- 
