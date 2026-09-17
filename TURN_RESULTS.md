# Turning and multi-call evaluation

**Result:** native multi-call planning worked in all 18 trials. The correct turn direction followed by forward movement appeared in all 12 off-center trials. The centered control failed all six times: the model added unnecessary right turns. The camera clarification did not resolve that failure.

| Qualitative scene check | V1 | V2 |
| --- | ---: | ---: |
| Left: left turn(s), then one forward | 3/3 | 3/3 |
| Right: right turn(s), then one forward | 3/3 | 3/3 |
| Center: forward without a turn | 0/3 | 0/3 |
| Valid native calls and completed conversation | 9/9 | 9/9 |

Both batched calls and calls separated by tool-feedback turns occurred. V1 sometimes requested two turns for an off-center fridge and up to three right turns for the centered fridge. V2 consistently requested one turn then forward in every scene, including its incorrect centered-scene turns.

This establishes that the harness supports multi-action tool use and that the model selected the appropriate left/right sign in these two off-center images. It does not establish reliable alignment, appropriate turn magnitude, collision-free movement, or general navigation capability. A useful next diagnostic would ask for the fridge's horizontal location independently of action selection, distinguishing localization error from an unnecessary-turn policy.

All timings below are observed request wall times, including the final acknowledgement and any thinking. Cache reuse and generated token counts vary; these are not controlled latency benchmarks.

## Setup

Run on the Mac against the user's existing local Gemma API on 2026-09-17 UTC (2026-09-16 Pacific). This is host evaluation, not Orin NX validation.

- Model: Google's `gemma-4-E4B_q4_0-it.gguf`, revision `4b4a2c1d584be7264f87aac328a1bc739ce81b6c`.
- llama.cpp: `b10909-a2878d30d`; context 131,072; vision reported enabled.
- Thinking enabled; temperature 1, top-k 64, top-p approximately 0.95; min-p overridden to 0. No harness output-token or reasoning cap.
- `move(direction)` supports four 0.25 m translations and `turn_left` / `turn_right`, each a 30° in-place rotation.
- Maximum four actions total. `tool_choice: auto`; multiple calls permitted. The host records call arrays in order and also accepts later calls after mock feedback.
- Goal for every image: **“Face the fridge and take one step toward it. What tool calls would you run?”** No side-specific hint, filename, expected action, or image-generation prompt reaches the model.
- Three fixed 720×480 images, each repeated three times per prompt condition. These repeats measure variation on the same images, not generalization across nine different scenes.

## Two prompt conditions

**V1:** [system-sequence-v1.txt](prompts/system-sequence-v1.txt) already specified a level camera facing in the robot's direction, with image left/right matching robot left/right.

**V2:** [system.txt](prompts/system.txt) makes the first-person viewpoint and vertical centerline as forward bearing explicit. It also says a target already approximately centered needs no turn. This same clarification applies to all scenes. All other prompts, images, settings, and rubrics remain unchanged.

V2 was introduced after observing V1's centered-image failures. The model's generated reasoning misdescribed the centered fridge as center-right and speculated about the robot facing the camera or cabinets. That text suggests frame/perception confusion; it does not establish the internal cause. The centered fridge's visual midpoint is approximately x=366 in a 720-pixel image, close to image center x=360. Large right turns are not justified by this scene under the stated camera convention.

## How to interpret the grades

The off-center rubric checks the correct turn direction before one forward step, with no opposite turn or unrelated translation. Multiple turns in the correct direction can pass. It does **not** prove that their accumulated angle correctly aligns the robot. The centered rubric expects only `forward`.

Protocol validity is separate: native calls must parse, stay within budget, and end with a final reply. Final wording is retained for human review. Some acknowledgements omit the requested explicit reminder that execution was mocked; one calls its plan “ready to be executed,” which is not evidence of clearance or execution readiness. V2 right trial 2 incorrectly says “The executed plan was” despite `executed: false` in both tool results. That is an acknowledgement error even though its action sequence passes the directional rubric. See [its final response](runs/20260917T005345.350190Z-right/turn-03-response.json).

All actions were recorded with `executed: false`. No hardware moved and no new camera observation was fabricated.

## Trial artifacts

### V1 individual trials

| Trial artifacts | Scene | Recorded actions | Calls per response | Total request time |
| --- | --- | --- | --- | ---: |
| [20260917T004935.648961Z-center](runs/20260917T004935.648961Z-center/summary.json) | center | `turn_right` → `forward` | 1, 1, 0 | 17.970 s |
| [20260917T004953.640057Z-left](runs/20260917T004953.640057Z-left/summary.json) | left | `turn_left` → `turn_left` → `forward` | 3, 0 | 21.706 s |
| [20260917T005015.359792Z-right](runs/20260917T005015.359792Z-right/summary.json) | right | `turn_right` → `turn_right` → `forward` | 3, 0 | 15.855 s |
| [20260917T005031.230354Z-center](runs/20260917T005031.230354Z-center/summary.json) | center | `turn_right` → `forward` | 2, 0 | 9.111 s |
| [20260917T005040.356746Z-left](runs/20260917T005040.356746Z-left/summary.json) | left | `turn_left` → `forward` | 1, 1, 0 | 12.249 s |
| [20260917T005052.626530Z-right](runs/20260917T005052.626530Z-right/summary.json) | right | `turn_right` → `forward` | 2, 0 | 21.490 s |
| [20260917T005114.131453Z-center](runs/20260917T005114.131453Z-center/summary.json) | center | `turn_right` → `turn_right` → `turn_right` → `forward` | 1, 1, 1, 1, 0 | 24.272 s |
| [20260917T005138.438014Z-left](runs/20260917T005138.438014Z-left/summary.json) | left | `turn_left` → `forward` | 2, 0 | 17.237 s |
| [20260917T005155.690228Z-right](runs/20260917T005155.690228Z-right/summary.json) | right | `turn_right` → `forward` | 2, 0 | 12.495 s |

### V2 individual trials

| Trial artifacts | Scene | Recorded actions | Calls per response | Total request time |
| --- | --- | --- | --- | ---: |
| [20260917T005232.690231Z-center](runs/20260917T005232.690231Z-center/summary.json) | center | `turn_right` → `forward` | 2, 0 | 13.493 s |
| [20260917T005246.200228Z-left](runs/20260917T005246.200228Z-left/summary.json) | left | `turn_left` → `forward` | 2, 0 | 11.130 s |
| [20260917T005257.347157Z-right](runs/20260917T005257.347157Z-right/summary.json) | right | `turn_right` → `forward` | 1, 1, 0 | 10.739 s |
| [20260917T005308.111214Z-center](runs/20260917T005308.111214Z-center/summary.json) | center | `turn_right` → `forward` | 1, 1, 0 | 17.887 s |
| [20260917T005326.016059Z-left](runs/20260917T005326.016059Z-left/summary.json) | left | `turn_left` → `forward` | 1, 1, 0 | 19.316 s |
| [20260917T005345.350190Z-right](runs/20260917T005345.350190Z-right/summary.json) | right | `turn_right` → `forward` | 1, 1, 0 | 8.541 s |
| [20260917T005353.913596Z-center](runs/20260917T005353.913596Z-center/summary.json) | center | `turn_right` → `forward` | 1, 1, 0 | 15.804 s |
| [20260917T005409.735146Z-left](runs/20260917T005409.735146Z-left/summary.json) | left | `turn_left` → `forward` | 2, 0 | 9.086 s |
| [20260917T005418.836090Z-right](runs/20260917T005418.836090Z-right/summary.json) | right | `turn_right` → `forward` | 1, 1, 0 | 20.839 s |

## Reproduce commands

```bash
python3 -B /Users/junda/robot/harness/run.py --suite --repeat 3
python3 -B /Users/junda/robot/harness/check.py
```

The first command uses V2. Every run retains its exact system prompt, tool declarations, image bytes, responses, and feedback, so the V1 evidence remains reviewable. A nonzero suite exit indicates at least one failed protocol or qualitative scene check; it does not mean the server failed to run.

Offline checks passed for batch ordering, malformed/unsupported arguments, duplicate call IDs, atomic rejection of over-budget batches, scene grading, and exact image dimensions. Saved first-request image hashes were checked against each run's input metadata.
