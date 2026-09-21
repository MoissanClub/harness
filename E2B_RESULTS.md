# Gemma 4 E2B local evaluation

Measured 2026-09-18 (America/Los_Angeles). **E2B with brief thinking produced 5/9 correct minimal plans, with 4.409 s median request latency and 87.62 generated tokens/s.** These are Mac measurements of the running setup, not Orin NX results or a general robotics capability score.

## Test and serving configuration

- 27 serial inference requests: three existing 720×480 kitchen images × seeds 301–303 × thinking off/normal/brief. Each asks the robot to face the fridge and take one step toward it.
- Fixed `plan(actions)` tool, at most four actions; translation 0.25 m and turns 30° in place. One inference response per trial, no final acknowledgement, no hardware execution.
- Temperature 1, top-k 64, top-p 0.95, min-p 0; no output-token cap. Randomized order matches the historical E4B thinking pilot. Every request disables prompt KV reuse; observed cached-token counts are zero. Weights remain loaded.
- Alias `gemma4-e2b`, local API port 8080; llama.cpp `b10909-a2878d30d`, four slots, 131072-token context reported by the server.
- Weights: Unsloth `gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf`, repository snapshot `66a399f68ddd113b06dff02fca9523e55465d11d`. The server reports `model_ftype: Q4_0`; that summary does not establish every tensor's quantization. Vision support is enabled; a separate projector path was not captured.
- Active launch command, verified from the running process:

```bash
llama serve -hf unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL --alias gemma4-e2b --gpu-layers all --jinja --spec-type draft-mtp --spec-draft-n-max 2
```

The responses contain nonzero draft/accepted-token counters, confirming speculative decoding occurred. Saved `/props` defaults nevertheless say speculative type `none`; use the launch command and actual response timings to describe this run. No server settings were changed for the evaluation.

## Results

“Minimal plan” means exactly `[forward]` for the centered fridge or `[correct_turn, forward]` for an off-center fridge. All E2B plans passing the original, more permissive direction/order rubric also pass this stricter check.

| Thinking | Minimal pass rate | Median request latency | Observed latency range | Median decode rate | Mean completion tokens | Mean reasoning-text tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Off | 3/9 (33.3%) | 0.665 s | 0.662–0.677 s | 99.77 tok/s | 13.0 | 0 |
| Normal | 5/9 (55.6%) | 5.204 s | 4.339–8.378 s | 87.43 tok/s | 444.7 | 422.3 |
| Brief | 5/9 (55.6%) | 4.409 s | 1.608–9.196 s | 87.62 tok/s | 343.0 | 322.7 |

All 27 responses had valid native tool calls, empty ordinary answer content, compliant thinking behavior, and no truncation. Valid tool syntax therefore scored 100%; correct action choice did not.

| Thinking | Center /3 | Left /3 | Right /3 |
| --- | ---: | ---: | ---: |
| Off | 3 | 0 | 0 |
| Normal | 1 | 1 | 3 |
| Brief | 2 | 1 | 2 |

With thinking off, **every response was `plan(actions=["forward"])`**, so the fast result fails every off-center case. Normal thinking's failures are unnecessary right turns in two centered cases and wrong-direction turns in two left cases. Brief thinking's failures are one unnecessary right turn in a centered case, one wrong-direction turn, and two omitted turns.

Brief and normal have equal pass counts but different successful cases. The predeclared selection rule chooses brief: median latency among successful plans is 4.692 s versus normal's 5.204 s. Its overall median is 15.3% lower and mean reasoning-text count is 23.6% lower. Neither establishes general accuracy parity or a latency bound: brief's slowest response took 9.196 s and failed.

Median prefill time was 0.521 s off and approximately 0.548 s with thinking. Brief reasoning accounts for approximately 94% of completion tokens; generating hundreds of reasoning tokens still dominates latency despite the short final call. In brief mode, 1630 of 2910 drafted tokens were accepted (56.0%); this is not the fraction of output generated speculatively and does not quantify MTP's speedup without an MTP-off control.

## Matched historical E4B comparison

All 27 E2B request JSONs match their historical E4B counterparts except the model alias, including image bytes, tool schema, prompts, sampling, and seeds. The active template differs in comments and serialization of prior assistant calls with string-valued arguments; that branch is unused by these fresh system/user-only requests. The E2B template remained unchanged throughout the run.

| Thinking | E2B minimal /9 | E4B minimal /9 | E2B median latency | E4B median latency | E2B / E4B median decode rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Off | 3 | 4 | 0.665 s | 1.151 s | 99.77 / 60.07 tok/s |
| Normal | 5 | 5 | 5.204 s | 8.439 s | 87.43 / 59.10 tok/s |
| Brief | 5 | 5 | 4.409 s | 6.110 s | 87.62 / 59.56 tok/s |

Under the original permissive rubric, E4B scored 4/9, 7/9, and 7/9. Each thinking-on result includes two repeated-turn plans, explaining the difference from the minimal-plan scores. Neither rubric has calibrated angular ground truth.

The observed E2B brief setup has **27.8% lower median latency and 47.1% higher median decode throughput**, while tying E4B on the minimal-plan count. This is a comparison of serving setups: E2B uses Unsloth's quantized package and MTP drafting; historical E4B used Google's QAT Q4_0 package with no drafting counters. Host load, clocks, and session conditions were uncontrolled. Do not attribute the entire difference to model size or MTP.

## Interpretation and next decision

Brief thinking remains the provisional choice for this diagnostic. E2B is worth evaluating further: this setup is faster, and the stricter score does not show an accuracy loss relative to the small E4B pilot. It is not yet a dependable visual action selector. Three generated images repeated across seeds do not measure visual generalization, task completion, or physical navigation.

The next capability test should use held-out observations and stateful task episodes under the proposed chunk architecture, including progress and failure feedback. If the decision instead requires isolating runtime/model speed, use the same quantization policy and MTP setting, interleave matched workloads, and then measure on Orin. No harness defaults or architecture were changed by this evaluation.

## Evidence and reproduction

- [E2B experiment](experiments/20260919T064513.310750Z-thinking/): full requests/responses, per-trial summaries, source snapshot, active template, server properties, schedule and configuration hashes.
- [E2B aggregate](experiments/20260919T064513.310750Z-thinking/aggregate.json), [trials](experiments/20260919T064513.310750Z-thinking/trials.json), [selection](experiments/20260919T064513.310750Z-thinking/selection.json).
- [E4B matched baseline](experiments/20260917T044508.244815Z-thinking/aggregate.json), [historical interpretation](THINKING_RESULTS.md).

```bash
python3 -B /Users/junda/robot/harness/evaluate_thinking.py --model gemma4-e2b
```

Request latency is the non-streaming inference HTTP exchange, including server processing, but excludes artifact writes and subsequent reasoning-text tokenization. Decode throughput is the server's reported generation rate, excluding prefill. Reasoning counts retokenize the returned text and exclude channel markers; they are an approximate partition of total completion tokens. This run did not measure time to first token. Independently recomputed all 27 response assessments and aggregates; no discrepancies were found.
