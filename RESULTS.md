# First local evaluation

Historical single-action baseline. The current harness supports short action sequences; see [TURN_RESULTS.md](TURN_RESULTS.md). Original prompts and settings remain in the request files below.

Executed against the user's running API on 2026-09-17 UTC (2026-09-16 Pacific).

## Observed configuration

- llama.cpp build: `b10909-a2878d30d`.
- Model: Google's `gemma-4-E4B_q4_0-it.gguf`, repository revision `4b4a2c1d584be7264f87aac328a1bc739ce81b6c`.
- Server reports vision support and 131,072 context tokens.
- Server defaults: temperature 1.0, top-k 64, top-p approximately 0.95, min-p approximately 0.05.
- Harness overrides: thinking enabled, min-p 0, tool choice auto, parallel tool calls disabled. No explicit output-token cap.
- Input: `assets/kitchen-720x480.png`, verified 720×480 PNG. The model receives the image and question, not the image-generation prompt.

## Results

| Run | Native tool call | Decision wall time | Feedback |
| --- | --- | ---: | --- |
| `runs/20260917T003715.158898Z` | `move({"direction":"forward"})` | 3.205 s | Returned another action as raw tool markup in text, despite `tool_choice: none`. |
| `runs/20260917T003754.876834Z` | `move({"direction":"forward"})` | 4.090 s | Returned `The movement "forward" was recorded.` and stopped. |

The first system prompt specified a single next movement but did not clearly state that receiving the mock result ends the test. The revised prompt explicitly said this was a single-decision test and asked for an acknowledgement after the tool result. Full original prompts are retained in each run's request files. No direction hint was added.

The second run used 454 prompt tokens and generated 111 completion tokens for its decision, finishing with `tool_calls`. Its acknowledgement took another 1.258 s and finished with `stop`. These are individual observations, not latency benchmarks; the two runs had different prompts, stochastic generation, and different cache behavior.

Both decisions contained exactly one native API tool call with valid JSON arguments. Host validation dispatched the mock, which returned `executed: false`. No hardware action occurred. In the second run the acknowledgement did not falsely claim movement, though it omitted the requested explicit statement that execution had not occurred.

The first run predates the added `feedback_protocol_ok` summary check, so its `summary.json` only records the valid initial call and raw feedback. The feedback failure is preserved in `feedback-response.json` and this report. The sequence harness uses `protocol_ok` and also rejects raw tool markup masquerading as a final reply.

## Scope of the result

This is a successful basic image-input/native-tool-call integration check and a plausible action selection. It is not proof of obstacle avoidance, metric motion planning, reliable navigation, or causal use of the image. “Forward” is also a plausible text-only prior for this question. The next useful evaluation is a controlled scene change and an absent-fridge/abstention case.

Host syntax checks and rejection checks passed for an unknown function, an invalid direction, and an extra argument.
