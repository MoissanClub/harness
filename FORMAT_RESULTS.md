# Tool format evaluation: shorter output helps, incomplete plans do not

## Changes delivered

- `enable_thinking: false` in `request-defaults.json`.
- One model response per request. The host validates/records the complete plan and stops; no tool-feedback continuation or final acknowledgement request.
- System prompt reduced from 247 to 61 whitespace-separated words. Camera frame, action increments, ordering, budget and mock status remain. The previous prompt is preserved as `prompts/system-sequence-v2.txt`.
- Four interchangeable native tool schemas in `tools.py`: `combined`, `split`, `atomic`, `plan`. All normalize to the same six actions; no hardware is connected.
- Full requests, responses, settings, source snapshots, cache counts and timings are retained. The ordinary runner still defaults to `combined`; choose another with `--format`.

## First-principles prediction

The choice among six actions contains the same information whether expressed through six function names or six argument values. Six tools do not require six model passes: the model still generates through its vocabulary. Tokenization and the serialization protocol determine how many autoregressive steps express that choice.

Approximate request latency is visual/input processing plus uncached prompt processing plus output decoding plus transport/runtime overhead. At fixed model/hardware/context, fewer output tokens usually reduce latency without materially increasing the decoder's tokens/second. More tool declarations cost input tokens; cached prefixes reduce that cost. Learned function-use conventions can change correctness and whether the model emits a whole sequence.

Predictions were saved before the experiment in [FORMAT_HYPOTHESIS.md](FORMAT_HYPOTHESIS.md). In particular, atomic tools were expected to shorten outputs but lengthen declarations; a list-valued plan tool could amortize repeated call delimiters.

## Exact template/tokenizer measurements

These are measured with the installed model tokenizer and active chat template, including the tool-response stop marker. They are native model output counts, not token counts of API-generated JSON wrappers or call IDs.

| Encoding | Extra input tokens for declarations | One forward action | Turn left + forward | Four alternating turn/forward actions |
| --- | ---: | ---: | ---: | ---: |
| `move(direction)` | 88 | 13 | 27 | 53 |
| Separate `move(direction)` / `turn(direction)` | 118 | 13 | 25 | 49 |
| Six no-argument functions | 154 | 9 | 17 | 33 |
| `plan(actions)` | 96 | 13 | 19 | 29 |

The function names are not necessarily single tokens. For two actions, atomic tools save ten output tokens but add 66 input tokens relative to `combined`. `plan` saves eight output tokens while adding only eight input tokens. With four actions, `plan` is shorter than atomic tools on both sides. The four-action row is a tokenizer measurement, not a four-action inference benchmark.

[Exact native strings and counts](experiments/20260917T041437.446966Z/encoding-counts.json).

## Experiment 1: visual planning

144 serial requests = three existing kitchen images × four formats × six seeds × two cache conditions. Format order and scene/seed block order were shuffled reproducibly. Temperature 1, top-k 64, top-p 0.95, min-p 0; thinking off; no output-token cap. Same system/user prompt and action semantics throughout.

Cold means `cache_prompt:false`, with zero reused prompt tokens. It does not mean unloaded weights or flushed kernel/image caches. Warm immediately repeats the exact image, prompt and seed with caching enabled. Only five prompt tokens were newly evaluated in every warm request. Cold/warm outputs matched for all 72 pairs, so they are not 144 independent quality observations.

| Encoding | Center /6 | Left /6 | Right /6 | Total /18 | Median cold request | Median warm request |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `combined` | 1 | 2 | 2 | 5 | 1.158 s | 0.319 s |
| `split` | 0 | 3 | 5 | 8 | 1.431 s | 0.509 s |
| `atomic` | 0 | 1 | 2 | 3 | 1.244 s | 0.306 s |
| `plan` | 3 | 1 | 3 | 7 | 1.208 s | 0.386 s |

**Every response had valid native calls, no prose, and zero returned reasoning characters. Task accuracy was poor despite perfect protocol validity.** Failures included wrong turn direction, unnecessary turns, strafing instead of rotating, and omitting forward. `combined` and `atomic` included exactly one final forward action in only 9/18 samples; `split` did so in 16/18 and `plan` in 17/18. These completeness counts do not establish correct turning.

The latency columns include failures and are not a ranking of equivalent completed work. For example, returning only a turn is cheaper than completing the requested turn plus forward step.

For responses with the identical canonical sequence `turn_right,forward`, median cold/warm times were: combined 1.403/0.546 s (n=2 each), split 1.434/0.511 s (n=10), atomic 1.309/0.388 s (n=6), plan 1.253/0.413 s (n=4). These groups span different scenes/seeds and include visually incorrect plans; they are descriptive, not a controlled quality comparison.

Median decoder rates across formats were about 56–60 tokens/s. Cold prompt-phase medians were 0.892, 0.948, 0.994 and 0.894 s respectively. The measured extra declaration cost is real; faster total completion mostly comes from emitting fewer tokens. Do not interpret short-response throughput differences as a new faster decoder.

[All trials](experiments/20260917T041437.446966Z/trials.json), [aggregates](experiments/20260917T041437.446966Z/aggregate.json), [settings/source manifest](experiments/20260917T041437.446966Z/manifest.json).

## Experiment 2: isolate serialization from vision

The image was removed and the instruction explicitly specified: “Rotate left in place, then translate forward one step. Include both actions in this response.” Same system prompt, tools, sampling and thinking setting. Four formats × three new seeds × cold/warm = 24 requests. Success requires exactly `turn_left,forward` with tool-only output.

| Encoding | Exact sequence, each cache condition | Actual output tokens | Median cold request | Median warm request |
| --- | ---: | ---: | ---: | ---: |
| `combined` | 3/3 | 27 | 1.116 s | 0.620 s |
| `split` | 3/3 | 25 | 1.152 s | 0.592 s |
| `atomic` | **0/3** | **9: only turn left** | 0.856 s | 0.264 s |
| `plan` | 3/3 | 19 | **0.926 s** | **0.461 s** |

Again, all 24 responses had native valid calls, no prose/reasoning, and identical cold/warm action sequences. Atomic tools omitted forward in every sample, even with no visual decision. This is not evidence of a universal runtime inability to return multiple no-argument calls: the visual experiment contains valid examples of doing so.

Among complete responses, `plan` reduced tokens by 29.6% and median request latency by 17.0% cold / 25.6% warm versus `combined`. Decoder medians for the successful formats were similar, approximately 47–49 tokens/s. Absolute throughput differed from the earlier vision experiment; the host's clocks/background load were not controlled. Compare formats within each experiment, not throughput across experiments.

[Text-only prompt](experiments/20260917T041743.106392Z-serialization/prompt.txt), [all trials](experiments/20260917T041743.106392Z-serialization/trials.json), [aggregates](experiments/20260917T041743.106392Z-serialization/aggregate.json).

## Recommendation and limits

For this **one-response ordered mock planner**, `plan(actions)` is the best next candidate: compact schema, fewer output tokens, explicit ordering in one array, and fewer missing-step failures. This is a format recommendation, not a claim that its visual decisions are sufficiently reliable. Split `move`/`turn` had the highest visual score here, 8/18 versus 7/18; three scenes do not justify declaring a robust quality winner.

For an execution loop that intentionally observes again after every action, a small fixed set of no-argument tools remains promising: a single action per response would be complete work, and those tools have the shortest single-action encoding. Once actions need variable angles, distances or speeds, parameterized tools scale better than enumerating a function for every value.

The main hypothesis was partly confirmed: output token savings translated into latency savings. Its strongest counterargument also appeared: the shortest-looking interface produced incomplete plans. Token count alone does not predict usable-task latency. The list-valued plan tool won the controlled complete-sequence comparison; atomic tools did not.

Remaining uncertainties: only three synthetic images and three/six seeds per condition; equivalent semantics but naturally different wording in declarations; fixed cold-before-warm order; uncontrolled host load; no calibrated camera/depth; no physical execution; no Jetson measurement. Repeated exact-frame caching is optimistic for changing video. The qualitative scene rubric checks turn sign/order and one forward step, not metric alignment; repeated same-side turns can pass.

These changes jointly disable thinking, shorten prompts/descriptions, and switch to one-response planning. The accuracy difference from historical thinking-on runs cannot be assigned to any one change. It does not establish a capability limit of Gemma E4B.

The smallest follow-up that would change the recommendation is a held-out set of left/center/right views with paired `plan` versus `split` trials. A repeatable quality advantage for `split` could outweigh a few tenths of a second. If failures persist in both, isolate prompt shortening and reasoning settings with a separate controlled ablation before blaming model capacity. Thinking remains off in the delivered configuration.

## Reproduce

```bash
python3 -B /Users/junda/robot/harness/check.py
python3 -B /Users/junda/robot/harness/run.py --case right --format plan
python3 -B /Users/junda/robot/harness/evaluate_formats.py
python3 -B /Users/junda/robot/harness/serialize_formats.py
```

Model: Google's `gemma-4-E4B-it-qat-q4_0-gguf`, alias `gemma4-e4b`, multimodal projector loaded, llama.cpp `b10909-a2878d30d`, local Mac. Complete server properties and model snapshot paths are saved with the experiments. Measurements taken September 16, 2026 local time (September 17 UTC).

Primary protocol references: [Google Gemma function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4), [Google thinking controls](https://ai.google.dev/gemma/docs/capabilities/thinking), and the [installed llama.cpp revision's prompt-cache implementation](https://github.com/ggml-org/llama.cpp/blob/a2878d30d/tools/server/server-context.cpp#L2941). Empirical claims above come from the local saved measurements.
