# Checkpoint and proposed next experiment

**Superseded as the main direction:** the user's objective is complete drink-fetching autonomy with short action chunks. See [TASK_CHUNK_PROPOSAL.md](TASK_CHUNK_PROPOSAL.md). The retrospective below remains valid; the single-frame alignment experiment is now an optional diagnostic for a specific failure, not the next project milestone.

Status: proposal for review. No new inference, dataset collection, controller implementation, or hardware actuation has been performed for this proposal.

## Recommendation

Stop optimizing multi-action tool syntax for now. First build a small, explicitly labeled **single-step visual alignment evaluation**, then compare:

1. Image → Gemma → next-action tool call.
2. Image → Gemma → target location → deterministic next-action rule.

Use an oracle-location control to distinguish visual errors from failures to apply the rule. Keep the current model/runtime fixed. The second arm uses one VLM inference, not an additional language-model planner. Its benefit is a measurable intermediate result and explicit control geometry; lower latency and better accuracy are hypotheses to test.

This does not commit us to a perception/controller architecture. The immediate decision is where the observed errors originate and whether that separation helps this model.

## What we actually established

| Observation | Supported conclusion | Not established |
| --- | --- | --- |
| All 99 requests in the latest pilot and format experiment produced valid native calls | The tested template/parser/schema path works | Useful or physically correct actions |
| Brief and normal thinking each scored 7/9 in the pilot; brief used 33% fewer reasoning tokens | A system instruction reduced reasoning cost in this sample | General accuracy equivalence, or a bounded reasoning budget |
| Brief `plan` scored 13/18 under the qualitative rubric, 11/18 under the minimal-pattern check | Packaging a whole sequence can improve completion under a one-response contract | Better visual understanding or a generally superior robot interface |
| `plan` omitted forward in 0/18; other formats omitted it in 4, 10, and 5 trials | Response completeness depended strongly on the interface | The runtime forbids multiple calls, or a proven cause for early handoff |
| `plan` turned unnecessarily in 4/6 centered cases | The simple task is still unreliable under the current specification | Whether the underlying failure is perception, an implicit centering threshold, or reasoning |
| Approximately 94% of generated tokens were reasoning; two-action native encodings use 17–27 tokens | Further syntax savings are small relative to current reasoning cost | An engine throughput bottleneck caused by the number of tool declarations |

Primary evidence: [thinking and format results](THINKING_RESULTS.md), [earlier format study](FORMAT_RESULTS.md), and their saved requests/responses. Cross-study quality comparisons are not controlled ablations because prompts, seeds, or interaction contracts changed.

### Why the previous evaluation could mislead us

- **The task was underspecified.** “Face the fridge” had no defined target point, angular tolerance, or camera calibration. A 30° turn can overshoot a slightly off-center target. Neither repeated correct-side turns nor exactly one turn establishes alignment.
- **The primary rubric was too permissive.** It counted three same-direction turns followed by forward as a success. The stricter rubric exposed this, but still lacked geometric ground truth.
- **We mixed three problems.** Identifying the fridge, deciding the action sequence, and expressing that sequence as native calls were scored together. Output reasoning is useful for inspection, not ground truth for the model's internal computation.
- **One response was an implementation constraint.** A turn-only response is incomplete for our requested plan, but it can be a sensible first action in a loop that observes again before advancing. `plan` also changes operation granularity, not just argument spelling.
- **Seeds were mistaken for breadth.** Many trials on three images characterize sampling variation on those images, not visual generalization. Mode selection used the plan schema, so mode-by-interface interactions remain untested.
- **Successful-only latency is selective.** Different interfaces succeed on different examples. It should accompany all-trial latency and matched-input/matched-correctness comparisons, not independently rank systems.
- **A synthetic static image is not a motion environment.** It supplies no validated distance, free-space guarantee, or observation after a turn. PNG size and tool serialization are downstream of this measurement problem.

## First-principles design

A useful next action requires an observation, an objective with a tolerance, and a rule relating them. For horizontal alignment, the key state is target bearing, not a prose description of the whole kitchen.

With a calibrated, distortion-corrected pinhole camera, a target at horizontal pixel x has bearing `atan((x - cx) / fx)`, where cx is the optical center and fx is horizontal focal length in pixels. This follows from the [camera projection model](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html), not from an assumption that the current images provide fx. Expressing the viewing ray in robot coordinates requires camera-to-robot orientation; a bearing from a different robot origin also depends on camera offset and target depth.

For the first offline diagnostic, avoid pretending we know those values. Define a measurable **image-centering task**:

- Target point: horizontal center of the visible refrigerator front. Annotate the relevant front region; exclude uncertain/occluded cases from forced coordinate ground truth and label them explicitly.
- Coordinate: x divided by image width, from 0 to 1, increasing to image right.
- Example deadband: `[0.45, 0.55]` is aligned. This 10%-wide band is a proposed experimental tolerance, not a robot safety or navigation threshold. Freeze it before testing.
- Expected decision: left of the band → `turn_left`; right → `turn_right`; inside → `aligned`; no uniquely identifiable target → `unknown`.
- Boundary cases: use an annotation uncertainty interval. If it crosses a threshold, use a predefined acceptable decision set and report it separately; do not force an arbitrary exact label.

There is deliberately no forward action in this first diagnostic. Image centering alone does not establish clearance or distance. “Aligned” means hold and report alignment, not permission to walk. After image centering works, a separately evaluated approach controller can use calibrated bearing, depth/clearance, and fresh feedback.

### Three diagnostic paths

| Path | Input | Model output | Downstream responsibility | What failure tells us |
| --- | --- | --- | --- | --- |
| A: direct action | Image + target + explicit deadband/action rule | One `decide(action)` native call | Validate enum; record mock decision | End-to-end next-action error, still not localized |
| B: explicit location | Same image and target definition | One `locate_target(status, x)` native call; x only when visible | Validate status/range; apply the exact deterministic rule | Coordinate/presence errors are inspectable; controller arithmetic is testable independently |
| C: oracle-location control | Human-annotated target state as text + the same rule | Same `decide(action)` as A | Validate and compare | Errors persist even when visual estimation is removed |

Proposed statuses are visible, absent, or ambiguous. A model saying “confident” is not treated as calibrated probability. The evaluator retains missing calls, malformed arguments, ordinary prose, abstentions, and truncations as separate outcomes.

All paths use one response, one native call, and no final acknowledgement. Freeze the schema rather than rerunning a syntax search. Ask for concise structured output with thinking off initially; the hypothesis is that the narrower task does not need hundreds of reasoning tokens. Use the same explicit sampler, images, runtime, and seed schedule for A/B. A single seed is only a diagnostic screen; repeat boundary/error cases to measure sampling instability without counting repeats as independent scenes.

If a path fails, a matched brief-thinking check on development cases can test whether reasoning helps. Do not repeatedly tune prompts against held-out labels, and do not conclude model incapability from a single failed configuration.

## Proposed smallest useful experiment

### 1. Freeze labels and controls before changing prompts

Prepare 12 development images covering clear left/right/center, positions near the deadband, absent targets, and ambiguity/occlusion. Prefer real camera images and several distinct rooms or capture sequences. The existing generated images remain regression controls, not the entire benchmark. Verify image decoding and record the actual vision preprocessing/token budget; identical source resolution alone does not guarantee identical model input. Keep these settings fixed across A/B.

Reserve 24 additional images before prompt tuning. Split by room/capture sequence, not neighboring frames; transformations of the same source belong to the same split. If only one room is available, describe the result as within-room testing. Review target annotations independently of any model output.

The 12-image screen is for fault isolation. Neither it nor the 24-image holdout certifies deployment reliability.

### 2. Run 36 initial diagnostic requests, then inspect

- A and B on the 12 development images: 24 image requests.
- C on 12 matched annotated states: 12 text requests.
- Preserve original responses, exact prompts/template, annotations, model/preprocessor versions, and timings.

No broad hyperparameter search. First inspect whether errors come from target location/presence, threshold use, or native output completion. A programmatic oracle-coordinate-to-rule check should be exact; it validates the evaluator, not the VLM.

After freezing the resulting prompts/configurations, run A and B once on the 24 held-out images (48 requests). Report the paired results before considering further changes. Additional seeds quantify stability; they do not increase the count of distinct test scenes.

### 3. Use decision-relevant metrics

- **Primary:** correct next action per distinct image; confusion matrix separating left/right, aligned, and unknown. Report wrong turns on centered targets and movement decisions on absent/ambiguous targets explicitly.
- **Perception:** target presence/ambiguity accuracy and horizontal localization error in pixels and fraction of width; distributions and worst cases. Score points outside valid image bounds as invalid, not clipped successes.
- **Contract:** valid call rate and unwanted output. Keep this separate from semantic accuracy.
- **Latency:** time from submitted image to complete validated decision, including deterministic postprocessing for B; report all-trial median/range and paired per-image differences. Also show latency on cases where both arms are correct, plus tokens/prefill/decode breakdown. Short failures never count as useful fast decisions.
- **Coverage:** distinct rooms/sequences/images and near-boundary/absent subsets. Display a case-by-case panel; avoid a single aggregate score hiding center failures.
- **Reproducibility:** identical cold-KV policy and hardware conditions, randomized A/B order, no concurrent inference. Keep Mac observations separate from later Orin tests.

Do not choose an arm using an unsupported universal accuracy threshold. Prefer a clear paired reduction in meaningful errors without an offsetting latency cost; if results are mixed or differ by only a case or two, report uncertainty and collect independent scenes. If accuracy is comparable, prefer A's simpler direct interface unless B's observability is useful enough to justify the extra contract. No result from this small set authorizes physical movement.

## Alternative explanations and what would change the recommendation

**Strongest counterargument:** explicit coordinate prediction may be harder for this compact VLM than choosing a coarse action. Numeric grounding can introduce a new error source. If A is more accurate or equally accurate and faster, keep direct actions; do not force a perception interface for architectural neatness.

**If C succeeds and B localizes poorly:** perception/grounding is the immediate bottleneck. Before attributing this to the model, check image preprocessing and test a supported higher-detail budget on development cases if warranted. Then evaluate a detector or grounding model on the same labels before spending more effort on tool syntax. These are candidate experiments, not claims about untested model availability or superiority.

**If B is accurate and A misuses the deadband:** the deterministic rule is a useful separation. Extend it toward bounded yaw control with calibrated intrinsics/extrinsics and observed post-action error reduction. Only then evaluate approach motion with depth/clearance.

**If C fails:** simplify/verify the symbolic rule, schema, template and parser first. A valid tool call is not evidence that the correct operation was selected.

**Cheap optional control on the old experiment:** 14 saved off-center responses stopped after a correct-side turn. One truthful mock-recording tool result and one continuation, preserving the original assistant reasoning/call as required by the [Gemma tool-turn protocol](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4), would test sensitivity to the handoff contract. Do not claim a turn occurred, add an answer hint, or treat this as navigation validation. Record rescue rate and cumulative latency. Recovery would not prove the cause of the original stopping behavior: extra computation and added context are alternative explanations. This can qualify the old conclusion, but is less valuable than improving the visual ground truth; it is not the main proposed next step.

## Scope boundary

This checkpoint preserves the current brief-thinking/plan default and all historical findings. The proposed next experiment has not been implemented or run. Real control will need calibrated camera/robot frames, bounded yaw commands, updated observations, termination conditions, and physical stop/recovery behavior. An action selected correctly from a stale frame can still be wrong when executed; full-loop outcome and latency must eventually be measured together.
