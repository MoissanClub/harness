# Sunday Oct 18: first evening on the robot's Jetson (PC2)

Robot online over Tailscale (`ssh g1`). Nothing moved the robot. Scripts in `scripts/` (copies of what ran on PC2 under `~/spike` and `~/litert`).

## PC2 as found
- `unitree-g1-nx`, JetPack 6.2 (L4T 36.4.3), Ubuntu 22.04.5, kernel 5.15.148-tegra. CUDA 12.6 runtime and TensorRT 10.3 runtime installed (the lean set from `~/g1-fetch/scripts/pc2_setup.sh`); no `nvcc`. Power mode 15 W (ID 2) with 4 of 8 cores online; modes MAXN(0)/10W(1)/15W(2)/25W(3); `nvpmodel -m 0` asks for a reboot. 15 GB RAM (13 free), 1.9 TB NVMe (1.7 TB free). No docker. Nix present. conda envs: `g1fetch` (torch 2.11 CUDA, TensorRT 10.3, transformers 5.5.3, ultralytics, pyrealsense2 2.58, unitree_sdk2py), `uni`, `tv`, `teleimager`, `studio`.
- Running services: `brainco_hand.service`, `teleimager-realsense-webrtc.service` + `teleimager-compat.service` + `mediamtx.service` (hold the D435i), `tailscaled`, `g1-pc2-usb-wifi-ap-vht80.service`, pulseaudio. Audio capture devices: only the Jetson APE (no USB mic).
- `~/g1-fetch` (owner's fridge-fetch project, status 2026-10-16): LocoClient wrapper, arm_sdk streamer + pinocchio IK, BrainCo hands, `cli check` preflight, AudioClient TTS status, OpenAI-compatible yes/no VLM verifier. Its `docs/05_deploy_learnings.md` and `docs/06_dependency_learnings.md` are binding: DDS interface `enP8p1s0`, `mode_machine` 4, controller velocity deadband (min 0.14 m/s), poll lowstate instead of a 500 Hz callback, detector warm-up before opening the camera, torch only from the Jetson index, never `pkill -f` a self-matching pattern.

## Done tonight
- Root-free CUDA 12.6 toolkit: `apt-get download` of cuda-nvcc/crt/nvvm/cudart(-dev)/driver-dev/libcublas(-dev)/cccl, `dpkg -x` into `~/cuda-user/root/usr/local/cuda-12.6` (1.7 GB). `nvcc` 12.6.68 runs; cuBLAS and CUB headers and the driver stub are present. System packages untouched.
- llama.cpp cloned at `a2878d30d` (the Mac benchmark build b10909) in `~/llama.cpp`; CUDA build started with `~/llama-build.sh` (`-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87`, user-space toolkit, `-j4`), log `~/llama-build.log`. At 15 W on 4 cores it was at 30% after about an hour (the flash-attention and MMQ template instances dominate).
- Model files copied from the Mac cache to `~/models/gemma4`: `gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf` (2.62 GB), `mmproj-BF16.gguf` (0.99 GB, contains the audio encoder), `mtp-gemma-4-E2B-it.gguf`. Harness `bench/` scripts and the 480x336 image set at `~/harness/bench` so `run_bench.py` gives numbers comparable to the Mac table. Server launcher `~/spike/serve-orin.sh`; spoken-order probe `~/spike/order_probe.py`; test clips (macOS `say`, 16 kHz mono) in `~/spike/clips`.
- Audio over DDS (`audio_probe.py`, `mic_probe.py`): `AudioClient.TtsMaker(text, 1)` returned 0 and played through the robot speaker (owner heard it); `rt/audio_msg` carried `{"play_state":1}` then `{"play_state":0}`. The 4-mic multicast (239.168.123.161:5555) sent no packets: the stream only flows while the voice assistant's wake mode is on (app or L1+L2). Community voice API 1008 `{"mode":1}` returned error 3103 on this firmware.
- LiteRT-LM 0.18.0 (`litert-lm`, `litert-lm-api`, `litert-lm-builder`) installed in conda env `litert` (Python 3.10; venvs failed on `ensurepip`). Official bundle `gemma-4-E2B-it.litertlm` (2.59 GB) downloaded to `~/litert`. The wheel ships only `liblitert-lm.so` (GPU WebGPU accelerator statically registered, no Vulkan/Dawn library).

## LiteRT-LM measurements (CPU, 4 threads, 15 W, CONTENDED by the running build; rerun clean later)
| Turn | Wall time | Result |
| --- | ---: | --- |
| Engine load | 14.1 s | |
| Text "Say meow." (system prompt, no thinking) | 3.8 s cold, 3.4 s warm | "Meow" |
| Transcribe ~2 s clip (6 clips) | 6.2-7.1 s each | en x4 and zh correct; synthetic Spanish garbled |
| Audio -> `order()` tool call, automatic tool calling | 14.6-17.4 s each | item correct 5/5; language en, fr(!), en, other(es), zh; "other" clip answered "unsure" as text, no call |
| `--backend=gpu` (CLI) | hung >10 min at 0.1% CPU, killed | no GPU path on this wheel |

Rerun uncontended after the build (CPU, 4 threads, 15 W, llama-server idle): engine load 0.6 s (cached artifacts), text turn 1.6-1.8 s, transcription 3.0-3.6 s per clip (same outputs), spoken order to `order()` 7.2-8.5 s (same calls, including the wrong `fr` on en_green and `other` on es_red). Against llama.cpp CUDA on the same board (1.64 s tool call, 0.50 s two-word answer) LiteRT-LM is 4.5x and 15x slower.

Verdict for the plan: LiteRT-LM runs on the G1's Jetson but only on the CPU and at 3-15x the latency of the CUDA path for the same turn (the Tier 1 gate was 2.5 s p50). Keep it out of the demo loop; keep these numbers for the slide if useful.

## Build result and the first Orin table (same evening)
The build finished (`BUILD_EXIT=0`) after about 75 minutes at 15 W. `serve-orin.sh` brings the server up in 9 s (`-ngl 99 --jinja -np 1 -c 4096 --swa-full --cache-ram 0`); tegrastats showed GR3D at 99% during requests, 5.8 GB RAM used, GPU 51 C.

`run_bench.py --tag orin-15w`, 78 images, greedy, 480x336 (run saved under `experiments/20261018T234322.118503Z-latency-orin-15w`; the Mac column is from LATENCY_RESULTS.md):

| Variant | Strict accuracy | Orin total p50 / p90 / max | Orin prompt | Orin output | Mac p50 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `where-free-off-480x336` (one word) | 77/78 (99%) | 756 / 764 / 768 ms | 106 tok, 655 ms | 2 tok, 69 ms | 222 ms |
| `face-tool-480x336` (native tool call) | 76/78 (97%) | 1573 / 1583 / 1591 ms | 102 tok, 643 ms | 15 tok, 891 ms | 324 ms |
| `box-prefill-480x336` (box_2d) | 78/78 (100%), x_mae 0.017 | 1796 / 1810 / 1870 ms | 139 tok, 750 ms | 17 tok, 1015 ms | 378 ms |

Accuracy is identical to the Mac. Decode costs about 59-64 ms per output token at 15 W (vs 8.9 ms on the Mac), prompt processing about 6 ms per fresh token plus the image encoder. Output-token count is now the main lever: one-word gates fit the budget, tool-call syntax costs about a second.

## Audio on the Orin: works (`order_probe.py --rounds 2 --mixed`, results in `orin-sunday/order_results.jsonl`)
Spoken clip (macOS `say`, 16 kHz mono) as an `input_audio` part after the instruction text, system prompt plus `order`/`unsure` tools, thinking off, greedy; llama.cpp commit a2878d30d, CUDA sm_87, the same `mmproj-BF16.gguf` as the Mac.

| Clip | Round 1 and 2 result | Total | Prompt | Output |
| --- | --- | ---: | ---: | ---: |
| en_blue | `order(blue_can, en)` both rounds | 1.62 s | 38 tok / 312 ms | 21 tok / 1280 ms |
| en_green | `order(green_can, en)` both | 1.66 s | 48 tok / 364 ms | 21 tok / 1271 ms |
| en_red | `order(red_can, en)` both | 1.61 s | 35 tok / 309 ms | 21 tok / 1289 ms |
| zh_green | `order(green_can, zh)` both | 1.70 s | 59 tok / 402 ms | 21 tok / 1271 ms |
| es_red | `order(red_can, other)` both: item right, language missed | 1.77 s | 82 tok / 470 ms | 21 tok / 1272 ms |
| en_other ("what time does the hackathon end?") | no tool call, 3-token empty reply both rounds (should have called `unsure`) | 0.49 s | 46 tok / 331 ms | 3 tok / 136 ms |
| image + text + audio in one request (plan A) | `order(blue_can, en)`, prefix of 200 tokens served from cache | 2.28 s | 118 tok / 960 ms | 21 tok / 1276 ms |

Item 10/10 on the can clips, language 8/10 (Spanish synthetic voice labelled `other`), p50 1.64 s. No crash, no repetition, no leaked thinking. The NVIDIA "audio issue with E2B under llama.cpp" note does not reproduce on this build. Decision: plan A/B confirmed on the robot; plan C (separate ASR) is not needed. Next levers: MAXN power mode (reboot), MTP drafting for the 21-token call (decode is 78% of the turn), or a two-word answer format instead of the tool-call syntax for the fastest path; the `unsure` miss needs a prompt tweak (or treat "no call" as unsure in code).

## Two-word answer instead of the tool call (`order_words.py`)
Same clips, system prompt asking for exactly two words (colour or none, then the language code), question text before the audio, `max_tokens 6`:

| Clip | Answer (both rounds) | Total |
| --- | --- | ---: |
| en_blue / en_green / en_red | `blue en` / `green en` / `red en` | 0.46-0.52 s |
| zh_green | `green zh` | 0.56 s |
| en_other | `none en` (correct refusal) | 0.49 s |
| es_red | `none en` (wrong; the synthetic Spanish voice was also labelled `other` by the tool variant) | 0.63 s |

10/12 correct, p50 0.50 s, max 0.63 s: three output tokens instead of 21. So on the Orin at 15 W the voice turn costs 0.5 s as a two-word answer or 1.6 s as a native tool call with identical understanding; the choice is story versus snappiness, and both are within budget. Spanish needs a real speaker on Tuesday before anything is concluded.

## MAXN (owner approved the reboot; `nvpmodel -m 0` then `jetson_clocks`; 8 cores online)
Same server flags, same scripts. `experiments/20261019T002612.680462Z-latency-orin-maxn`, `orin-sunday/order_results-maxn.jsonl`, `orin-sunday/tegrastats-maxn.log`.

| Turn | 15 W p50 | MAXN p50 (p90 / max) | Mac p50 | Accuracy (unchanged) |
| --- | ---: | ---: | ---: | --- |
| One-word gate (`where-free-off-480x336`) | 756 ms | 320 ms (321 / 323) | 222 ms | 77/78 |
| Native tool call (`face-tool-480x336`) | 1573 ms | 686 ms (687 / 691) | 324 ms | 76/78 |
| Box detection (`box-prefill-480x336`) | 1796 ms | 772 ms (778 / 803) | 378 ms | 78/78, x_mae 0.017 |
| Spoken order to `order()` tool call | 1.64 s | 0.73 s (max 0.78) | n/a | item 10/12, language 8/12 (same misses) |
| Image + audio + tools in one request | 2.28 s | 0.98 s | n/a | correct |
| Spoken order as two words | 0.50 s | 0.22 s (max 0.26) | n/a | 10/12 (same Spanish miss) |
| LiteRT-LM CPU, 8 threads: text / transcribe / order | 1.6 / 3.0 / 7.2 s (4 thr) | 0.6-1.1 / 1.3 / 3.0 s | | same outputs |

At MAXN decode is 26.6 ms per output token (452 ms for 17 tokens) and prompt processing about 2.5 ms per fresh token plus the encoder; RAM 5.7 GB, GPU 63 C under sustained load. The Orin at MAXN is within 1.5-2.1x of the Mac, and every call in the demo loop is under one second on the robot. Note: `nvpmodel -m 0` persists across reboots, `jetson_clocks` does not (run it in the preflight or add a systemd unit).

## Onboard mic: works once the voice service is fully up (needed PC1 internet to start, per the owner)
Earlier captures saw nothing: zero packets on 239.168.123.161:5555, `tcpdump` on enP8p1s0 saw no UDP 5555 at all, `GetServerApiVersion()` and the SDK's ASR id 1002 timed out (3104), the community ids 1007-1009/1011 are unknown (3103). The owner then connected PC1 to the internet ("voice is always on" in the app), and on the next capture PC1 (192.168.123.161) streamed 5120-byte datagrams (160 ms of 16 kHz mono) to the group and `rt/audio_msg` carried recognizer output with SenseVoice-style tags, e.g. `{"text":"站起来。","angle":0,"language":"<|zh|>","confidence":0.5,"emotion":"<|EMO_UNKNOWN|>","is_final":false}` (one utterance mis-tagged `<|ja|>`), plus `play_state` messages when the factory assistant answered. A 15.8 s capture (`orin-sunday/mic_capture.wav`, peak 21684/32767, RMS 1478) sent to llama-server with "Transcribe this audio." came back as `先起來。 站。 你走,這邊紅球。 先起來。` in 0.53 s; the translate variant (410 prompt tokens, 1.27 s) kept most of it in Chinese. So the onboard array, the multicast stream and Gemma's Mandarin hearing work together on the robot; quality in a loud hall is still untested (Marvik reported motor and Jetson noise on this array).

Caveat for the no-cloud rule: the stream and recognizer only appeared after PC1 had internet. Monday test: disconnect PC1 from the internet, reboot the robot, confirm the stream still flows and the assistant stays local (it should fall back to the offline mode per Unitree's docs); if it does not, the USB mic is the only path at the event. Either way the factory assistant must be asleep during the demo (it answered the wake word tonight through GPT).

## USB webcam with mic (backup audio and second viewpoint): Logitech C922 Pro Stream
Plugged into PC2 by the owner: `/dev/video6` (index0; `/dev/v4l/by-id/usb-046d_C922_Pro_Stream_Webcam_9518517F-video-index0`) and ALSA card 2 (`plughw:2,0`, USB Audio, 32 kHz stereo native; `arecord -D plughw:2,0 -f S16_LE -r 16000 -c 1` resamples to the 16 kHz mono Gemma wants). A 6 s recording (`orin-sunday/usbmic.wav`, peak 21074/32767, RMS 3026) transcribed by Gemma on the Orin as `可以。 呃貝禮白的營業師。` (0.63 s, 158 prompt tokens; owner to judge accuracy). OpenCV (`g1fetch` env) grabbed a 1280x720 MJPG frame (`orin-sunday/usbcam.jpg`); at 480x336 Gemma answered "The camera sees the interior of a room with light-colored cabinets and a person sitting on a chair." (0.89 s), "yes" to "Is a person visible?" (0.09 s, identical image already cached, so not a real latency), and boxed the person at [643, 521, 1000, 856] on the 0-1000 grid (0.60 s). Owner's decision: onboard array first, this webcam's mic as the backup; its camera is a free second viewpoint (chest or table) if the head camera's view of the rack is poor.

- Mic: verify the onboard stream with PC1 offline after a reboot (no-cloud rule); USB mic with push-to-talk stays the planned path for the hall.
