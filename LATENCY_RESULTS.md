# Sub-second perception → action on Gemma 4 E2B

Measured 2026-09-21 on the MacBook Pro (M4 Pro, 24 GB), llama.cpp `b10909-a2878d30d`, `unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL` + `mmproj-BF16`. **All latencies are Mac measurements; the Orin NX section is a projection, not a measurement.** Task: "face the fridge and take one step toward it" from one camera image. The numbers, benchmark code and both docs were re-checked by an independent verification pass; its corrections are folded in.

## Result

| Approach (thinking off unless noted; greedy; PNG frames) | Strict accuracy, 78 images | Total p50 / max |
| --- | ---: | ---: |
| codex's setup: brief thinking + `plan` tool ¹ | 49/78 (63%) | 2564 / 5888 ms |
| Thinking off + `plan` tool, codex prompt | 18/78 (23%) — always `[forward]` | 445 / 450 ms |
| One-word answer (`left`/`center`/`right`), no tool call | 77/78 (99%) | 222 / 234 ms |
| Native tool call with a percept argument: `face_target(position)` | 76/78 (97%) | 324 / 332 ms |
| Box detection with assistant prefill (continuous bearing, x error 1.7% of width) | 78/78 (100%) | 378 / 389 ms |

The last four rows use the new `run_llama.sh` flags; the last three also use a 480×336 frame. As JPEG the same three score 78/78 at 217 ms, 77/78 at 319 ms and 78/78 at 374 ms.

¹ Measured here with greedy sampling and a warm prefix on the MTP server. On the new flags the same request has a 2145 ms p50 (n=24), so at equal server flags the fast paths are **6–10× faster**, and more accurate. `run.py`'s own defaults (brief thinking, `plan` tool, server-default sampling) are unchanged.

**Sub-second holds with a wide margin on the Mac.** Which format to use:

- **Box detection is the most robust**: 100% greedy, still 156/156 at temperature 1.0, no left/right flips, and it yields a bearing instead of a bucket. With the prefill it cannot say "no fridge".
- **One word is the fastest** and misses only at a label boundary.
- **`face_target` is the native-tool-call option.** Its misses are one-directional: it answers `left` for a fridge on the right, including far from any boundary (`f` = 0.69 and 0.92 greedy; five more at temperature 1.0). Never the reverse.

**Why it works.** E2B perceives well without thinking but cannot compose percept → multi-step plan without it. A trace-mining pass over codex's saved E2B thinking runs found the correct fridge side named in 17/18 trials, yet 8 wrong plans, with about one sentence of each ~340-token trace carrying information (token offsets estimated). So: ask a direct perception question right after the image, let the answer or tool argument carry the percept, and do the geometry (`left → turn_left, forward`) in code or inside the robot-side skill.

## Method

- **Images:** `bench/make_dataset.py` cuts sliding 3:2 crops at two zoom levels from the three 1536×1024 source kitchens, plus mirrored copies: 78 images at 720×480 (30 left / 18 center / 30 right, mirror-balanced). Labels come from the fridge centre's horizontal fraction `f`, measured once per source, never from model output: `f ≤ 0.33` expects `turn_left`, `0.43–0.57` no turn, `f ≥ 0.67` `turn_right`; the gaps are not generated because a 30° turn quantum makes them ambiguous. 14 fridge-free crops test the target-absent case.
- **Grading:** strict = exactly `[forward]` or `[correct_turn, forward]`. Perception-only variants never output actions; a fixed policy in `bench/variants.py` maps their percept to actions (thresholds 0.38 / 0.62, the midpoints of the label gaps). That is the point of the design, but it means the "plan" rows test percept + composition while the perception rows test percept only.
- **Latency:** client wall clock from sending the request to the last streamed byte (`bench/client.py`). It includes HTTP, server-side base64/image decode, vision encoder, prefill and decode. It excludes camera capture and the client-side resize/encode (precomputed with `sips`).
- **Cache realism:** requests are strictly serial, `cache_prompt: true`, and consecutive requests always carry different images, so only the static text prefix can be reused — as with a live camera. Rows where the server reused an image KV are flagged and excluded from latency (it happened only on the 4-slot default server). Headline numbers assume one client that owns the single slot and repeats the same request type, so its prefix stays warm; alternating request types with different system text would pay part of the cold cost below.
- **Sampling:** greedy (`temperature 0, top_k 1`) unless stated. Each variant gets one untimed warm-up request.
- **Intervals:** `summary.json` carries 95% Wilson intervals (97% at n=78 → 91–99%; 23% → 15–34%). They assume independent samples. These are overlapping crops and mirrors of 3 scenes, so the real uncertainty is wider; read the intervals as a floor.
- Server launch lines are saved per run (`manifest.json: server_launch` for new runs, `server-launch.txt` backfilled for the 2026-09-21 runs).

## Where the time goes

From a verbose-log pass (`-lv 4`) with the final flags; the log excerpt is saved in `experiments/*-latency-verbose-decomp/server-log-excerpt.txt` and parsed by `bench/vit_split.py`:

| Frame | Vision encoder | LLM prefill side | Fresh tokens | `prompt_ms` |
| --- | ---: | ---: | ---: | ---: |
| 720×480 → 150 image tokens (1350 patches) | 135 ms | 194 ms | 186 | 329 ms |
| 480×336 → 70 image tokens (630 patches) | 58 ms | 145 ms | 106 | 202 ms |

- LLM prefill ≈ **80 ms fixed + 0.6 ms per fresh token**. The fixed part is several small `llama_decode` calls plus sampling the first output token, which is therefore "free".
- Decode ≈ **8.9 ms per step plain** (113 tok/s over 5.5k thinking tokens). With MTP `n-max 2` it is 95 tok/s: one draft round costs ~24 ms for ~2.1–2.4 tokens.
- Everything outside `prompt_ms + predicted_ms` (HTTP, base64, image decode, template, tokenization): 3–11 ms at 480×336, 15–22 ms for a 720×480 PNG.
- The 222 ms one-word request ≈ 58 (encoder) + 145 (prefill) + 10 (decode) + 8 (other). **Prompt processing is ~90% of it**, and about half of the request is image-specific (encoder plus the 70 image tokens). Output format only matters once outputs exceed a few tokens.

Thinking cannot fit: brief thinking produced a median of 204 output tokens (mean 225, range 126–526), about 1.8 s of decode alone.

## Options explored

| Option | Effect | Verdict |
| --- | --- | --- |
| Thinking off | −2 s (2564 → 505 ms on the same server) | The largest lever and required, but with a "plan the actions" prompt accuracy falls to 23% (always `[forward]`) |
| Reasoning budget 16 / 32 / 64 / 128 tokens | 739 / 908 / 1221 / 1895 ms; 23 / 23 / 24 / 49% | Dead end: any budget that fits under 1 s gives nothing over thinking off |
| Better plan prompt with thinking on (`act-target-brief`) | 90%, 3531 ms p50, 11.2 s max | Accurate but 10× too slow |
| Percept field before actions inside the tool call (`look`, `move`) | Percept often right (50–55/78), action still `[forward]` 78/78 | Fails. The chat template sorts schema properties and the model emits arguments in that **alphabetical** order, so `target` lands after `actions`; naming them `look`/`move` fixes the order but not the behaviour |
| One action per frame (`move(direction)`, no-arg tools, grammar word) | 23% / 23% / 44% | Fails |
| Two requests on one KV: perceive, then `plan` tool given the percept | KV reuse works (2nd turn +250 ms, 363 tokens cached); plan still wrong, 22% | Fails with the image in context, although the same mapping is 3/3 text-only with a rule in the system prompt (`experiments/*-text-mapping`) |
| JSON schema / DSL grammar with action rules in the system prompt | 23–53% | Fails; long rule text also degrades the percept |
| **Direct perception question after the image** (`where`, `x` %, `box_2d`, `face_target`) | **97–100%** | **Works** |
| Question moved to the system turn (for caching) | one word 99 → 32%, `x` 97 → 32% | Fails |
| Question text before the image | one word 99 → 85%, `x` 97 → 69%, `approach(x)` tool 70 → 33%; box detection unchanged at 100%; no latency gain | Keep the question **after** the image. Only the system text is cacheable |
| Prefix caching (`cache_prompt`, changing images) | final flags, cold → warm: codex `plan` request 596 → 445 ms; `face_target` 410 → 324 ms; one word 246 → 222 ms (`best-cold` vs `best-final`) | Keep; the gain scales with the static system + tool text. codex's earlier numbers were all cold |
| Smaller frame: 720×480 → 480×336 (150 → 70 image tokens) | −131 to −139 ms total, accuracy unchanged | **Largest lever after thinking off.** llama.cpp keeps native size in 48-px cells, so the client sets the token count; 70 is the floor, smaller frames are upscaled by the server (480×320, 360×240 gave no gain) |
| 384×240 with `--image-min-tokens 40` | further −40 ms; 38–40/40 correct | Optional; below Google's trained 70-token minimum, n=40 only |
| Output format | one word 2 tok; `x` % 3; no-arg tool 7–9; tool + arg 13–15; box 42 → 17 with assistant prefill + `stop: "]"` | ≈ 9 ms per token on the Mac. `response_format` adds a JSON fence; the server rejects `grammar` together with `tools` |
| Tool call vs none | +100 ms (324 vs 222 ms); 97% vs 99%, plus the one-directional flips above | Affordable on the Mac; see Orin note |
| JPEG q85 instead of PNG | −4 to −5 ms | Minor; do it on the robot for transport |
| Temperature 1.0 instead of greedy (2 passes, independent seed per request, n=156, `final-sampling`) | box 100%; one word 99 → 93%; `x` 97 → 91%; `face_target` 97 → 89% | **Use greedy for control.** Box detection is immune |
| E4B (Google QAT Q4_0 GGUF) instead of E2B (unsloth UD-Q4_K_XL), one pass | 1.6–1.7× slower; one word 88%, `face_target` 94%, box 100%, plan tool 51% | Dropped. Confounded (different publisher/quant, prompts tuned on E2B; its misses are boundary calls), but it cannot be faster and does not fix thinking-off planning |

### Server flags (n=40 images per cell, total p50 ms)

| Flags | `plan` tool 720×480 | `face_target` | one word | box prefill |
| --- | ---: | ---: | ---: | ---: |
| Previous `run_llama.sh` (4 slots, MTP n-max 2) | 506 | 371 | 286 | 476 |
| `-np 1 --cache-ram 0`, MTP 2 | 506 | 369 | 288 | 467 |
| … no MTP | 498 | 372 | 251 | 415 |
| … MTP n-max 1 / 3 / 4 | 499 / 515 / 514 | 376 / 374 / 373 | 278 / 293 / 295 | 450 / 484 / 522 |
| … MTP 2, `-c 4096` | 509 | 370 | 290 | 468 |
| … MTP 2, `-c 4096 --swa-full` | 452 | 313 | 253 | 418 |
| … MTP 2, `-c 4096 --ctx-checkpoints 0` | 631 | 416 | 294 | 449 |
| … MTP 2, `-c 4096 --prio 2 --poll 100` | 512 | 373 | 293 | 471 |
| **`-np 1 --cache-ram 0 -c 4096 --swa-full`, no MTP (adopted, n=78)** | 445 | 324 | 222 | 378 |

- **`--swa-full` with a small context: −35 ms (one word) to −56 ms (tool calls) per request.** It removes the sliding-window checkpoint save/restore and an extra batch break. `--ctx-checkpoints 0` alone does the opposite: the prefix cache is lost.
- **MTP does not pay on this Mac overall.** Raw decode is 15% slower with it (95 vs 113 tok/s on long output) and it costs 30–50 ms on one-word and box requests. The exception is tool-call boilerplate: `face_target` is ~10 ms faster with MTP 2 (313 vs 324 ms). Per-request speculative overrides are compiled out in this build, so this is a restart-time choice.
- `-np 1 --cache-ram 0` does not change latency but makes prefix reuse deterministic and stops identical-image cache hits from faking results (three such rows appeared in the 4-slot run).
- `-c 4096` alone, `--prio`, `--poll`: no effect.

### Batching actions in one call (dictated plan, text-only, no MTP; `experiments/*-batching/table.json`)

| Format | 1 action | 2 | 4 | 8 |
| --- | ---: | ---: | ---: | ---: |
| `plan(actions=[…])` tokens / total ms | 15 / 138 | 19 / 169 | 29 / 256 | 45 / 395 |
| No-arg tool per action, tokens / total ms | 9 / 82 | 17 / 151 | 33 / 290 | 65 / 576 |

A single action is cheapest as a no-arg tool; batches are cheapest as one array (+4–5 tokens ≈ 37 ms per extra action, 50 ms/action at 8). These prompts are identical and cached, so the totals are serialization cost with near-zero prefill. With streaming the tool-call deltas start early — for `face_target` the first delta arrives at 253 of 324 ms — so a client can begin acting before the call closes. Thinking-off E2B does not produce correct multi-action plans from an image, so in the fast path batching happens robot-side: one `face_target(left)` call expands to `turn_left, forward`.

## Recommended request

This is the measured `face-tool-480x336` payload (`bench/variants.py`); only the image data is elided.

```json
{
  "model": "gemma4-e2b", "temperature": 0, "top_k": 1, "cache_prompt": true, "max_tokens": 32,
  "chat_template_kwargs": {"enable_thinking": false},
  "tool_choice": "auto", "parallel_tool_calls": true,
  "messages": [
    {"role": "system", "content": "You are a robot's vision module. Image left/right are robot left/right."},
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<480x336 frame>"}},
      {"type": "text", "text": "Is the fridge in the left third, center third, or right third of the image? Call face_target with that position."}]}],
  "tools": [{"type": "function", "function": {
    "name": "face_target", "description": "Turn to face the target, then take one step toward it.",
    "parameters": {"type": "object", "additionalProperties": false, "required": ["position"], "properties": {
      "position": {"type": "string", "enum": ["left", "center", "right"],
                   "description": "Third of the image containing the target."}}}}}]
}
```

`max_tokens` is a suggested guard; the benchmark ran without it (responses are 15 tokens).

- Send frames at exactly **480×336** (multiples of 48 inside the 70-token floor skip the server's CPU resize and letterboxing).
- Validate the argument client-side: the native tool grammar does not enforce enums or ranges (`target_x: 300` was returned for a 0–100 field).
- For a bearing, or when a wrong-direction turn is costly, use `box-prefill-480x336` (378 ms); for the lowest latency drop the tool and read one word (222 ms). A numeric `x` inside a tool argument is coarse (10/25/50/85); the plain-text `x` question is better (4% error). A box inside a tool argument is untested.
- Send one production-size dummy request at startup. The first image request after a server start was ~2× slower in a server log from this session (934 vs ~520 ms; that log is not saved in the repo).

## Known weaknesses

- **Absent target.** With no fridge in view the fast variants hallucinate a position: "none" was chosen for 6/14 (one word, 4-way), 0/14 (`face_target` with a `none` enum), 1/14 (unprefilled box). Two mitigations, both imperfect (`final-absent`, 92 images):
  - One request, 4-way answer: present 77/78, absent 6/14 → 83/92 at 221 ms.
  - Yes/no gate first, then "where" as a second turn on the same KV (+83 ms, image not re-processed): gate alone is 78/78 yes, 12/14 no; but the follow-up "where" is worse than the single-turn question — present 73/78 (all five misses answered `center`, two of them away from a boundary), absent 12/14 → 85/92 at 281 ms. Untested: gate, then a fresh single-turn "where".
  - The two gate false positives are wide views with a stainless dishwasher.
- **Left/right flips in `face_target`** (above). The one-word misses sit at a label boundary (`f` = 0.31); box detection had none.
- Three generated kitchens, cropped and mirrored: this measures these scenes, not visual generalization or navigation. The 14 absent images are a small diagnostic. Prompts were chosen on these same images.
- Sequencing (which skill next) is untested here. Thinking-off E2B failed every composition test above, so keep sequencing in code or in a slower planner off the critical path, and keep per-frame calls to grounded perception.
- Dataset generation and resizing shell out to macOS `sips`, and `bench/images*/` is git-ignored: on Linux/Jetson copy the image folders over or port the resize step.

## Orin NX 16 GB projection (not measured)

Inputs were collected by a web research pass during this work and not re-verified: the little-gemma project's Orin NX benchmarks report this exact GGUF under llama.cpp at ~38 tok/s plain decode (≈27 ms/token, consistent with 102 vs 273 GB/s memory bandwidth) and ~1000 tok/s prefill, roughly at parity with this Mac; NVIDIA's Gemma 4 Jetson recipe pins images to 70 tokens. The llama.cpp vision encoder on Orin is unmeasured (0.7–2.5× the Mac assumed).

| Request | Mac | Orin NX estimate |
| --- | ---: | ---: |
| One word, 480×336 | 222 ms | ≈ 0.25–0.45 s |
| `face_target` tool call, 480×336 (15 output tokens) | 324 ms | ≈ 0.6–0.85 s |
| Box prefill, 480×336 (17 output tokens) | 378 ms | ≈ 0.65–0.9 s |
| Brief thinking, ~200 output tokens | 2.1–2.6 s | ≈ 6–8 s |

If output tokens cost ~27 ms there, the ~13-token tool-call wrapper costs ≈ 0.35 s: sub-second with a tool call is plausible but tight, and the one-word format is the safe choice. Re-test on target: MTP (decode is bandwidth-bound there; reports say 1.3–1.5×), `-fa on` together with MTP (past crash reports on SM87), an F16 mmproj, `jetson_clocks` / MAXN_SUPER, and the 70-token image.

## Reproduce

```bash
python3 -B bench/make_dataset.py                                   # macOS only (sips)
bench/serve.sh best -np 1 --cache-ram 0 -c 4096 --swa-full          # the adopted flags
python3 -B bench/run_bench.py --tag best-final --variants "codex-off,face-tool-480x336*,where-free-off-480x336,where-grammar-off-480x336*,box-prefill-480x336*"
python3 -B bench/run_bench.py --tag final-sampling --sampling eval --passes 2 --variants "face-tool-480x336,where-free-off-480x336,x-grammar-off-480x336,box-prefill-480x336"
python3 -B bench/run_bench.py --tag final-absent --dataset both --variants "present-only-480x336,gate-where-480x336,where4-grammar-480x336"
python3 -B bench/batching.py && python3 -B bench/text_mapping_probe.py
bench/flag_sweep.sh 40        # restarts the server 11 times and leaves it on the last test config
python3 -B bench/report.py experiments/*-latency-best-final
```

Evidence under `experiments/20260921T*-latency-<tag>/` (each holds `requests.jsonl`, `summary.json`, `manifest.json`, `server-props.json`, server launch line): `mtp2-np1-fast`, `mtp2-np1-input`, `mtp2-np1-round2` (prompt, format, ordering and image-size variants), `mtp2-np1-thinking` (thinking and budgets), `flags-*` (server flags), `best-final`, `best-cold`, `final-sampling`, `final-absent`, `verbose-decomp`, `best-nomtp-thinking`, `e4b-best`. Superseded: `best-sampling` (one seed shared by every request in a pass), `best-absent` / `best-gate` (presence-only rows mis-graded; re-run as `final-absent`). The `smoke*` directories are 6-image shakedown runs.
