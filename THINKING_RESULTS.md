# Brief thinking and tool-interface evaluation

## Approach

Keep Google's installed chat template unchanged. Use its existing `enable_thinking` flag and add a reasoning-style instruction to the ordinary system prompt. The template owns protocol serialization; the system prompt owns the desired behavior. Injecting the same instruction through a template edit would provide no intrinsic token-cost advantage and would mix these responsibilities.

The brief profile enables thinking and appends exactly:

> Use brief, efficient reasoning. Avoid repetition and unnecessary elaboration.

This is our neutral test instruction, not a canonical Google prompt. It gives no image/answer hints, hard reasoning limit, or extra action guidance. The common base prompt clarifies that tool-only output applies outside the thought channel. The model is still asked for one complete ordered mock plan in one response, without a follow-up acknowledgement.

Google documents system instructions as a way to reduce reasoning length while the native feature remains a Boolean switch. Its reported approximate 20% token reduction is not a guarantee for this model or workload. [Google prompt-formatting guidance](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4#tip_adaptive_thought_efficiency_using_system_instructions).

Predeclared design and selection rule: [THINKING_HYPOTHESIS.md](THINKING_HYPOTHESIS.md).

## Stage 1: choose a thinking mode

Fixed `plan(actions)` schema; three existing images; seeds 301–303; randomized mode order and scene/seed blocks; 27 inference requests. Temperature 1, top-k 64, top-p 0.95, min-p 0. The model/template/images/action semantics and all base instructions are identical across modes. Each request starts a fresh logical task and disables prompt KV reuse. No output-token cap.

| Mode | Qualitative successes /9 | Median request latency | Median latency on successful plans | Mean reasoning-text tokens | Mean total completion tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Off | 4 | 1.151 s | 1.141 s | 0 | 14.6 |
| Normal thinking | 7 | 8.439 s | 9.136 s | 428.8 | 453.1 |
| Brief thinking | 7 | 6.110 s | 6.110 s | 285.9 | 310.2 |

**Selected brief thinking.** It matched normal thinking's success/failure pattern on all nine scene/seed pairs, reduced mean reasoning-text tokens by 33.3%, and reduced overall median request latency by 27.6%. This is observed parity in a small pilot, not a statistical equivalence claim.

| Mode | Center /3 | Left /3 | Right /3 |
| --- | ---: | ---: | ---: |
| Off | 3 | 0 | 1 |
| Normal | 1 | 3 | 3 |
| Brief | 1 | 3 | 3 |

Thinking helped the off-center cases and hurt the center case in this pilot. It is not uniformly beneficial. The accuracy-first selection rule then used successful-plan latency as its tiebreaker.

All 27 responses had valid native calls, empty ordinary answer content, and compliant thinking behavior. Cache reuse was zero. The installed template remained identical before and after the pilot. Raw reasoning was retained in response artifacts, not fed into another inference, because each trial ends after its one plan response.

### Grading limitation

The primary rubric checks turn direction/order and exactly one final forward step, with no unrelated translation. It permits multiple turns in the correct direction and does not establish metric alignment.

Normal and brief each produced two plans with repeated turns. Both score 5/9 under the stricter syntactic pattern of exactly one turn then forward, or forward alone for center; off scores 4/9. This secondary pattern is not calibrated angular ground truth either. Normal's repeats were two right turns and three left turns; brief's were three right turns and two left turns. Do not equate the primary 7/9 score with successful physical navigation.

[All pilot trials](experiments/20260917T044508.244815Z-thinking/trials.json), [aggregates](experiments/20260917T044508.244815Z-thinking/aggregate.json), [selection](experiments/20260917T044508.244815Z-thinking/selection.json), [settings and source hashes](experiments/20260917T044508.244815Z-thinking/manifest.json).

## Stage 2: tool-interface comparison

The completed comparison used the frozen brief profile, four formats, three images, and new seeds 401–406: 72 inference requests. Format order and scene/seed blocks were randomized. Every request disabled prompt KV reuse; there were no same-frame warm repetitions. Sampling, image bytes, model, template, goal, base prompt, and four-action budget were held fixed.

| Interface | Qualitative successes /18 | Exact minimal pattern /18 | Median request latency, all trials | Median latency, successful plans | Mean completion tokens | Mean reasoning-text tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `move(direction)` | 11 | 11 | 8.376 s | 8.383 s | 397.3 | 372.1 |
| Separate `move(direction)` / `turn(direction)` | 5 | 5 | 5.812 s | 5.875 s | 285.5 | 265.2 |
| Six no-argument tools | 11 | 9 | 8.036 s | 7.570 s | 373.7 | 354.4 |
| `plan(actions)` | **13** | **11** | **6.694 s** | **5.474 s** | 325.4 | 302.1 |

“Exact minimal pattern” means `[forward]` for center or `[correct_turn, forward]` for either side. As above, this is a stricter syntactic check, not measured angular alignment. The primary rubric was fixed before measurement; this secondary result exposes its tolerance for repeated turns.

| Interface | Center /6 | Left /6 | Right /6 | Responses missing forward /18 |
| --- | ---: | ---: | ---: | ---: |
| `move(direction)` | 3 | 3 | 5 | 4 |
| Separate move / turn | 2 | 2 | 1 | 10 |
| No-argument tools | 3 | 3 | 5 | 5 |
| `plan(actions)` | 2 | 5 | 6 | **0** |

**Selected `plan(actions)` under the predeclared accuracy-first rule.** It produced the complete requested turn-then-forward sequence most often under the primary rubric, and no trial omitted forward. Its two repeated-turn plans each contained three correct-side turns. Under the minimal-pattern criterion, it ties `move(direction)` at 11/18, but remains faster on matching successes: median 5.391 s versus 8.383 s. These few scenes do not establish a generally superior interface.

All 72 responses had valid native calls, empty ordinary answer content, compliant thinking behavior, and zero cached prompt tokens. There were no operational errors or truncations. The template was unchanged before/after and matched the pilot's template.

### What explains the result?

**Serialization cost behaves as predicted, but it is small relative to thinking.** The active tokenizer/template gives the following reference counts, including the native tool handoff marker and excluding reasoning. These are generated protocol tokens, not the size of the API's returned JSON wrapper.

| Interface | Tool-declaration token increment | One forward action | Turn + forward | Four alternating actions |
| --- | ---: | ---: | ---: | ---: |
| `move(direction)` | 88 | 13 | 27 | 53 |
| Separate move / turn | 118 | 13 | 25 | 49 |
| No-argument tools | 154 | 9 | 17 | 33 |
| `plan(actions)` | 96 | 13 | 19 | 29 |

Removing arguments saves repeated argument syntax during generation but adds tool declarations to the input. A list amortizes the call wrapper over several actions and becomes shortest in this four-action reference. Tool choice is still next-token prediction over the same model vocabulary; six declared functions do not require six separate model evaluations. Names and schemas can nevertheless change the model's learned behavior and reasoning length.

Across this experiment, retokenized reasoning accounts for approximately **94%** of reported completion tokens. The 10-token difference between the two-action `move` and no-argument encodings corresponds to only about 0.17–0.24 s at the observed decode rates. Differences of hundreds of reasoning tokens dominate that saving. Median decode rates by format were 58.4, 57.5, 52.8, and 58.1 tokens/s respectively; they do not demonstrate that shorter tool syntax makes the underlying model compute faster. Host performance varied during the run.

**The interface also changes where a plan ends.** `plan(actions)` places the entire ordered sequence inside one function call. Other interfaces must emit multiple calls before yielding a tool response. In inspected failures, reasoning described both actions but the parsed response contained only the turn: see [combined](experiments/20260917T044806.831756Z/014-right-combined-cold/turn-01-response.json), [split](experiments/20260917T044806.831756Z/015-right-split-cold/turn-01-response.json), and [atomic](experiments/20260917T044806.831756Z/016-right-atomic-cold/turn-01-response.json). They did not explicitly request feedback. A learned tendency to yield after one action is a plausible explanation, not a proven cause. Successful multi-call responses show that the runtime does not impose a one-call limit.

This is therefore a **tool-interface comparison**, not a clean test of token spelling alone. A plan tool changes action granularity as well as serialization. For a controller deliberately choosing one action per observation, the smaller no-argument interface could be preferable; that is a different objective from completing a multi-action plan in one response.

**Brief thinking is not bounded thinking.** The slowest trial took 16.413 s, and even `plan` reached 16.178 s. The selected interface still failed the centered scene in 4/6 trials. It is the provisional best configuration for this mock task, not a reliable robot policy.

[All format trials](experiments/20260917T044806.831756Z/trials.json), [aggregates](experiments/20260917T044806.831756Z/aggregate.json), [selection](experiments/20260917T044806.831756Z/selection.json), [native token counts](experiments/20260917T044806.831756Z/encoding-counts.json), [settings and source hashes](experiments/20260917T044806.831756Z/manifest.json), [template verification](experiments/20260917T044806.831756Z/verification.json).

## Applied defaults

[runner-defaults.json](runner-defaults.json) now selects brief thinking and `plan`. Existing CLI switches retain every alternative. One inference response is recorded per trial; no acknowledgement or tool-feedback request follows it. No custom template, hard thought budget, or `preserve_thinking` override was introduced.

```bash
python3 -B /Users/junda/robot/harness/run.py --suite
```

The request sets `chat_template_kwargs: {"enable_thinking": true}` and appends the brief suffix to the normal system message. The installed template renders native thinking/tool tokens. Editing a template to emit the exact same token sequence cannot provide a model-level advantage over supplying the corresponding system content.

Each trial is a new logical task. If the harness later adds a tool-feedback loop, preserve the assistant reasoning and calls during that unfinished logical turn; do not carry raw thinking indiscriminately into new user turns. That conversation-history concern is separate from the brevity instruction. [Google thought-context guidance](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4).

## Measurement scope

- Same local Google Gemma4 E4B QAT Q4_0 model and multimodal projector, llama.cpp b10909-a2878d30d. These are Mac measurements, not Orin NX results.
- Cold means no prompt KV reuse, not unloaded weights or flushed hardware/image caches.
- Request latency includes the inference HTTP exchange but excludes artifact writes and subsequent reasoning-text tokenization.
- Reasoning-text token counts retokenize the returned reasoning field. They exclude channel markers and can differ at fragment boundaries from original generated token counts. Total completion tokens are the server's reported full generation count.
- Modes/formats are compared with fixed sampling and paired seed labels; changed tokenization/prompt content means these are not identical random semantic choices.
- New seeds on the same three synthetic images provide replication, not held-out visual generalization. Host clocks/background load are uncontrolled. The mode was selected with the plan schema, so mode-by-format interactions remain possible.
- The earlier thinking-off study used a slightly different base output instruction and different seeds. Its figures provide historical context, not a controlled estimate of thinking's effect on every format.
