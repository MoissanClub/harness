# Run plan: litert-gpu (PC2 only, no motion)

Written 2026-10-21 (S0) for the owner's approval; revised after an independent review the same evening. One experiment: does
LiteRT-LM run Gemma 4 E2B on the Orin's GPU, and does it hear the spoken order as fast and as well as llama.cpp? The robot is powered
in its stand for PC2 only: nothing in this plan publishes to DDS, enables the arm or runs `brain.py`; the remote is not touched. Slot:
any PC2 boot before the Fri 12:00 freeze, never interleaved with another GPU job (the kill test, `brain.py`, a benchmark). About 60
minutes of battery, compute load only. Driver: a fresh `robot-<date>` session that reads this plan, `ROBOT_RULES.md` and the Sunday
note; the session that wrote the probe does not drive (`DEV_WORKFLOW.md` section 6).

Why now: Best Use of LiteRT pays $7.5k / $5k / $2.5k and is its own submission track (event page re-read 2026-10-21). Google AI Edge's
Jetson guide (`litert-samples/samples/platforms/nvidia`, Oct 11-17) runs Gemma 4 E2B text on the Orin GPU through LiteRT's WebGPU
accelerator over Vulkan, vision and audio towers on the CPU, Orin NX "expected to work" on JetPack 6. Sunday's LiteRT-LM numbers
(`2026-10-18-orin-sunday.md`: 4.5-15x slower than llama.cpp) were CPU only; `--backend=gpu` hung for 10 min at 0.1% CPU while the
llama.cpp build was running, and was never retried. Correction to the Oct 21 chat: the 0.18.0 wheel is not missing Dawn (it is
statically linked in `liblitert-lm.so`, which dlopens `libvulkan.so.1`); what the wheel lacks are the `prebuilt/linux_arm64`
libraries (WebGPU accelerator, GPU sampler, `libwebgpu_dawn.so`). The only Orin NX 16 GB success report (LiteRT-LM issue #2570,
2026-09-14) put those on `LD_LIBRARY_PATH`. Cause of Sunday's hang: unknown (candidates: the build's contention at 15 W, the Vulkan
driver path, the #2570 delegate failure).

## Question

On PC2 at MAXN, does LiteRT-LM 0.18.0 with the GPU backend answer the spoken order (the Sunday two-word prompt and v2's
`hear_choice` prompt) within 1 s p50 with llama.cpp's accuracy on the same clips, measured in the same session?

## The deciding number

- Measured quantity: wall time per spoken order, seconds, from creating the conversation to the answer (LiteRT-LM; a fresh
  conversation per order, as the brain would use it) or the HTTP round trip (llama.cpp, whose system prefix is cached by the
  server); correct answers per set and per clip; GR3D % during each request (tegrastats, sampled by the probe every 100 ms).
- Sets, n fixed: **sunday** = `order_words.py`'s two-word prompt over the six Sunday clips (`~/spike/clips`) x 2 rounds = the 12 Sunday
  requests; **v2** = `gemma.py`'s `hear_choice` prompt with scene "three" (1 purple la croix, 2 silver chi sparkling, 3 black coffee)
  over `hackathon/spikes/clips/v2` (13 macOS `say` clips in en/fr/es/zh plus the owner's Oct 19 C922 recording) x 2 rounds = 28.
  Greedy on both engines, thinking off, clips rotated, one untimed warm-up per set.
- Pass (GPU), per set, both sets, against llama.cpp rows with the same tag (this session): every expected request answered (no errors
  on either engine); p50 <= 1.0 s and max <= 1.5 s; correct >= llama.cpp's count minus one clip (2 requests: greedy decoding repeats a
  clip's answer across rounds, so counts move in pairs); GR3D >= 50% (median of the per-request maxima: proof the GPU ran). The 1.0 s
  keeps "every Gemma call in the demo loop is under one second on the robot" true. Coded in `litert_gpu_probe.py` (`GATE`,
  `ACC_SLACK_CLIPS`); `--report` prints a line per set, the per-clip differences, and `GATE <tag> GPU: PASS|FAIL|INCOMPLETE`.
- Coexistence (only after a GPU pass; the demo keeps llama-server for vision and LiteRT-LM for hearing): with both resident, LiteRT
  v2 p50 within 20% of its solo p50; the one-word gate (`run_bench.py`, `where-free-off-480x336`, 78 images) p50 within 10% of this
  session's solo run and accuracy within one image of it; MemAvailable >= 2048 MB at the hold. Read from the SUMMARY lines, run_bench's
  line and `free -m`, not from `--report` (the resident tag has v2 only and prints INCOMPLETE).
- Fallback (the GPU did not load at either stage, or `GATE GPU` failed): LiteRT-LM CPU, 8 threads, same sets, same tag as the solo
  llama.cpp run, p50 <= 1.5 s, max <= 2.5 s, same accuracy rule (`GATE <tag> CPU`). A CPU pass is the owner's call (an honest
  "LiteRT-LM on the CPU" in the loop), not an automatic swap.
- Predictions, written before the run: llama.cpp sunday 10/12 at about 0.22 s p50 (Sunday MAXN; es_red missed both rounds), v2 about
  26/28 (Mac: "a coke please" -> 3 both rounds). LiteRT GPU p50 0.4-0.9 s (Mac ratio GPU/llama 1.7x; model card Orin Nano GPU 1,142
  prefill / 24 decode tok/s; the CPU audio tower is the unknown). LiteRT CPU p50 1.2-2.0 s (Sunday CPU text turn 0.6-1.1 s).
- Pass means: a build session (its own brief) adds a LiteRT-LM engine for `hear_choice` only, behind a flag with llama.cpp as
  fallback; vision stays on llama.cpp; the screen tags the order step "Gemma via LiteRT-LM (GPU)"; the slide uses this session's
  numbers; the owner asks AGI House whether one project may enter both Track 2 and the LiteRT track.
- Fail means: LiteRT-LM stays out of the loop and its numbers go on the slide (as the plan already says). Next plan, if wanted: the
  guide's Flutter app self-test on PC2 (`xvfb-run -a ./run.sh --selftest --skip-audio`; needs Flutter 3.47.3, apt packages with sudo
  and internet, about 1-2 h of build), which separates "the pip wheel" from "the runtime on this board".

## Held fixed

- Code: commit `8c14122` on `hackathon` (later commits are documents), which adds `hackathon/spikes/scripts/litert_gpu_probe.py`
  (sha16 `6629057f370b9959`), `vk_probe.py` (`0dcc9c40bad4b71e`), `litert_prebuilt_v0.18.0.sha256` and `hackathon/spikes/clips/v2/`
  (14 wav). Checked on PC2 by the Boot block's `CODE 8c14122` line. Not pushed yet. Prompts equal `order_words.py` and
  `hackathon/brain/gemma.py` at `7869c62` (`--selfcheck` proves it).
- LiteRT-LM: conda env `litert` on PC2 (Python 3.10), `litert-lm-api` 0.18.0 (wheel sha16 `d066db0c2bcd832b`), installed Sunday. No
  installs in this session.
- Model: `~/litert/gemma-4-E2B-it.litertlm`, 2,588,147,712 bytes, sha256 `181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c`
  (the Mac copy from litert-community revision `41c55696` matches). Not `gemma-4-E2B-it-gpu.litertlm` (2.0 GB, the size of the
  text-only web build: likely no audio tower).
- Prebuilt libraries: LiteRT-LM tag v0.18.0 `prebuilt/linux_arm64`, five files whose sha256 equal the Git LFS oids at that tag,
  committed as `hackathon/spikes/scripts/litert_prebuilt_v0.18.0.sha256` (PC2 checks the copies against the repo file, not against a
  list that travels with them); on the Mac at `~/models/litert/prebuilt-v0.18.0-linux_arm64/`. All need glibc <= 2.27; the
  accelerator and sampler link `libwebgpu_dawn.so` from the same folder. Native code from outside the committed tree: a declared
  deviation from "code arrives from a committed tree", bounded by the committed hashes.
- llama.cpp: `~/llama.cpp` at `a2878d30d` (CUDA sm_87), `hackathon/spikes/scripts/serve-orin.sh` run with `bash` (git stores it
  without the executable bit) (`-ngl 99 --jinja -np 1 -c 4096 --swa-full --cache-ram 0`), `gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf` +
  `mmproj-BF16.gguf`.
- PC2: JetPack 6.2 (L4T 36.4.3), MAXN with `jetson_clocks` this boot, the teleimager services stopped, no other GPU process.

## Before the session (Mac; the owner decides 2)

1. Done 2026-10-22 (owner approved the plan and both deviations): code commit `8c14122`, this plan committed after it.
2. Push `hackathon` to origin so PC2's `git pull` gets the commit. This also pushes the brain v2 commits not yet on origin (9 on
   2026-10-21 evening, `2d4f1ca..a4707d6`): the owner or the coordinator decides. Without a push, the Boot block copies the paths
   instead (Risks) and checks the sha16 values.
3. The driver session starts from this file.

## Bench evidence (filled before the robot is switched on)

- `litert_gpu_probe.py --selfcheck` (Mac, python3 -I): 11/11 ok (prompts match, the 14 v2 clips present, scorer on known answers).
- Mac desk run, v2 set, 28 requests each, serial, `~/models/litert/gemma-4-E2B-it.litertlm`: llama.cpp (port 8080) 26/28, p50 0.104 s;
  LiteRT-LM CPU 8 threads 26/28, p50 0.339 s; LiteRT-LM GPU (Metal) 28/28, p50 0.172 s, max 0.182 s, load 1.9 s cold. Per clip: llama
  misses "a coke please" (3), CPU misses "give me the chi" (1), GPU misses none. The desk run found one bug, fixed: the engine refuses
  a cache directory that does not exist (the probe now creates it). Mac numbers are not Orin numbers.
- Gate logic (`--report`), on the Mac rows and four synthetic Orin-shaped files: Mac rows give a per-set FAIL for want of GR3D proof
  and `INCOMPLETE (missing sunday)`; one extra missed clip passes, two fail; one errored request fails its set; a LiteRT tag with no
  llama.cpp rows of the same tag fails.
- `vk_probe.py` (Mac): the no-libvulkan path exits 1 with its verdict line. The success path cannot run on the Mac (no Vulkan).
- The 0.18.0 aarch64 wheel inspected on the Mac: `liblitert-lm.so` (133 MB) needs only libc/libm/libdl/librt/libpthread, carries Dawn
  and the WebGPU accelerator statically, dlopens `libvulkan.so.1`, and looks for `libLiteRtTopKWebGpuSampler.so` on `LD_LIBRARY_PATH`
  ("GPU sampler unavailable. Falling back to CPU sampling" otherwise). The Python `Engine` has no option to wait for GPU weight uploads,
  so `load_s` may exclude part of the upload; the smoke turn and the warm-up are untimed and absorb it.
- Independent review of this plan (same evening): 11 findings, all applied (the push, `bash serve-orin.sh`, `PIPESTATUS`, 300 s
  timeouts with a hang watch, per-clip slack, a tag-keyed gate, the fallback flow, same-session baselines, a tegrastats pre-check,
  post-crash health checks, the committed library hashes, the driver session, the `experiments/` folder, commands out of the table); and the probe's own tegrastats sampler now exits
  with the probe (Linux parent-death signal), so a crash leaves no orphan.
- Not checkable offline (each is a block below): Vulkan on PC2; which of the four GPU outcomes the Orin gives (works / exits with no
  text, the #2570 shape / segfault / hang); GR3D; memory with both engines resident.

## Blocks (60 minutes, hard stops)

Commands are in the next section, verbatim, by block. tmux on PC2 with three panes: 1 the commands, 2 the hang watch, 3 the monitor.

| Block | Minutes | What | Expected output lines |
| --- | --- | --- | --- |
| Boot and identity | 0-10 | owner: robot on in the stand, straps on, battery % noted, remote untouched. Agent: code, git state, power, GPU idle, runtime, model, clips, libraries; start pane 3 | `CODE 8c14122` (never check out an older commit to make it match); `6629057f370b9959`, `0dcc9c40bad4b71e`; the git-status line count (recorded); `NV Power Mode: MAXN`; a tegrastats line with `GR3D_FREQ 0%` (GPU idle, readable without root); `0.18.0`; `181938105e0e...`; en_blue en_green en_other en_red es_red zh_green; MemAvailable over 12 GB; five `: OK` |
| Vulkan | 10-12 | is the Orin GPU visible to Vulkan | `device: NVIDIA Tegra Orin (nvgpu) \| integrated GPU \| Vulkan 1.3.x`, `VULKAN OK: ...`, exit 0. Failure: the diagnostics, then straight to Solo (llama.cpp half) and Fallback |
| GPU load | 12-27 | smoke only (load + "Say meow."): stage A the wheel alone, stage B with the prebuilt folder, then the stage the experiment uses once more on its cache (the first GPU run compiles shaders). Pane 2 watches for a hang | per stage: `engine gpu ready in N s {...}`, `smoke: 'Meow' in X s {...}`, `mapped after smoke: [...]` (stage B: `libLiteRtWebGpuAccelerator.so` and `libwebgpu_dawn.so` from `prebuilt-v0.18.0`), `EXIT 0`. Record each stage's shape: works / no text (#2570) / `EXIT 139` / `EXIT 124` (timeout) / stopped as a hang. Then set `G` and `C` |
| Solo | 27-42 | the variable is the engine. LiteRT GPU (skipped if neither stage loaded), then llama.cpp always, then the one-word gate baseline, then the report | 40 request lines per engine, GPU lines with `gr3d=` over 50; `SUMMARY gpu sunday`, `SUMMARY gpu v2`, `SUMMARY llama sunday` (10/12 near 0.22 s), `SUMMARY llama v2`; run_bench's `where-free-off-480x336` line (77/78, p50 near 320 ms) and `Saved: .../experiments/...-latency-orin-solo`; `GATE pc2-solo-1 GPU: PASS\|FAIL` |
| Coexistence or Fallback | 42-52 | `GATE GPU: PASS`: both engines resident. Otherwise: LiteRT CPU with llama-server stopped, same tag | Coexistence: `HOLD:`; `free -m` MemAvailable >= 2048; run_bench line within 10% of the solo p50 and within one image; `SUMMARY gpu v2` p50 within 20% of solo. Fallback: `SUMMARY cpu ...` and `GATE pc2-solo-1 CPU: PASS\|FAIL` |
| Close | 52-60 | the run_bench folders out of the clone, git state as at boot, results and the Sunday clips to the Mac, server back if the next session needs it | `CLEAN AS AT BOOT`; the logs, `orders.jsonl`, `report_*.txt`, six wav files on the Mac |

## Commands

Variables, set once in each pane (bash):

```bash
LP=$(conda info --base)/envs/litert/bin/python; P=~/harness/hackathon/spikes/scripts; O=~/spike/litert_gpu; T=pc2-solo-1
```

A rerun of a block after a written hypothesis uses a new tag (`T=pc2-solo-2`) and new log names, so `--report` never merges two runs.

**Boot and identity** (pane 1, PC2):

```bash
cd ~/harness && git pull && git log -1 --format='%h %s'
git diff --quiet 8c14122 HEAD -- hackathon/spikes/scripts/litert_gpu_probe.py hackathon/spikes/scripts/vk_probe.py hackathon/spikes/scripts/litert_prebuilt_v0.18.0.sha256 hackathon/spikes/clips/v2 && echo CODE 8c14122
sha256sum $P/litert_gpu_probe.py $P/vk_probe.py | cut -c1-16
mkdir -p $O && git -C ~/harness status --porcelain > $O/git_status_boot.txt; wc -l < $O/git_status_boot.txt
sudo nvpmodel -q | head -1
sudo jetson_clocks
sudo systemctl stop teleimager-realsense-webrtc teleimager-compat
pgrep -x llama-server && pkill -x llama-server
timeout 3 tegrastats --interval 100 | tail -1
$LP -I -c 'import importlib.metadata as m; print(m.version("litert-lm-api"))'
sha256sum ~/litert/gemma-4-E2B-it.litertlm
ls ~/spike/clips/*.wav
free -m; df -h ~
```

Mac, then the check on PC2 against the committed hash file:

```bash
rsync -a ~/models/litert/prebuilt-v0.18.0-linux_arm64/*.so g1:~/litert/prebuilt-v0.18.0/
ssh g1 'cd ~/litert/prebuilt-v0.18.0 && sha256sum -c ~/harness/hackathon/spikes/scripts/litert_prebuilt_v0.18.0.sha256'
```

Pane 3, the monitor for the temperature and memory stop rules (left running; Ctrl-C at Close):

```bash
tegrastats --interval 5000
```

**Vulkan** (pane 1):

```bash
python3 -I $P/vk_probe.py
```

Only on failure:

```bash
ls /etc/vulkan/icd.d /usr/share/vulkan/icd.d; ldconfig -p | grep -i vulkan
dpkg -l | grep -E 'libvulkan1|nvidia-l4t-3d-core|nvidia-l4t-vulkan'
```

**GPU load.** Pane 2, the hang watch (a shader compile burns CPU; Sunday's hang sat at 0.1%):

```bash
while sleep 60; do ps -o stat,pcpu,etime,wchan:24,args -p "$(pgrep -d, -f litert_gpu_probe.py)" 2>/dev/null | cut -c1-110; done
```

Pane 1, stage A then stage B:

```bash
timeout -k 10 300 $LP -I $P/litert_gpu_probe.py --engine gpu --smoke --verbose --cache ~/litert/cache-gpu-a 2>&1 | tee $O/smoke_a1.log; echo EXIT ${PIPESTATUS[0]}
env LD_LIBRARY_PATH=$HOME/litert/prebuilt-v0.18.0 timeout -k 10 300 $LP -I $P/litert_gpu_probe.py --engine gpu --smoke --verbose --cache ~/litert/cache-gpu-b 2>&1 | tee $O/smoke_b1.log; echo EXIT ${PIPESTATUS[0]}
```

After any crash, timeout or hang stop, before the next command:

```bash
pgrep -a -x tegrastats    # only pane 3's --interval 5000 monitor: the probe's own sampler dies with the probe
python3 -I $P/vk_probe.py
sudo dmesg | tail -30 | grep -i -E 'nvgpu|gpu|mmu|fault'
ps -eo stat,pid,args | awk '$1 ~ /^D/'
```

Only if both stages failed quickly (not by timeout or hang) and at least 8 minutes of the block remain, the runtime's own CLI rules
out the probe script:

```bash
env LD_LIBRARY_PATH=$HOME/litert/prebuilt-v0.18.0 timeout -k 10 300 $(dirname $LP)/litert-lm run ~/litert/gemma-4-E2B-it.litertlm --backend=gpu --prompt "Say meow." 2>&1 | tee $O/cli_b1.log; echo EXIT ${PIPESTATUS[0]}
```

Then the stage the experiment uses, pre-registered (both worked: B, the full GPU path the guide's bundle ships), and its warm load:

```bash
G=; C=~/litert/cache-gpu-a                                                          # only A worked
G="env LD_LIBRARY_PATH=$HOME/litert/prebuilt-v0.18.0"; C=~/litert/cache-gpu-b       # B worked
$G timeout -k 10 300 $LP -I $P/litert_gpu_probe.py --engine gpu --smoke --cache $C 2>&1 | tee $O/smoke_warm.log; echo EXIT ${PIPESTATUS[0]}
```

**Solo** (pane 1). LiteRT GPU, skipped if neither stage loaded:

```bash
$G timeout -k 10 900 $LP -I $P/litert_gpu_probe.py --engine gpu --sets sunday,v2 --cache $C --tag $T --out $O/orders.jsonl 2>&1 | tee $O/solo_gpu_$T.log; echo EXIT ${PIPESTATUS[0]}
```

llama.cpp, always (after the LiteRT process has exited), then the one-word gate baseline, then the report:

```bash
bash $P/serve-orin.sh
python3 -I $P/litert_gpu_probe.py --engine llama --sets sunday,v2 --tag $T --out $O/orders.jsonl 2>&1 | tee $O/solo_llama_$T.log
(cd ~/harness && python3 -B bench/run_bench.py --tag orin-solo --variants where-free-off-480x336) 2>&1 | tail -3
python3 -I $P/litert_gpu_probe.py --report $O/orders.jsonl | tee $O/report_$T.txt
```

If run_bench stops on a missing or stale scaled image (it calls `sips`, which PC2 lacks), note it: the coexistence block then uses
the llama.cpp probe on v2 instead, compared with `SUMMARY llama v2` above.

**Coexistence** (only after `GATE <tag> GPU: PASS`; llama-server stays up). Pane 1:

```bash
$G $LP -I $P/litert_gpu_probe.py --engine gpu --sets v2 --cache $C --tag pc2-resident-1 --hold --out $O/orders.jsonl 2>&1 | tee $O/resident_gpu.log
```

At `HOLD:`, in pane 2 (stop the hang watch first with Ctrl-C):

```bash
free -m
(cd ~/harness && python3 -B bench/run_bench.py --tag orin-resident --variants where-free-off-480x336) 2>&1 | tail -3
python3 -I $P/litert_gpu_probe.py --engine llama --sets v2 --tag pc2-resident-1 --out $O/orders.jsonl    # only if run_bench failed in Solo
```

Then Enter in pane 1.

**Fallback** (the GPU did not load, or `GATE GPU` failed). Pane 1, same tag as the solo llama.cpp run:

```bash
pkill -x llama-server
$LP -I $P/litert_gpu_probe.py --engine cpu --threads 8 --sets sunday,v2 --cache ~/litert/cache --tag $T --out $O/orders.jsonl 2>&1 | tee $O/solo_cpu_$T.log
python3 -I $P/litert_gpu_probe.py --report $O/orders.jsonl | tee $O/report_${T}_cpu.txt
```

**Close.** Pane 3 Ctrl-C. Pane 1 (PC2), then the Mac:

```bash
mkdir -p $O/experiments && mv ~/harness/experiments/*-latency-orin-solo ~/harness/experiments/*-latency-orin-resident $O/experiments/ 2>/dev/null; ls $O/experiments
git -C ~/harness status --porcelain | diff $O/git_status_boot.txt - && echo CLEAN AS AT BOOT
bash $P/serve-orin.sh    # only if the next session needs the server
```

```bash
rsync -a g1:~/spike/litert_gpu/ hackathon/spikes/<date>-litert-gpu/
rsync -a g1:~/spike/clips/ hackathon/spikes/clips/sunday/
```

## Stop rules for this plan

The general rules in `DEV_WORKFLOW.md` section 4 apply. Plan-specific:

- Nothing here commands the robot. If the robot moves, the FSM changes or a DDS publisher is found running, stop and write it down.
- Deviation for the owner to approve: `ROBOT_RULES.md` says the server is stopped only through its serve script, and `serve-orin.sh`
  has no stop-only mode. The LiteRT runs need the GPU free, so the plan stops the server with the script's own stop line,
  `pkill -x llama-server` (exact process name: it cannot match the calling shell), and restarts it only through `serve-orin.sh`.
- A hang: the hang watch shows the probe under 1% CPU for two consecutive minutes with no new output in pane 1: Ctrl-C, do not wait
  for the 300 s timeout. A stage that hung or timed out is not rerun as is; at most one retry per stage, only with a written
  hypothesis in `DECISIONS.md` (example: "another GPU process held the device"), under a new log name.
- After a crash, timeout or hang, run the health checks. An nvgpu fault in `dmesg`, a process in D state, `vk_probe.py` no longer
  passing, or llama-server failing to come up: PC2 needs a reboot (the owner approves; `jetson_clocks` again after it); the GPU part
  of the session ends and the llama.cpp half runs after the reboot if time allows.
- llama.cpp on the sunday set differs from Sunday (not 10/12, or p50 over 0.30 s): no gate is read until the cause is written (power
  mode, clocks, server flags, another process).
- MemAvailable under 1 GB (pane 3 RAM over about 14,600 of 15,656 MB) or swap growing: end the LiteRT process (Enter, else Ctrl-C)
  and note it. GPU over 85 C (`gpu@` in pane 3): pause until under 70 C.
- A bug in the probe found on PC2 ends the experiment: no code edits on PC2; fix on the Mac, commit, new plan.
- No installs on PC2 (pip, apt, Flutter) in this session.
- Battery under 30 percent or 60 minutes elapsed: close.

## Owner tasks

- Before: approve this plan, the two declared deviations (stopping the server with `pkill -x`, the prebuilt libraries) and the push;
  robot on in the stand with the straps, battery noted; confirm no other session uses PC2's GPU; nothing to set up on the table.
- During: no motion tasks; approve a PC2 reboot if the health checks call for one; say "stop" at any time; read the `GATE` lines with
  the driver.
- After (debrief): is about 1 s acceptable on stage for the order step; enter the LiteRT track (and ask AGI House whether one project
  may enter two tracks); is a CPU-only LiteRT result worth showing.

## Risks

- PC2 unreachable (it was on Oct 20 evening). No push or no internet for `git pull`: copy the paths instead and check the sha16
  values: `rsync -a hackathon/spikes/scripts/litert_gpu_probe.py hackathon/spikes/scripts/vk_probe.py hackathon/spikes/scripts/litert_prebuilt_v0.18.0.sha256 g1:~/harness/hackathon/spikes/scripts/`
  and `rsync -a hackathon/spikes/clips/v2/ g1:~/harness/hackathon/spikes/clips/v2/` (the Close git-state check then lists them as
  untracked: expected, written in the note). The `CODE 8c14122` line fails then (the commit is not on PC2): the sha16 lines are the
  identity check, and the v2 clips are checked with `cd ~/harness/hackathon/spikes/clips/v2 && sha256sum *.wav | LC_ALL=C sort | sha256sum | cut -c1-16`
  (expected `cc95d4aca5bf6c39`, the Mac's value at `8c14122`).
- The v0.18.0 prebuilt libraries may not suit the wheel's statically linked runtime and crash at load in stage B: that is a result
  (recorded), not a reason to try other versions in this session.
- tegrastats may need root for GR3D: the Boot pre-check shows it. If the line has no `GR3D_FREQ`, run
  `sudo tegrastats --interval 100 --logfile $O/tegra.log` in pane 3 during Solo and read GR3D during the run from it; the probe's gate
  then prints FAIL for want of proof and the driver states the log's numbers next to it.
- The sunday clips are synthetic; v2 has one real C922 recording. Neither engine is tested on real guests in a loud hall.
- Two engines resident plus YOLOE, the RealSense and the brain is not measured here; the build session measures the full footprint.
- Each order creates a fresh conversation and re-prefills the system prompt (LiteRT-LM keeps no prefix across conversations in this
  probe, while llama-server caches it); a build that keeps one conversation per prompt could be faster, but that is not what is
  measured.
