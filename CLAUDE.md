# Robot autonomy harness

Goal: a Unitree G1 autonomously **fetches a drink from the fridge** (walk there, hold the door with one hand, take a can with the other, close the door, return, hand over). A small VLM does perception and decisions and drives robot skills through tool calls. Target: Jetson Orin NX 16 GB on the G1. Dev/eval: this MacBook Pro (M4 Pro, 24 GB). Everything here is mocked; no hardware.

## Layout

- `run_llama.sh` — llama.cpp server, Gemma 4 E2B QAT + mmproj, `127.0.0.1:8080`, alias `gemma4-e2b`. Flags are measured choices; see its comments.
- `bench/` — latency/accuracy benchmark. Findings: **`LATENCY_RESULTS.md`**.
  - `make_dataset.py` → 78 labeled fridge views + 14 fridge-free views. Needs macOS `sips`; `bench/images*/` is git-ignored, so regenerate on the Mac or copy the folders to Linux.
  - `variants.py` — every prompt / tool / grammar / image-size variant. `run_bench.py` — serial sweep → `experiments/<ts>-latency-<tag>/{requests.jsonl,summary.json}`. `report.py` — Markdown tables.
  - `serve.sh TAG [flags]` — restart the port-8080 server (its launch line is saved into each run's manifest). `flag_sweep.sh`, `batching.py`, `text_mapping_probe.py`, `vit_split.py` — server-flag A/B, N-actions-per-call cost, text-only percept→plan control, vision-encoder split from a `-lv 4` log.
- `run.py`, `tools.py`, `prompts/`, `evaluate_*.py`, `check.py` — codex's original one-response harness (3 images, `plan` tool). `python3 -B check.py` = offline checks.
- `*_RESULTS.md` (other than latency), `DEPLOY.md`, `TASK_CHUNK_PROPOSAL.md`, `AGENTS.md`, `README.md` — codex's notes: suggestions, verify before relying on them.

```bash
bench/serve.sh dev -np 1 --cache-ram 0 -c 4096 --swa-full
python3 -B bench/run_bench.py --list
python3 -B bench/run_bench.py --tag dev --variants "face-tool-480x336,where-free-off-480x336,box-prefill-480x336"
```

## What we know (Mac, 78 images; numbers in `LATENCY_RESULTS.md`)

- Sub-second is met with thinking **off** and greedy decoding: one-word answer 99% at 222 ms; `face_target(position)` tool call 97% at 324 ms; box detection 100% at 378 ms (most robust: unaffected by temperature, no left/right flips). Brief thinking + `plan` tool was 63% at 2.1–2.6 s.
- E2B without thinking perceives well but cannot compose percept → plan: every "plan the actions" variant collapses to `[forward]`, and reasoning budgets under 1 s do not help. Ask a **direct perception question placed after the image**, let the answer/tool argument carry the percept, do geometry and sequencing in code.
- Levers: thinking off (−2 s) → 480×336 frame (70 image tokens, llama.cpp's floor; −135 ms) → cached system prefix (−25 to −150 ms, grows with system + tool text) → few output tokens (~9 ms each) → `--swa-full -c 4096` (−35 to −55 ms). Prompt processing is ~90% of a short request. MTP drafting is a net loss on this Mac.
- Gotchas: a perception question in the system turn or before the image loses accuracy (box detection excepted); temperature 1.0 costs 6–8 points on word/number/tool answers; `face_target` sometimes answers `left` for a fridge on the right; the chat template sorts tool arguments alphabetically; the server rejects `grammar` with `tools`; the native tool grammar does not enforce enums/ranges (validate client-side); with no fridge in view the model hallucinates a position, and both mitigations (4-way answer, yes/no gate) are partial.
- Orin NX is unmeasured. Public reports suggest ~27 ms per output token there, which would make tool-call syntax cost ~0.35 s. Re-test MTP, `-fa`, and clocks on target.

## Rules for working here

- Python 3.9+ **stdlib only**; match the terse existing style. `runner-defaults.json`, `request-defaults.json`, `evaluation-sampling.json` stay the source of truth for the original harness.
- Benchmarks are serial and GPU-exclusive: never run two inference jobs at once. Restart the server only via `bench/serve.sh` (it stops just the port-8080 process; the Llama.app router on another port is the user's).
- Never time repeated identical images — the server reuses the image KV and reports fantasy latencies. `run_bench.py` rotates images and flags `image_cache_hit`; bench with `-np 1 --cache-ram 0`.
- Report accuracy with n and per-class counts; when sampling with temperature, seed every request differently (llama.cpp re-seeds per request). The 3 source kitchens are generated images, so results are a diagnostic, not navigation capability. Mac numbers are not Orin numbers.
- Do not download models or other files without asking. Keep experiment artifacts; `runs/` is git-ignored.
