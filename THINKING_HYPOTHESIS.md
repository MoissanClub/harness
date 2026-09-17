# Thinking experiment — predeclared design

Keep the installed Gemma chat template unchanged. Its Boolean thinking flag controls native thinking tokens; a system instruction controls desired reasoning brevity. Do not insert protocol tokens manually or enable preserve_thinking globally.

Hypothesis: brief thinking can recover some errors from the earlier thinking-off, one-response planner while reducing output tokens and latency compared with normal thinking. Google reports roughly 20% fewer thought tokens from a LOW instruction, but its page does not establish the outcome for these scenes or E4B. This is a soft instruction, not a hard token cap.

The only mode-specific changes are:

- off: enable_thinking=false, no suffix;
- normal: enable_thinking=true, no suffix;
- brief: enable_thinking=true, append prompts/brief-thinking.txt: “Use brief, efficient reasoning. Avoid repetition and unnecessary elaboration.”

All modes share the same short base prompt. Its output rule is clarified to apply outside the thought channel, so valid reasoning is not accidentally prohibited. Consequently, rerun a fresh off control rather than treating the previous off study as an exact matched baseline.

## Stage 1: select a thinking mode

Use the plan schema, all three existing images and seeds301–303: nine trials per mode,27 total. Randomize scene/seed blocks and mode order using schedulerseed20260918. Disable prompt KV reuse in every trial. Keep model/server, tool semantics, user goal, image bytes, four-action budget, single response/no acknowledgement, and sampling identical. Sampling comes from evaluation-sampling.json. No generation cap.

Success requires valid native calls, no ordinary answer prose, the existing qualitative scene rubric, and no generated reasoning when mode=off. Reasoning is allowed in normal/brief. Record total completion tokens and separately retokenize the extracted reasoning text; fragment counts omit channel delimiters and may differ at boundaries from original generated token counts. Tokenization requests occur after the measured inference request.

Select the mode with most successes. Break ties by lowest median request latency among its successful plans; if there are no successes, use overall median latency. Report both successful-plan and overall latencies so short failures cannot silently win. This is a small pilot: one sample is11.1 percentage points. Selection on the plan schema does not establish the best mode for every schema.

## Stage 2: rerun tool formats

Freeze the selected mode and suffix, then compare combined,split,atomic,plan using all three images and new seeds401–406:18 trials per format,72 total. Randomize format order and scene/seed blocks. Use cold prompt KV in every trial; do not repeat identical frames just to obtain optimistic cached latencies. Keep all failures. Rank success first, then successful-plan median latency, and report total/reasoning output token counts.

This is replication with new seeds on the same three synthetic images, not held-out visual generalization. Tokenization advantages can be overwhelmed by variable reasoning length. The output rules and schemas remain the same across stage2; the template must have the same SHA256 before and after both stages.

After reviewing results, update runner-defaults.json to the best observed mode/format for this mock evaluation. Preserve every source snapshot and previous experiment. Do not command hardware.

Source: https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4#tip_adaptive_thought_efficiency_using_system_instructions
