# How this setup works

Inference is **C++ llama.cpp** (`llama-server`). It is **not** `llama-cpp-python`. Python is a stdlib HTTP client only.

```text
# 720x480 PNG  →  OpenAI-compatible JSON  →  C++ llama-server :8080
#                /v1/chat/completions
#                native tools + vision mmproj
#  one model response  →  validate tool_calls  →  mock plan  →  stop
```

## Technology applied

| Layer | What | Why it stays fast for VLM robotics |
| --- | --- | --- |
| Runtime | C++ `llama-server` (saved runs: `b10909-a2878d30d`) | Decode/prefill stay in C++/GPU. No Python GIL around kernels. |
| Model | Gemma 4 E4B QAT **Q4_0** GGUF + mmproj, alias `gemma4-e4b` | Small enough for Mac / Orin NX 16 GB. QAT keeps tool-call quality at 4-bit. |
| Context | 131,072 reported; one image + short system/user | Large ctx is available; each trial only sends the current frame + goal. |
| Vision | `modalities.vision` required via `/props`; PNG as `image_url` data-URL | 720×480 kitchen frames, not 1536×1024 sources. Fewer vision tokens. |
| API | OpenAI-compatible `/v1` + llama.cpp extras (`cache_prompt`, `/props`, `/tokenize`) | Native `tool_calls`, not text-parsed function markup. |
| Client | `run.py` stdlib `urllib` | No `openai` / `llama-cpp-python` on the hot path. |
| Control | One response, max 4 actions, no ack turn | Robotics loop cost is one prefill+decode, not a multi-turn chat. |
| Thinking | Default `brief` (`enable_thinking` + short system suffix) | Pilot: −33% reasoning tokens, −28% median latency vs `normal`. |
| Tools | Default `plan(actions)` | One native call holds the whole sequence; less schema/decode overhead than many atomic calls. |
| Cache | `cache_prompt` on llama.cpp KV | Warm reuse of the same image+prompt. `--cache off` for cold VLM timing. |
| Sampling | Eval: T=1, top-k 64, top-p 0.95, min-p 0 | `request-defaults.json` sets `min_p: 0`, `stream: false`, `parallel_tool_calls: true`. |
| Actions | Mock only (`executed: false`) | Measures VLM plan latency, not robot I/O. |

Defaults live in `runner-defaults.json` (`format=plan`, `thinking=brief`) and `request-defaults.json`.

## Request path

```python
# run.py build_payload / complete — comments match the live code
payload = {
    "chat_template_kwargs": {"enable_thinking": thinking != "off"},
    "model": "gemma4-e4b",
    "messages": [
        {"role": "system", "content": system},          # budget, 0.25 m, 30°, tool-only
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            {"type": "text", "text": goal},             # Face the fridge; one step
        ]},
    ],
    "tools": tool_schemas(format, max_actions),         # combined|split|atomic|plan
    # optional: seed, cache_prompt true/false
}
# POST {base_url}/chat/completions  then stop. No tool-result follow-up.
```

Server must already be running. The harness never starts llama.cpp and never loads the GGUF in-process.

## Run commands

Paths below match the original Mac tree. On this machine use `/home/dev/Desktop/code/harness/run.py`.

```bash
# All three scenes (center/left/right), three trials each → 9 one-shot VLM plans
# Default format=plan, thinking=brief. Fastest accurate profile from the pilot.
python3 -B /Users/junda/robot/harness/run.py --suite --repeat 3

# One off-center scene; six no-arg tools (turn_left(), move_forward(), …)
# More tool schema tokens than plan(); use for interface A/B, not latency.
python3 -B /Users/junda/robot/harness/run.py --case left --format atomic

# Explicit brief reasoning (same as default). Thinking on, short system suffix.
# Off-center scenes needed thinking in the pilot; center was faster with off.
python3 -B /Users/junda/robot/harness/run.py --case right --thinking brief

# Force a cold VLM prefill: cache_prompt=false (no prompt-KV reuse)
# Use this to time first-frame robotics observations, not warm repeats.
python3 -B /Users/junda/robot/harness/run.py --case right --format plan --cache off

# Point the stdlib client at another C++ llama-server (same /v1 contract)
python3 -B /Users/junda/robot/harness/run.py --suite --base-url http://SERVER:8080/v1
```

`--cache default` leaves KV policy to the server. `on` / `off` set `cache_prompt` explicitly. That flag is prompt-KV reuse only; it does not reload weights or flush image/kernel caches.

## Robotics-VLM latency notes

```bash
# Keep the C++ server hot. Do not restart llama-server between trials.
# Same process = weights + mmproj stay in GPU/CPU RAM.

# Live camera / first look:  --cache off
# Same scene, same prompt:   --cache on     # optimistic bound, not a new frame

# Prefer --format plan and --thinking brief for the control loop.
# --thinking off is faster (~1.1 s median) but failed most off-center cases.
# --thinking normal is slower (~8.4 s) with no extra success vs brief (~6.1 s).

# Do not add a second chat turn. The runner records mocks and exits.
```

Mac brief+plan median was about 6.7 s in the format study; that does **not** establish Orin NX rate. Retokenized reasoning was ~94% of completion tokens, so thinking length dominates decode time.
