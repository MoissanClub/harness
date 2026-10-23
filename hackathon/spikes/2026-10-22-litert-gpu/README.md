# 2026-10-22 (11:48-11:53 PT, PC2 over ssh, no motion): LiteRT-LM on the Orin GPU for the spoken order

Ran `hackathon/briefs/2026-10-21-litert-gpu.md` (code `8c14122`, plan `e6d9e2f`) after the other session's llama.cpp 12B eval had
released the GPU (the owner asked to wait for it). Result: **`GATE pc2-unpinned-1 GPU: PASS`**, and coexistence passes. LiteRT-LM
0.18.0 runs Gemma 4 E2B on the Orin GPU (WebGPU over Vulkan) and hears the order as accurately as llama.cpp, about 0.35-0.46 s
slower per order, with both engines resident and llama.cpp's vision call unchanged.

Logs: PC2 `~/spike/litert_gpu/`, synced to this folder (`orders.jsonl` = every request, `report_pc2-unpinned-1.txt` = the gate,
`smoke_*.log` = the load stages, `experiments/` = the two run_bench folders moved out of PC2's clone). The six Sunday clips are now
fixtures in `hackathon/spikes/clips/sunday/`.

## Setup

| Item | Value |
| --- | --- |
| Code | `8c14122` (not pushed: copied by the plan's fallback; sha16 probe `6629057f370b9959`, vk_probe `0dcc9c40bad4b71e`, hash file `c084f4b198175386` = the commit's, clips fingerprint `cc95d4aca5bf6c39`, five prebuilt libraries `OK` against the committed hashes) |
| PC2 | JetPack 6.2 (R36.4.3), MAXN, **`jetson_clocks` not run since boot** (schedutil, CPU min 729.6 MHz), **teleimager camera services running**; up 26 min at the start |
| Runtime | conda env `litert` (`~/miniconda3/envs/litert/bin/python`, 3.10.20; `conda` is not on PATH over ssh), `litert-lm-api` 0.18.0 |
| Model | `~/litert/gemma-4-E2B-it.litertlm` sha256 `181938105e0e...` (Sunday's download) |
| GPU stage used | B: `LD_LIBRARY_PATH=~/litert/prebuilt-v0.18.0`, cache `~/litert/cache-gpu-b` |
| llama.cpp | `serve-orin.sh` E2B (`a2878d30d`, `-np 1 -c 4096 --swa-full --cache-ram 0`) |
| Vulkan | `NVIDIA Tegra Orin (nvgpu)`, integrated GPU, Vulkan 1.3.251 (`vk_probe.py` exit 0) |

## Runs

| Block | Result |
| --- | --- |
| GPU load, stage A (wheel only) | works: `Selected adapter: NVIDIA Tegra Orin (nvgpu), arch=ampere, backend=Vulkan`, load 6.35 s cold, "Meow" in 3.24 s (TTFT 1.72 s, prefill 15 tok/s, decode 6.4 tok/s), "WebGPU sampler not available, falling back to statically linked C API". Neither the #2570 failure nor Sunday's hang reproduced |
| GPU load, stage B (prebuilt folder) | works: load 5.81 s cold, "Meow" in 1.77 s (TTFT 0.19 s, prefill 174 tok/s, decode 16.5 tok/s); mapped `libLiteRtTopKWebGpuSampler.so` and `libwebgpu_dawn.so` from the prebuilt folder, the accelerator stays the wheel's static one. Warm load 1.62 s, "Meow" 0.85 s |
| Solo, LiteRT GPU (stage B) | sunday 10/12, p50 0.562 s, max 0.683 s; v2 26/28, p50 0.628 s, max 0.677 s; GR3D 99% on every request |
| Solo, llama.cpp | sunday 10/12, p50 0.217 s, max 0.265 s (Sunday pinned: 10/12, 0.22 s: the stop rule holds); v2 26/28, p50 0.168 s, max 0.258 s |
| Solo, one-word image gate (run_bench) | 77/78, p50 321.5 ms (Sunday pinned 320 ms) |
| Gate (`--report`) | sunday PASS, v2 PASS, `GATE pc2-unpinned-1 GPU: PASS` |
| Coexistence (both resident) | LiteRT v2 26/28, p50 0.629 s (solo 0.628); image gate 77/78, p50 319.8 ms (solo 321.5); MemAvailable 8,211 MB, RAM used 7.3 GB: all three criteria pass |
| Fallback (LiteRT CPU) | not run (the GPU passed) |
| Close | PC2 clone differs from boot only by the four copied paths (expected for the fallback); no tegrastats left; E2B server up (pid 4623) |

## Counts

| Set (n) | LiteRT GPU | llama.cpp | Per-clip difference |
| --- | --- | --- | --- |
| sunday (6 clips x 2 = 12) | 10/12 | 10/12 | none by count; both miss es_red both rounds, differently: LiteRT `red en` (item right, language wrong), llama.cpp `none en` |
| v2 (14 clips x 2 = 28) | 26/28 | 26/28 | LiteRT right on "a coke please" (`none`; llama.cpp `3`, the black coffee), wrong on "give me the chi" (`1`; llama.cpp `2`) |

Where the time goes (medians, LiteRT benchmark info and llama.cpp timings):

| | LiteRT GPU sunday | LiteRT GPU v2 | llama.cpp sunday | llama.cpp v2 |
| --- | ---: | ---: | ---: | ---: |
| Prompt tokens processed per order | 123 (no prefix kept across conversations) | 129 | 47 fresh + 76 cached | 32 fresh + 97 cached |
| Prefill | 859 tok/s | 688 tok/s | 144 ms | 128 ms |
| Output tokens / decode | 3 at 23.5 tok/s | 2 at 22.6 tok/s | 3 in 64 ms | 2 in 32 ms |
| TTFT | 0.174 s | 0.296 s | | |
| Wall p50 | 0.562 s | 0.628 s | 0.217 s | 0.168 s |

Decode at 23 tok/s matches Google's Orin Nano GPU figure (24.2). About 0.25 s per order is outside the reported prefill and decode;
the CPU audio tower is the likely owner (not measured separately). Conversation creation costs about 1 ms.

## Root causes

- Sunday's `--backend=gpu` hang: not reproduced with the same wheel, model and board. Unknown; the remaining candidate is the
  contention with the llama.cpp build at 15 W that night.
- Stage A vs B speed: B loads the WebGPU top-k sampler; without it sampling falls back to the CPU C API (the log says so), and stage
  A's first turn ran at 15 / 6 tok/s against B's 174 / 16.5. Stage A was not timed beyond the smoke turn, so the full cost of the CPU
  sampler is not measured.

## Deviations

- The owner asked this session to run the test; the plan named a fresh robot session as the driver (`DEV_WORKFLOW.md` section 6).
- `jetson_clocks` not run and the teleimager services left running: both need sudo, which this session does not type. Tagged
  `pc2-unpinned-1`. Both engines ran under the same conditions; llama.cpp's numbers equal Sunday's pinned ones, so the clocks cost
  little here. A pinned rerun is tag `pc2-solo-1`.
- Code copied by the plan's no-push fallback (identity by sha16 instead of `CODE 8c14122`); `conda info --base` replaced by the env's
  path; the coexistence hold released through a FIFO because the driver had no terminal on PC2.
- The hang watches first matched their own ssh shell (`pgrep -f` with the pattern in the command line); replaced with `[l]itert...`.
  They only listed processes.

## Debrief (owner)

To fill: is about 0.6 s acceptable on stage for the order step (vs 0.2 s)? Enter the LiteRT track, and ask AGI House whether one
project may enter Track 2 too? Run the pinned rerun?

## Open items

- A build session (its own brief) for a LiteRT-LM `hear_choice` path behind a flag, llama.cpp as the fallback, vision unchanged; it
  measures the full footprint with YOLOE, the RealSense and the brain (this session measured the two engines only: 7.3 GB used).
- Keep one engine per prompt warm and test whether a reused conversation (prefix kept) cuts the 123-129 prompt tokens per order.
- Pinned rerun (`sudo jetson_clocks`, teleimager stopped) for the slide numbers; push `8c14122`/`e6d9e2f` so PC2's clone has the probe.
- The real-voice test in a loud room remains for both engines (sunday clips synthetic; v2 has one C922 recording).
