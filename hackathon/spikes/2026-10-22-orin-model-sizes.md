# Thursday Oct 22: Gemma 4 E2B vs E4B vs 12B on the G1's Orin NX (PC2)

Question from the owner: is E4B or 12B worth it on the robot, and is 12B fast enough to write code for a task it has never seen and then run that code? Nothing moved the robot; this is inference only.

**Result.** Perception stays on E2B: the bigger models are no more accurate on the fridge views and are 1.4-1.8x (E4B) and 2.3-3.3x (12B) slower. Writing code is where size matters, and the jump is E2B to E4B: E2B gets 2/9 one-step tasks right, E4B 8/9 at a 4.2 s median, and 12B also 8/9 at 12.2 s. On six harder tasks 12B got 3/6 at 16.6 s; E4B has not run them yet, and that comparison decides whether 12B earns its 3x cost.

## Setup
- PC2 at MAXN (8 cores), booted about 10 minutes before the first run. **`jetson_clocks` not applied** (it needs sudo, which is not passwordless): GPU governor `nvhost_podgov`, 306-918 MHz, tegrastats showed GR3D at 88-99% during requests. E2B re-measured in this state is 8-15% slower than Sunday's pinned MAXN run (368 / 760 / 839 ms vs 320 / 686 / 772 ms, same accuracy). So compare models within this table; pinned clocks should take roughly 10-15% off every number.
- llama.cpp `b10909-a2878d30d`, CUDA sm_87, the demo server flags: `-ngl 99 --jinja -np 1 -c 4096 --swa-full --cache-ram 0`. Launched by `scripts/serve-orin-model.sh e2b|e4b|12b` (copied to `~/spike/` on PC2; `serve-orin.sh` stays the E2B demo launcher). Each run's launch line is in its `manifest.json`.
- Model files, all in `~/models/gemma4` on PC2 (fetched with `scripts/fetch-e4b-12b.sh`, about 20 MB/s from Hugging Face):

| Size | Weights | Projector (vision + audio) | Source |
| --- | --- | --- | --- |
| E2B | `gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf` 2.62 GB | `mmproj-BF16.gguf` 0.99 GB | unsloth QAT, copied from the Mac Oct 18 |
| E4B | `gemma-4-E4B_q4_0-it.gguf` 5.15 GB | `gemma-4-E4B-it-mmproj.gguf` 0.99 GB | `google/gemma-4-E4B-it-qat-q4_0-gguf`, fetched today |
| 12B | `gemma-4-12b-it-qat-q4_0.gguf` 6.98 GB | `mmproj-gemma-4-12b-it-qat-q4_0.gguf` 0.18 GB | `google/gemma-4-12B-it-qat-q4_0-gguf`, fetched today |
| 12B draft head | `mtp-gemma-4-12B-it.gguf` 0.25 GB | | `unsloth/gemma-4-12B-it-qat-GGUF`, fetched, not yet measured |

  Confound: E2B is unsloth's UD-Q4_K_XL, E4B and 12B are Google's QAT q4_0 (as in the Mac E4B run of Sept 21), and every prompt was tuned on E2B. The 12B projector loads audio input (the server warns it is "experimental"); audio was not tested on E4B or 12B.

## Perception (the demo's three request types)
`bench/run_bench.py`, 78 labeled fridge views at 480x336, greedy, thinking off, serial, no image-cache hits.

| Request | Model | Strict accuracy (L / C / R) | Total p50 / p90 / max | Prompt | Output |
| --- | --- | --- | ---: | ---: | ---: |
| One word (`where-free-off`) | E2B | 77/78 (29/30, 18/18, 30/30) | 368 / 371 / 372 ms | 276 ms | 2 tok, 35 ms |
| | E4B | 69/78 (25/30, 18/18, 26/30) | 532 / 535 / 537 ms | 409 ms | 2 tok, 68 ms |
| | 12B | 75/78 (27/30, 18/18, 30/30) | 829 / 830 / 832 ms | 688 ms | 2 tok, 119 ms |
| Tool call (`face-tool`) | E2B | 76/78 (30/30, 18/18, 28/30) | 760 / 764 / 769 ms | 272 ms | 15 tok, 422 ms |
| | E4B | 73/78 (26/30, 18/18, 29/30) | 1322 / 1328 / 1340 ms | 403 ms | 15 tok, 854 ms |
| | 12B | 76/78 (28/30, 18/18, 30/30) | 2305 / 2413 / 2419 ms | 686 ms | 15 tok, 1591 ms |
| Box (`box-prefill`) | E2B | 78/78, x error 0.017 | 839 / 848 / 909 ms | 309 ms | 17 tok, 476 ms |
| | E4B | 78/78, x error 0.015 | 1499 / 1508 / 1563 ms | 471 ms | 17 tok, 973 ms |
| | 12B | 78/78, x error 0.005 | 2778 / 2866 / 2904 ms | 882 ms | 17 tok, 1846 ms |

- Decode per output token: E2B 28 ms, E4B 57 ms, 12B 109 ms. Prompt for about 77 fresh tokens plus the image: 276 / 409 / 688 ms.
- Peak board RAM during the runs (tegrastats, 15.6 GB total, about 0.86 GB idle): E2B 5.8 GB, E4B 8.6 GB, 12B 11.4 GB. 12B leaves about 4 GB, so it cannot sit next to the E2B server (about 4.9 GB). E2B plus E4B (about 4.9 + 7.8 GB) would be tight and was not tried. GPU peaked at 71 C on 12B.
- Every miss of E4B and 12B is a "center" answer for a fridge at f = 0.29-0.32 or 0.68-0.73, i.e. within 0.06 of a label boundary; none is a left/right flip. E2B's two tool-call misses are at f = 0.69 (`left` and `center`), the known one-directional flip. 12B's only gain is box precision (x error 0.005 of the width vs 0.017), which the grasp does not need.
- Only the 12B one-word gate is under one second; its tool call and box are 2.3-2.8 s.

## Writing code for an unseen task (`bench/codegen_probe.py`, new)
The model gets a small robot API in the system prompt (`look()` returning cans with id, colour, label, x left-positive and y in cm; `pick(id)`, `give()`, `place("tray"|"table")`, `say(text)`, `listen()`, `wave()`), then one task in plain words, and must reply with `def task(robot):`. The program runs against a mock robot on two or three different table layouts (2-5 cans; different guest replies; cans that slip). A task **passes** only if every layout ends in the right state with no refused call or exception; **lenient** also accepts refused calls that did no harm (for example `place` after `give` with an empty hand). Greedy, thinking off, one sample per task, `max_tokens` 600, the system prefix warmed once so only the task text is fresh (14-50 prompt tokens). The model's code runs on the Mac (`python3 -I` in a temp dir, 5 s timeout, code that names `os`/`subprocess`/`open(` etc. is refused) and reaches the PC2 server through `ssh -N -L 18080:127.0.0.1:8080 g1`; it never runs on PC2. Every task's checker was validated offline: a reference solution passes all layouts and a plausible wrong one fails at least one. All 42 saved programs re-grade identically under the committed checker.

Basic set (9 one-step tasks). Cell: result, layouts passed, output tokens, server time (prompt + decode).

| Task | E2B | E4B | 12B |
| --- | --- | --- | --- |
| not-red: give every non-red can | lenient 0/3, 138 tok, 4.1 s | pass, 64 tok, 4.0 s | pass, 106 tok, 12.2 s |
| count: say how many cans | pass, 45 tok, 1.4 s | pass, 34 tok, 2.1 s | pass, 39 tok, 4.5 s |
| leftmost: give the leftmost can | fail 0/3, 164 tok, 4.8 s | pass, 60 tok, 3.7 s | pass, 75 tok, 8.6 s |
| greens-tray-wave: greens to tray, then wave | pass, 112 tok, 3.3 s | pass, 61 tok, 3.7 s | pass, 61 tok, 7.1 s |
| ask-colour: ask, give that colour or say sorry | fail 2/3, 178 tok, 5.3 s | fail 2/3, 114 tok, 6.9 s | fail 2/3, 132 tok, 15.2 s |
| right-to-left: all to tray, rightmost first | fail 0/3, 139 tok, 4.1 s | pass, 69 tok, 4.2 s | pass, 65 tok, 7.6 s |
| majority: more red than blue? give red, else blue | lenient 0/3, 251 tok, 7.4 s | pass, 219 tok, 13.3 s | pass, 126 tok, 14.5 s |
| two-colours: give two cans of different colours | lenient 0/3, 199 tok, 5.8 s | pass, 187 tok, 11.3 s | pass, 126 tok, 14.4 s |
| closest-label: closest Sprite, or say none | fail 1/3, 158 tok, 4.7 s | pass, 119 tok, 7.2 s | pass, 148 tok, 17.0 s |
| **Passed (lenient)** | **2/9 (5/9)** | **8/9 (8/9)** | **8/9 (8/9)** |
| Server time p50 / max | 4.7 / 7.4 s | 4.2 / 13.3 s | 12.2 / 17.0 s |
| Output tokens p50, ms per token | 158, 29 ms | 69, 60 ms | 106, 113 ms |

Hard set (6 tasks), 12B only so far: 3/6 (lenient 3/6), server time p50 16.6 s, max 27.7 s, 145 output tokens median.

| Task | 12B |
| --- | --- |
| middle: give the middle can left to right, or say there is none (even count) | fail 2/3, 95 tok, 11.0 s: takes the middle of `look()`'s order without sorting by x (right by luck on one layout) |
| retry-slip: give the leftmost, at most three picks, else sorry | pass, 97 tok, 11.3 s |
| right-of-pepsi: give the nearest can to the Pepsi's right, or say none | pass, 188 tok, 21.6 s |
| how-many: ask how many, give that many closest first, say if that's all | fail 0/3, 164 tok, 18.9 s: `int("Two, please.")` raises, so it gives nothing |
| common-first: all to tray, the most common colour first | pass, 241 tok, 27.6 s |
| one-per-colour: keep one can per colour, the rest to the tray | fail 0/3, 125 tok, 14.4 s: invents `robot.place(x, y)` for the kept cans |

What goes wrong:
- **E2B** writes plausible Python with wrong semantics: `place("tray")` right after `give()`, "furthest to the right" sorted the wrong way (x is positive to the left), `cans[can_id]` as if ids were list positions. Its programs are also the longest (158 tokens median), so on the Orin it is no faster than E4B.
- **E4B and 12B fail `ask-colour` the same way**: both compare the guest's whole reply with the colour name, so "Blue, please." matches nothing; both pass the layout where the guest says just "green".
- **12B's hard-set misses are about the guest's words and unstated assumptions, not Python**: number words, list order, an API call that does not exist. Suggestion, untested: keep speech-to-value in a separate short Gemma call (as the brain already does for the colour) and give the code-writer parsed values, e.g. a `listen_number()` skill.
- Latency is output tokens times the per-token cost: a 100-token program is about 3 s on E2B, 6 s on E4B and 11 s on 12B before prompt time (unpinned clocks).

## Not done
- E4B on the hard set (one run, about 1.5 min of GPU): the comparison that decides whether 12B adds anything over E4B. E2B on the hard set.
- 12B with the MTP draft head: the server loaded with `--spec-type draft-mtp -md ~/models/gemma4/mtp-gemma-4-12B-it.gguf --spec-draft-n-max 3`, but the run was stopped before any request. Decode is 90%+ of a 12B program, so this is its main lever.
- Pinned clocks, thinking on for code writing, audio on E4B and 12B, the brain's other processes running alongside a larger model.
- Caveats: 15 tasks written for this probe on a mock robot, one greedy sample each, so the pass counts are small-n and say nothing about real grasping; the perception set is 78 crops of 3 generated kitchens (a diagnostic, as before).

## Reproduce
```bash
ssh g1 '~/spike/serve-orin-model.sh e4b'          # e2b | e4b | 12b, extra llama-server flags after it
ssh g1 'cd ~/harness && python3 -B bench/run_bench.py --tag orin-e4b --model gemma4-e4b --variants "where-free-off-480x336,face-tool-480x336,box-prefill-480x336"'
ssh -f -N -L 18080:127.0.0.1:8080 g1               # on the Mac: model-written code runs here, not on PC2
python3 -B bench/codegen_probe.py --base-url http://127.0.0.1:18080/v1 --model gemma4-e4b --tag orin-e4b --set hard
ssh g1 '~/spike/serve-orin.sh'                      # back to the E2B demo server
```

## Evidence (`experiments/`)
- Perception, run on PC2 and copied back: `20261022T182330.849459Z-latency-orin-e2b-unpinned`, `20261022T182718.689134Z-latency-orin-e4b-unpinned`, `20261022T183312.995044Z-latency-orin-12b-unpinned`. Tegrastats logs stay on PC2 (`~/spike/tegrastats-{e2b,e4b,12b}.log`).
- Code writing, run on the Mac against PC2: `20261022T182614.396866Z-codegen-orin-e2b-unpinned`, `20261022T183149.919784Z-codegen-orin-e4b-unpinned`, `20261022T184110.797579Z-codegen-orin-12b-unpinned`, `20261022T184433.829212Z-codegen-hard-orin-12b-unpinned`. These predate the `--set` flag: the unmarked ones are the basic set (new runs are named `-codegen-basic-` / `-codegen-hard-`).
- Mac reference, E2B on the M4 Pro: `20261022T182247.563034Z-codegen-mac-e2b` (2/9, lenient 4/9, 1.6 s median at 9 ms per token). Superseded: `20261022T182155.478370Z-codegen-mac-e2b` (before the "keep the code short" line and the lenient grade; 2/9 at 271 tokens median).
