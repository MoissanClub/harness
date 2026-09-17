# Tool format experiment — hypothesis recorded before measurement

For the same model, hardware and visual input:

`latency ≈ image/transport overhead + uncached input tokens / prefill rate + output tokens / decode rate`.

This is a local approximation: prefill is batched, image encoding is a separate computation, and short decode timings contain fixed costs. Token throughput need not be perfectly constant.

## Predictions

- Six atomic, no-argument functions shorten each call but lengthen the tool declarations. They should improve warm-prompt latency more reliably than cold-prompt latency.
- Splitting movement and rotation into two parameterized tools may improve semantics, but should have little intrinsic decode advantage. It adds a declaration.
- One `plan(actions)` tool amortizes repeated call delimiters and argument keys across several actions. It may beat atomic calls for longer sequences. It may not win for a single action.
- Tool count is not the number of inference passes. Both a function-name choice and an enum choice are generated through the same model vocabulary. Names are not necessarily single tokens.
- Fewer generated tokens should affect total latency more than tokens/second. At the previous ~44 output tokens/s, saving ten output tokens is about 0.23 seconds. An extra 100 uncached prompt tokens could cost about 0.25–0.33 seconds at the previously observed prefill rates.
- A shorter protocol could still lose by confusing the model, adding redundant actions, or requiring recovery. Quality and complete plans must be measured alongside latency.

## Frozen comparison

Four equivalent action encodings: `combined`, `split`, `atomic`, `plan`. All expose the same six actions, fixed 0.25 m translation / 30 degree rotation, a maximum of four actions, and the same system/user prompts and three 720×480 images. Tools record hypothetical plans only.

Thinking is explicitly disabled. Each trial permits one complete ordered response; the host makes no acknowledgement or tool-feedback request. Sampling is temperature 1, top-k 64, top-p 0.95, min-p 0. No output-token cap is imposed. Seeds 101 onward are paired across formats; different tokenizations mean paired seeds are not identical choices.

Six repetitions per image and format. For each scene/seed block, shuffle format order using a fixed scheduler seed. Each format receives a cold request (`cache_prompt:false`) followed immediately by the same request with caching enabled. The cold response primes the warm request. Report cache counts to verify this actually happened. All requests are serial. Warm repetition of an identical frame is an optimistic cache bound, not live-camera performance.

Keep all failures. Report protocol validity, output-only compliance, qualitative task success, actions, prompt/new/cached/completion tokens, prefill/decode timing, decode throughput, and wall latency. Compare equivalent canonical plans separately so omission cannot masquerade as a latency win. Retain the existing qualitative rubric, which accepts repeated correct-side turns and does not establish metric alignment.

Use the active server template/tokenizer to measure exact input declaration costs and reference output encodings for one, two and four actions without inference. This isolates serialization cost from visual interpretation.

Limitations: three synthetic scenes, repeated samples not independent visual tasks, descriptive results rather than broad quality rankings, one Mac/model/build. The previous thinking-on evaluations changed multiple things and are not a controlled ablation of thinking alone. No inference about Orin NX throughput follows from these host measurements.
