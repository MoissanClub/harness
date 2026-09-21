# Gemma 4 vision and mock action plans

Evaluate Google's Gemma 4 E4B through a running llama.cpp server using three 720×480 kitchen images. Every scene receives the same goal: **“Face the fridge and take one step toward it. What tool calls would you run?”**

**Checkpoint:** native tool calling works in these tests, but the three-image studies do not establish reliable visual control. The current direction is complete drink-fetching autonomy using short, revisable skill plans: [TASK_CHUNK_PROPOSAL.md](TASK_CHUNK_PROPOSAL.md). The earlier [retrospective](NEXT_EXPERIMENT.md) remains useful; its single-frame test is now an optional diagnostic. The new architecture proposal has not been implemented or run.

The runner asks for a complete, ordered plan in **one model response**, with at most four actions and no ordinary answer prose. Thinking is configurable. It validates and records the calls, then stops: no tool-feedback request or final acknowledgement is generated. There is no robot SDK, hardware connection, motion, or simulated camera update.

The current thinking-mode and tool-interface results are in [THINKING_RESULTS.md](THINKING_RESULTS.md), with the predeclared design in [THINKING_HYPOTHESIS.md](THINKING_HYPOTHESIS.md). Earlier studies remain in [FORMAT_RESULTS.md](FORMAT_RESULTS.md) (thinking-off formats), [TURN_RESULTS.md](TURN_RESULTS.md) (thinking-on action sequences), and [RESULTS.md](RESULTS.md) (single-action baseline).

## Setup session

Python 3.9+. `run.py` / eval scripts are stdlib-only. Inference packages are in [requirements.txt](requirements.txt). The llama.cpp server must report vision at `/props` before any Run command.

```bash
# Optional helpers only (HF download). Runner is stdlib; inference is C++ llama.cpp.
python3 -m pip install -r requirements.txt

# Gemma 4 E4B QAT Q4_0 GGUF + mmproj (same snapshot as prior experiments)
huggingface-cli download google/gemma-4-E4B-it-qat-q4_0-gguf

# Confirm the C++ llama-server reports vision (default alias gemma4-e4b)
curl -sS http://127.0.0.1:8080/props | python3 -c "import json,sys; p=json.load(sys.stdin); assert p.get('modalities',{}).get('vision'), p"
```

Model file used in saved runs: `gemma-4-E4B_q4_0-it.gguf` from repo revision `4b4a2c1d584be7264f87aac328a1bc739ce81b6c`. Alias `gemma4-e4b`, port `8080`, context 131,072. Start your existing llama.cpp server with that GGUF and its multimodal projector, then continue below.

## Run

```bash
# All three scenes, three trials each
python3 -B /Users/junda/robot/harness/run.py --suite --repeat 3

# One off-center scene with separate no-argument tools
python3 -B /Users/junda/robot/harness/run.py --case left --format atomic

# Explicitly enable brief reasoning
python3 -B /Users/junda/robot/harness/run.py --case right --thinking brief

# Disable prompt KV reuse for this request
python3 -B /Users/junda/robot/harness/run.py --case right --format plan --cache off

# Another server
python3 -B /Users/junda/robot/harness/run.py --suite --base-url http://SERVER:8080/v1
```

Defaults: localhost port 8080, alias `gemma4-e4b`, centered scene, one trial, maximum four actions. Default format and thinking mode are configured once in [runner-defaults.json](runner-defaults.json); explicit `--format` and `--thinking` override them. `--cache default` inherits server behavior; `on` and `off` explicitly set `cache_prompt`. This controls prompt KV reuse, not all possible caches or model loading.

Other options: `--model`, `--seed`, `--max-actions`, `--image /absolute/path.png`, and `--prompt-file /absolute/path.txt`. Custom images have no automatic scene grade. The predefined rubric assumes the bundled goal; inspect results manually if you change it. Exit status is nonzero for invalid calls, ordinary answer prose, unexpected reasoning in off mode, or a predefined scene's qualitative mismatch. Abstentions are saved and counted as failures, without retrying or forcing a call.

## Thinking profiles

| `--thinking` | Native thinking flag | System instruction |
| --- | --- | --- |
| `off` | `enable_thinking: false` | Shared base prompt |
| `normal` | `enable_thinking: true` | Shared base prompt |
| `brief` | `enable_thinking: true` | Base prompt plus [brief-thinking.txt](prompts/brief-thinking.txt) |

The brief suffix asks for efficient reasoning without repetition or unnecessary elaboration. It is a soft instruction, not a token cap or a separate model capability. The harness leaves the installed chat template unchanged and lets it render the native control tokens. All modes request tool calls outside the thought channel; normal/brief may return `reasoning_content`. No mode requests a final acknowledgement.

## Tool interfaces for the same actions

Select an encoding with `--format`; all expose the same six canonical actions. Examples below are illustrative function notation; requests use native API `tools` schemas and responses use `tool_calls`.

| Format | Tools | Turn left, then advance |
| --- | --- | --- |
| `combined` | One `move(direction)` tool; six enum values | `move("turn_left")`, `move("forward")` |
| `split` | `move(direction)` for four translations; `turn(direction)` for left/right rotation | `turn("left")`, `move("forward")` |
| `atomic` | Six tools with no arguments | `turn_left()`, `move_forward()` |
| `plan` | One `plan(actions)` tool containing an ordered array | `plan(["turn_left", "forward"])` |

`plan` also changes the tool's granularity: one function contains the entire sequence, whereas the other formats require multiple calls for multiple actions. Quality differences therefore cannot be attributed solely to token count or argument spelling.

Translation actions `left`, `right`, `forward`, and `backward` move 0.25 m in the planned robot frame. Left/right strafe without rotation. `turn_left` and `turn_right` rotate 30° in place. These constants live in [tools.py](tools.py) and enter the shared system prompt. Later actions use the heading after earlier **planned** turns. The initial camera faces forward; image left/right match robot left/right.

`parallel_tool_calls: true` permits several calls per response. Their array order is sequential plan order; the harness never runs motions concurrently. With `plan`, the inner action array determines order. The budget counts actions, not function calls.

The whole batch is validated before recording: allowed functions, exact arguments, enum values, unique call IDs, and total action count. Saved mock results include `executed: false`, units, and the accumulated plan. These local records are **not sent back to the model**.

## Compare thinking and formats

First compare off/normal/brief while holding the `plan` format fixed:

```bash
python3 -B /Users/junda/robot/harness/evaluate_thinking.py
```

Defaults are three scenes × seeds 301–303 × three modes = 27 requests, all with prompt KV reuse disabled. The pilot shuffles scene/seed blocks and mode order. It selects the most successful mode, breaking ties by median latency on successful plans (overall latency if none succeed), and writes `selection.json` under `experiments/<timestamp>-thinking/`. It does not automatically change runner defaults. Selection is provisional: nine trials per mode and the `plan` schema cannot establish the best mode for every format.

Then compare four formats using the chosen mode and fresh seeds:

```bash
# Replace MODE with off, normal, or brief from the pilot's selection.json.
python3 -B /Users/junda/robot/harness/evaluate_formats.py --thinking MODE --cache-modes cold --start-seed 401
```

This runs 72 requests: three scenes × four formats × six seeds, all cold. New seeds on the same images provide replication, not held-out visual generalization. To run the paired cache comparison instead:

```bash
python3 -B /Users/junda/robot/harness/evaluate_formats.py
```

The default format comparison performs 144 serial requests: three scenes × four formats × six seeds × cold/warm. `--cache-modes paired` is the default; `cold` omits warm repetitions. `--repeats` and `--start-seed` adjust sampling; shared server/model/prompt/action-limit/thinking options are available. Scene/seed blocks and format order are shuffled reproducibly. In paired mode, each cold request (`cache_prompt: false`) is followed immediately by the same prompt and seed with caching enabled.

All evaluation scripts read fixed sampling settings from [evaluation-sampling.json](evaluation-sampling.json). Paired seeds do not imply identical choices across different tokenizations. The format comparison also uses the installed chat template and tokenizer to measure text-only declaration costs and reference encodings for one, two, and four actions, without inference.

Metrics include protocol validity, tool-only answers, thinking compliance, qualitative success, canonical actions, input/cached/evaluated/output tokens, wall latency, prefill/decode times, and decode tokens/s. Vision evaluations also retokenize extracted reasoning text after the timed request; these fragment counts omit channel delimiters and can differ at token boundaries. Format aggregates retain failures and separately group identical canonical plans. Review quality alongside timing: omitted actions can make a bad response look fast. Evaluation scripts exit nonzero for operational errors; quality failures remain in results and do not by themselves change exit status.

**Cache interpretation:** the warm request repeats the exact image, making it an optimistic bound rather than a live-camera benchmark. “Cold” disables prompt KV reuse; it does not reload weights or necessarily flush image, kernel, or other runtime caches. Inspect saved cache counts.

For a diagnostic that removes visual interpretation and fixes the requested sequence:

```bash
python3 -B /Users/junda/robot/harness/serialize_formats.py
```

This sends “Rotate left in place, then translate forward one step. Include both actions in this response.” as text, without an image. It uses the shared system prompt, tool definitions, thinking profile, sampling, and default four-action budget. `--thinking` selects a profile explicitly. Four formats × seeds 201–203 × cold/warm produce 24 requests. Success requires exactly `["turn_left", "forward"]`, valid calls, no ordinary prose, and no reasoning when off. An optional `--prompt-file` changes the instruction but not that exact-sequence rubric. Artifacts go under `experiments/<timestamp>-serialization/`, including source/configuration snapshots, prompt, schedule, every request/response, summaries, and aggregates.

## Configuration and artifacts

- [prompts/system.txt](prompts/system.txt): minimal camera/frame context, fixed increments, action budget, ordering, and tool-only output. It gives no expected turn direction.
- [prompts/user.txt](prompts/user.txt): identical goal for every scene.
- [prompts/brief-thinking.txt](prompts/brief-thinking.txt): appended only in brief mode; no template edits.
- [cases.json](cases.json): image paths and host-only labels. Neither filenames nor labels enter model messages; image bytes precede goal text.
- [runner-defaults.json](runner-defaults.json): default format and thinking profile.
- [request-defaults.json](request-defaults.json): tools auto, multiple calls enabled, min-p 0, non-streaming output. Thinking flags are derived from the selected profile.
- [evaluation-sampling.json](evaluation-sampling.json): shared explicit sampling settings for experiments. Ordinary runs inherit temperature/top-k/top-p from the server. No runner imposes an output-token cap.
- [check.py](check.py): offline checks of encodings, ordering, rejected calls, budgets, grading, and image dimensions.

Ordinary trials create `runs/<timestamp>-<scene>-<format>/` containing:

| File | Contents |
| --- | --- |
| `input.json` | Image path, dimensions/SHA-256, format, thinking profile, action budget, host-only rubric |
| `server-props.json` | Server properties, including build and model path |
| `turn-01-request.json` | Complete API request, including image base64 data URL |
| `turn-01-response.json` | Complete returned API response: content, calls, usage, timings |
| `turn-01-tool-results.json` | Local mock records; never sent to the model |
| `summary.json` | Parsed plan, protocol/output checks, assessment, latency |
| `error.json` | Operational error, when applicable |

Experiments create timestamped directories with numbered trials containing the same artifacts. Shared top-level files include `manifest.json` (settings/source hashes), `schedule.json`, `server-props.json`, `active-chat-template.jinja`, `trials.json`, and `aggregate.json`. Format experiments add four `<format>-prompt.txt` renderings and `encoding-counts.json`; the thinking pilot adds `selection.json`. A `source/` snapshot preserves code, configuration (including defaults and sampling), prompts, and applicable pre-measurement hypotheses. Results update after each trial. Earlier runs and failures remain intact.

## Images and evaluation limits

| Scene | Exact input | Generation prompt |
| --- | --- | --- |
| Center | [kitchen-720x480.png](assets/kitchen-720x480.png) | [image.txt](prompts/image.txt) |
| Left | [kitchen-left-720x480.png](assets/kitchen-left-720x480.png) | [image-left.txt](prompts/image-left.txt) |
| Right | [kitchen-right-720x480.png](assets/kitchen-right-720x480.png) | [image-right.txt](prompts/image-right.txt) |

Images were generated with the built-in image generator; left/right used the original kitchen as a reference. Original 1536×1024 files remain as `assets/kitchen[-left|-right]-source.png`. Inputs were resampled without cropping to exactly 720×480 with macOS `sips`. Gemma receives only those resized bytes, never generation prompts. These independently generated views have some layout differences; they are not calibrated camera poses.

Checks are separate:

- **Protocol (`protocol_ok`):** native calls validate and stay within the action budget.
- **Tool-only answer (`tool_only_answer`):** valid calls with no ordinary answer prose; reasoning is allowed.
- **Thinking compliance (`thinking_compliant`):** off mode produces no reasoning; normal/brief permit it.
- **Legacy strict output (`only_tool_output`):** valid calls with neither prose nor reasoning. Preserved for old reports; it is not the success criterion for thinking-enabled runs.
- **Left/right scenes:** matching turn before exactly one forward step, no opposite turn or unrelated translation, forward last.
- **Center:** exactly one forward step without rotation.

Multiple correct-side turns can pass the rubric. It does not establish exact alignment or the optimal number of 30° turns. Truncations, abstentions, and malformed output are saved rather than accepted as complete plans.

A single synthetic image provides no calibrated bearing, depth, or collision clearance. Repeated samples of three images measure these scenes, not general navigation reliability. This is one-response planning, not adaptive execution: a real robot needs bounded motion, fresh observations, and controller feedback. Mac results do not establish Orin NX compatibility or throughput. Historical thinking-on runs changed multiple settings and are not a controlled ablation of thinking alone.

## Inspect the model protocol

```bash
python3 -B /Users/junda/robot/harness/inspect_protocol.py /Users/junda/robot/harness/runs/20260917T005418.836090Z-right
```

This accepts a saved run directory, including any current tool format or a historical run. It uses `/props`, `/apply-template`, and `/tokenize` without inference, saving `active-chat-template.jinja`, `rendered-prompt.txt`, `native-tool-output.txt`, and `token-counts.json` under `protocol/<run-name>/`. Calls are serialized with the active template, including empty arguments and action arrays. The experiment's `encoding-counts.json` also provides reference counts across all formats.

The rendering contains an internal media placeholder; it is not a complete multimodal replay payload. Separately tokenized fragments may not sum to completion counts because channel/stop markers and boundaries contribute. Inspection uses the current server's template/tokenizer, which can differ from a historical run after an update.

## Primary references

- [Google: Gemma 4 function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4)
- [Google: model card and sampling guidance](https://ai.google.dev/gemma/docs/core/model_card_4)
- [Google: prompt formatting](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4)
- [llama.cpp server API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
