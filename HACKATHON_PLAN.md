# Gemma Hardware Hackathon plan: "Any Language, One Can"

Written Sunday 2026-10-18, six days before the event. How it was made: the event page was read in the browser; seven web-research agents (Gemma 4, LiteRT-LM, the G1, judging history, the Pixel path, prior art, hardware awards) each had their load-bearing claims re-checked by a fact-checker; six ideation angles produced 17 concepts; three judge personas (a Gemma-team judge, an AGI House investor, a G1 robotics engineer) scored them; one plan was synthesized, attacked by three red-team lenses and revised. Part A is the decision summary and where I override the red team. Part B is the full revised build plan (demo script, architecture, schedule, spikes, risk register). The research corpus with every cited URL is in `hackathon/research/`.

## Part A. Decision summary

### A0. Answers I need from you (they change the plan)

| Question | Why it matters |
| --- | --- |
| Who is on the team (3-4 required) and what can each person do: Linux/CMake, Python/web, robotics? | Fixes who owns the Orin build and the brain. Solo or two people means Tier 0 only, assisted pick from the start. |
| Will the G1 travel to Hillsborough with its protective stand, and do you have a second battery? | The whole bench day runs clipped into the stand (L2+B becomes a hang, not a fall). One pack lasts about 2 h; judging spans 10:00-15:00 plus stage. |
| Which languages can you and reachable friends speak natively (two speakers per language needed Tuesday)? | Only languages verified on the real mic Tuesday are promised on stage. English, Mandarin and Spanish are the default set. |
| Can you attend Arm Create in San Jose on Monday Oct 19 (Ian Ballantyne of Gemma DevX speaks 11:45, Matthias Grundmann of LiteRT 13:15)? | Cheapest way to meet two likely judges, show a phone video of the G1, and ask how scoring, stacking and LiteRT credit work. |
| Downloads (pre-approved Sunday, no more asking): llama.cpp source for the Orin build, Piper TTS + en/zh/es voices, `litert-lm` wheels + the `gemma-4-E2B-it.litertlm` bundle (2.58 GB, Tier 1), sherpa-onnx + Whisper small (plan C), webrtcvad. No new Gemma GGUFs are needed; the cached E2B files already contain the audio encoder. | Fetched on Monday; each run notes what was fetched. |

#### Answers so far (Sunday evening)

- Team: teammates are still to be named; with fewer than three people, the LiteRT tier is the first cut.
- Pixel: dropped by the owner on Sunday evening (not worth the trouble; leave some awards to other teams). No Android tier.
- Robot: one battery plus the charger. Whether the robot runs in its stand or free-standing is the other open decision; see A11.
- Downloads: pre-approved for anything the project needs.
- Robot: online at `ssh g1` from Sunday evening; see A12 for what was verified on it tonight.
- Still open: teammates, native speakers per language, Arm Create on Monday.

### A1. What we build

A Unitree G1 drinks host. A judge holds a push-to-talk stick and orders a can in their own language. Gemma 4 E2B on the robot's Orin NX hears the clip natively (no speech recognizer in front of it) and emits one tool call, `order(item, language)`. A second Gemma call on a fresh camera frame finds that can on a 3-slot rack (`box_2d`, the harness's 100% path). The robot confirms in the judge's language (Piper TTS), picks the can with a teleop-recorded `rt/arm_sdk` reach replayed to the slot Gemma chose, lifts it, and opens the BrainCo hand only when Gemma sees the judge's hand on the can. Order a colour that is not there and it says "I don't see a blue can; I see red and green" instead of inventing one. Everything runs on PC2; the laptop only mirrors a "brain view" page (frame, question, answer, tool call, milliseconds, provenance tag) over the robot's own access point.

Why this wins Track 2:

- It is the shape every winning humanoid demo had: language visibly grounded in what the robot sees now, one completed physical act, no operator. Judges get to be the protagonist in their own language.
- It uses what only Gemma 4 can do: native multilingual audio in, image in, native function calling, sub-second E2B perception at 70 image tokens. A judge cannot say "any model would work".
- Model choice follows this branch's own findings: DEPLOY.md (Sept 17, before the latency study) recommended E4B QAT Q4_0 for the Orin; LATENCY_RESULTS.md (Sept 21) measured E4B at 1.6-1.7x E2B's latency with no fix for thinking-off planning and dropped it. E2B is the default; E4B re-enters only if Tuesday's language table shows a promised language (Mandarin is the likely case, E2B CER 0.187 vs E4B 0.136 on FLEURS) needs it, and then it replaces E2B entirely rather than running beside it. `runner-defaults.json` and the original harness stay untouched; the hackathon brain is a new program.
- It is built on verified pieces: the Mac harness already answers perception questions in 222-378 ms and already accepts audio through the same server and the same cached `mmproj-BF16.gguf` (verified live during research: a spoken request returned a JSON order in 232-511 ms). Arm IK, BrainCo hand control and episode recording already work on this robot through xr_teleoperate.
- Honest numbers and a visible recovery are what Google's Gemma judges praise in every winners post ("disciplined, non-hallucinatory design", offline, measured latencies, failure and recovery shown).

### A2. The event in one screen

- Saturday Oct 24, 10:00-17:00 PT, doors 9:30, AGI House, Hillsborough. Teams of 3-4. Pre-building is expected: attendees are chosen for hardware they already built and told to bring their robot. Nothing not working on Oct 23 will work on Oct 24.
- The one rule: a Gemma-based model, entirely on-device, "no cloud anywhere in the loop". Judges rotate past workbenches science-fair style; the top six demo on stage. No rubric, judge list, demo length or submission checklist is published yet; re-read the event page the week of.
- Cash: Best in Show Android/Pixel $15k + Pixel 11; Track 1 Mobile and Track 2 Physical AI $7.5k/5k/2.5k each (1st also gets the "Break Glass" trophy); Best Use of LiteRT $7.5k/5k/2.5k. Hardware: 2x Pixel 11, 5x Raspberry Pi 5, 5x Coralboard (the new Synaptics SL2619 board), two Qualcomm packages (criteria unpublished; two of the six co-hosts are from Qualcomm). Whether one project can take several awards is unstated; Google's own Kaggle Gemma hackathons allowed it. The plan pays off on Track 2 alone and treats the rest as upside.
- What Google's Gemma judges reward (from their published rubric and winners posts): a working end-to-end loop on real hardware, all local; Gemma-4-specific features used, not wrapped; a human-centred story told in two sentences; honest numbers with n plus a failure and recovery; LiteRT-LM or partner silicon genuinely in the loop. What they penalize: anything cloud-touching (disqualifying), laptop-only demos, overclaimed autonomy, teleop in view, a Gemma that could be swapped out.
- Their mental benchmark is Google's own Reachy Mini demo (Pi 5, LiteRT-LM, Gemma 4 E2B, YOLO, Moonshine ASR). A humanoid that hears, sees and hands you something, reliably, clears it by a wide margin.

### A3. Award strategy: one story, gated tiers

Tier 0, always: Track 2. The loop above, robot clipped into its stand all day, the volunteer walks to the robot. Team estimate: P(the loop runs at some tier on Oct 23) 0.8; P(1st | runs) 0.35, 2nd 0.2, 3rd 0.15; EV about $3.3k plus the trophy.

Tier 1, gated Monday, backup only, never the primary engine: LiteRT-LM as the ear. The owner's rule: the end-to-end loop on llama.cpp CUDA is what we guarantee; LiteRT is added only if it costs the loop nothing. Google's `litert-lm` 0.18 pip wheels install on the Orin without building (manylinux aarch64), and the official `gemma-4-E2B-it.litertlm` bundle carries the same audio encoder and native tool calling with constrained decoding. If the ORDER turn (audio clip in, `order()` out) runs on LiteRT-LM on PC2 in at most 2.5 s p50 and the Tuesday memory soak still shows 2.5 GB free, then the voice turn runs on LiteRT-LM and the vision calls stay on llama.cpp CUDA. The slide line is honest and judge-visible: "LiteRT-LM hears you (Gemma 4 E2B, Google's own runtime); llama.cpp sees". CPU is the officially supported path (Google's Orin Nano numbers: 109 prefill / 12 decode tok/s); the WebGPU GPU path is unsupported on Jetson and only gets a 30-minute attempt with the `prebuilt/linux_arm64` LD_LIBRARY_PATH workaround. Cost: about 3 hours of one person. If it misses the gate, nothing LiteRT is claimed. Measured Sunday night on PC2 (CPU, 4 threads, 15 W, while the llama.cpp build was running): a spoken order became an order() tool call in 14.6-17.4 s, a 2 s clip transcribed in 6.2-7.1 s, a one-word text turn took 3.4 s, and the GPU backend hung; details in hackathon/spikes/2026-10-18-orin-sunday.md. Uncontended after the build it was 7.2-8.5 s per spoken order (text 1.6 s, transcription 3.0 s), 4.5x the CUDA path's tool call and 15x its two-word answer; even halved by MAXN that misses the 2.5 s gate by a wide margin, so the working assumption is now: no LiteRT claim, the numbers go on the slide as an honest evaluation if at all. Why it cannot be primary: LiteRT has no CUDA path, Jetson GPU support (WebGPU over Vulkan) is officially unsupported and reported flaky, and its vision encoder on ARM CPUs takes seconds per image, so the perception loop would lose its sub-second budget; only the voice turn is a candidate. The red team was right to kill the earlier "EmbeddingGemma 2 memory" idea (it embedded three enum values; token use); this tier is the headline voice turn itself. Added EV if stacking is allowed: roughly $1-1.5k.

Tier 2 (Pixel 11 app) was dropped by the owner on Sunday evening: not worth the trouble, and a deliberate choice to leave the Android pools to other teams.

Tier 3, gated Thursday: the stage walk. Default stage script is stationary (the robot is wheeled over in its stand). Only if Monday's `LocoClient` test shows `Move` works on our firmware in FSM 500, the organizers confirm a flat stage, and Thursday logs 10/10 clean 2 m walks with the can held at the chest, the stage version adds a short walk toward the volunteer before the handover. Walking is Unitree's controller, not our work, so this is wow, not score; a fall with BrainCo hands fitted ends the day.

Not targeted, and why: Raspberry Pi (a Pi 5 "badge" nobody owns is padding and a distraction), Coralboard ($100 board, Yocto, 8-15 h, a $500 prize), Qualcomm (criteria unknown; the VENTUNO Q cannot ship in time; a UNO Q running Gemma 3 1B at 5.5 tok/s looks like padding), Nvidia (no award). Also cut: the fridge door, grasping from clutter, SLAM, any learned policy, JetPack 7.2 or MAXN_SUPER reflash six days out, TensorRT Edge-LLM and vLLM, thinking mode, the onboard mic array as the primary mic (reported noisy), Unitree's factory assistant (GPT over the internet; it is put to sleep and proven asleep).

### A4. What runs where

```
judge's voice --> handheld wireless mic (UAC) + push-to-talk button --> PC2 ears.py (16 kHz, VAD, 8 s cap)
                                                                           |
   PC2 (Orin NX 16 GB, JetPack 6.2):                                       v
   ORDER turn: Gemma 4 E2B, audio in, native tools --> order(item, language)   [llama.cpp CUDA; Tier 1: LiteRT-LM]
   LOCATE: fresh 480x336 head-camera frame --> box_2d of the ordered can --> slot (code)   [llama.cpp CUDA]
   GATES: "Is the hand holding a can?" / "Is a human hand on the can?" one-word answers    [llama.cpp CUDA]
   brain.py state machine: IDLE > LISTEN > UNDERSTAND > CONFIRM > LOCATE > PICK > VERIFY > HANDOVER > RECOVER
     arm: recorded joint trajectories replayed through xr_teleoperate's G1_23 arm controller on rt/arm_sdk (50 Hz)
     hand: rt/brainco/right/cmd (0..1), stall and pull from /state
     speech: Piper TTS (en/zh/es) --> USB speaker (the 3 W onboard speaker loses the hall)
     safety: robot clipped into its stand in locked stand FSM 500; spotter holds the R3 remote on L2+B; never L2+R2
   brain view (SSE) --> laptop browser over the robot's own 5 GHz AP, no uplink
```

Measured Sunday night on the robot at MAXN (8 cores, jetson_clocks, GPU at 99%, 5.7 GB RAM, 63 C): one-word gate 320 ms, face_target tool call 686 ms, box_2d 772 ms, spoken order to order() call 0.73 s (0.98 s with the image in the same request), or 0.22 s as a two-word answer (colour plus language code) with the same understanding, all with Mac-identical accuracy; decode is 27 ms per output token. At 15 W everything was 2.3x slower, so MAXN is the demo power mode (nvpmodel persists; jetson_clocks goes in the preflight). Every call in the loop is under one second on the robot; the projections below predate these measurements. Scaling the Mac measurements by the Orin NX's roughly 2.5-3x lower memory bandwidth and the reported ~27 ms per output token (CLAUDE.md, DEPLOY.md): one-word gates about 0.6-0.9 s (Mac 222 ms), LOCATE with 17 output tokens about 1.0-1.4 s (Mac 378 ms), the ORDER audio turn about 1.5-2.5 s on llama.cpp (the audio encoder on the Orin is unmeasured; 3-6 s if on LiteRT-LM CPU), so speech-end to robot reply about 2.5-4 s. Part B's tighter figures (0.3-0.45 s gates, 0.8-1.5 s ORDER) are the optimistic end; design the cover (status light plus a spoken "un momento") for 4 s and let Monday's table set the real budget. DEPLOY.md's E4B expectation table (20 generated tokens in 2-5 s) is the pessimistic end from before the latency study. Every call shares one byte-identical system prompt and tools array so the cached prefix stays warm; the per-call question goes after the image, as the harness showed it must.

### A5. Hardware to order today

| Item | Price | Note |
| --- | --- | --- |
| DJI Mic Mini 2-TX kit with USB-C receiver (the handheld "talking stick") | ~$170 | Must enumerate as a USB audio device on L4T (`arecord -l`); buy a second brand as insurance |
| Hollyland Lark M2 (second wireless brand) | ~$130 | Linux UAC compliance is untested for both |
| Wired USB handheld mic (Samson Q2U) + 5 m extension | ~$80 | Bench fallback if the wireless link drops twice |
| USB HID arcade push-to-talk button | ~$25 | Push-to-talk is the only listening mode in a 100-person house |
| Creative Pebble V3 USB speaker | ~$40 | Bench voice; on stage the same WAVs play from the laptop into the house PA |
| USB RGB status light (blink(1) class) | ~$30 | Brain state on the table; the head LED stays with the firmware so the spotter can read it |
| 15-inch portable USB-C monitor | ~$100 | The brain view at the bench |
| USB-C PD power bank (100 W) + powered USB-C hub, 10 m Cat6, 10 m 3.5 mm cable, HDMI/USB-C adapters, second cable set | ~$180 | Micro Center Santa Clara, Monday |
| Folding table, 3-slot can rack jig referenced to the stand frame (12 cm pitch), 12 cans, saturated silicone koozies, matte backdrop | ~$100 | The jig travels with the stand, so bench calibration survives the move to the stage |
| 1.2 x 1.2 m MDF board | ~$40 | Only if the venue floor is carpet (ask the organizers today) |
| Gaffer and floor tape, power strip, printed cards, "camera on" sign | ~$60 | |
| Second G1 battery | unverified | Hard requirement: email Unitree, a reseller, a Bay Area G1 owner or a rental firm today; Monday 20:00 deadline, else the bench runs in two 75-minute windows around a 90-minute charge |
| Logitech C920 + clamp | ~$60 | Contingency only, if the head camera cannot see the rack and the lifted can (the D435i colour stream is a plain V4L2 node; no librealsense build needed) |
| GL.iNet Beryl AX travel router | ~$90 | Optional backup AP; the MT7612U USB AP is the default, 5 GHz, no uplink |

Total about $950-1,050 without the battery.

### A6. Schedule and gates

- Sunday Oct 18 (robot offline): order hardware; email the organizers (load-in 08:30, stage HDMI and PA, floor surface, demo length, tethered laptop, stacking, whether a LiteRT-LM component beside llama.cpp counts, judges' languages, another G1 team on site); battery emails; recruit native speakers; approve downloads. Mac spike: the exact ORDER payload (system + tools, instruction text then `input_audio` last, thinking off, greedy) on 20 rotated clips in en/zh/es; pass is 18/20 correct `order()` calls. Gate 0 at 20:00: plan B (audio-only tool turn, then vision turns) works on the Mac, or plan C (sherpa-onnx Whisper in front of Gemma) is the design.
- Monday Oct 19 (robot on): 09:00 toolchain check on PC2 (`nvcc`, `nvpmodel -q`, free disk and RAM), native llama.cpp CUDA sm_87 build or the pinned JetPack-6 CUDA container; harness payloads and 3 s / 8 s WAVs; Orin latency table v1; audio verdict by 14:00. Tier 1 spike: `pip install litert-lm litert-lm-api`, the ORDER payload through LiteRT-LM on CPU then GPU, p50 and RSS recorded. 15:00 robot block in the stand: software version, `GetFsmId()==500`, `ServiceSwitch("g1_arm_example", False)` timed, arm controller holds a pose, hands open/close with `q` and `tau_est` logged while a can is pulled, factory assistant put to sleep and verified, speaker and mic tests at 2 m with 75 dB crowd playback. Gate 1 at 20:00: audio plan A/B or C; LiteRT tier in or out; release signal; arm ownership; battery sourced.
- Tuesday Oct 20: rack height from the loaded pose; record reach-to-slot x3, present and home with `xr_teleoperate --arm G1_23 --ee brainco --motion --record` in FSM 500 in the stand (never without `--motion`: that path enters debug mode and kills the sport service until reboot); replay through the same controller class and gains; 20 picks per session; language table with native speakers on the real mic; camera opened as a V4L2 node with locked exposure; gates and LOCATE scored on 30 real frames; 2-hour `tegrastats` soak with everything loaded. Gate 2 at 20:00: promised languages, mic, camera, story A/B or C, release rule, pick trend.
- Wednesday Oct 21: full loop end to end on the stand by 12:00; recoveries (missing colour, grasp fail then retry then assisted, no hand in 8 s, `unsure`, can swap); two 10-trial pick sessions; ten bench loops; backup video v1. Gate 3 at 20:00: pick tier (rack at 8/10 in two consecutive sessions, else human-assisted and labelled), release gate at 28/30, wave kept or cut, final language set.
- Thursday Oct 22: 30 logged trials with per-stage counts; RF test with everything radiating; 10-minute run unplugged on the power bank; judge-interrupt drill; strangers ordering in their languages; numbers board; backup video v2 (90 s, captioned); two dress rehearsals with crowd noise. Tier 3 walk trials if gated in.
- Friday Oct 23: finish the 30 trials; 12:00 code freeze (git tag, `demo_mode` flag disables anything not in the success table); transport rehearsal against a stopwatch (packed case to first loop in 60 minutes, bench-to-stage move under 10 minutes); five timed stage rehearsals, drills (L2+B hang, server restart with warm-up under 60 s, PC2 reboot with preflight); fill the number slots in the script from the final Orin table; load the car.
- Saturday Oct 24: 08:00 load with two lifters; 60-minute checklist; dry run before 10:00; bench loops at :00/:20/:40 from 10:00 to 15:00 with the robot in Damp in the stand between groups; battery swaps 12:00 and 14:00; stage as rehearsed; nobody touches code.

Roles for a team of unknown skills: R1 owner (robot, safety, remote, trajectories, go/no-go), R2 Linux/CMake (Orin build, server, prompts, tables, Tier 1), R3 Python/web (brain.py, ears, mouth, brain view, preflight, narrative), R4 no technical skill needed (orders, organizer liaison, battery, props, transport, filming, timing). Android developer, if any, owns Tier 2 only. One robot and one GPU serialize everything: 2-hour blocks, never two inference jobs at once.

### A7. The ten unknowns, in retirement order

1. Does the Mac server emit a correct `order()` from a spoken clip with the exact demo payload (Sunday, 1 h)?
2. RESOLVED Sunday night: Gemma 4 audio works on the Orin under llama.cpp CUDA (commit a2878d30d, sm_87): 10/10 correct order() calls on can clips in en/zh/es, 0.73 s p50 at MAXN (1.64 s at 15 W), image+audio+tools in one request also works (0.98 s), two-word answer 0.22 s. See hackathon/spikes/2026-10-18-orin-sunday.md. Original question: does Gemma 4 audio work on the Orin under llama.cpp CUDA (Monday, decides plan A/B vs C)? NVIDIA's Jetson page flags an undated "audio issue with E2B under llama.cpp"; a community Orin Nano Super project runs it fine on a recent build. Fallbacks: `--no-mmproj-offload`, the Q8_0 mmproj, the pinned CUDA container, then sherpa-onnx Whisper. Follow DEPLOY.md's deployment order for this build: record the baseline first (model and projector hashes, llama.cpp commit, CUDA and JetPack versions, build flags, resolved server properties, power mode, clocks), build Release CUDA for `CMAKE_CUDA_ARCHITECTURES=87` and verify the model and projector are on the GPU, one slot, context sized from the measured RAM with room for robot services and no swap, check CUDA graphs and flash attention are actually on, then cheap A/B tests (prefill microbatch 128/256/512, flash-attention modes, power mode and clocks under `tegrastats`), and MTP with the cached E2B drafter (`mtp-gemma-4-E2B-it.gguf`) only after the plain numbers exist. Report what DEPLOY.md asks for: vision and prefill time, first-token time, complete valid-call p50 and p95, decode rate, peak shared RAM, temperature, clocks and power, with startup, warm-server fresh-frame and exact-image cache reuse kept separate, and robot services running.
3. Does the ORDER turn run on LiteRT-LM on PC2 within 2.5 s (Monday, Tier 1)?
4. Is `rt/arm_sdk` the sole arm owner with `g1_arm_example` switched off, and what is the pose jump at the switch (Monday)?
5. Does a judge pulling the can move the BrainCo `q`/`tau_est` trace enough for a release threshold, or do we release on two consecutive vision yes answers plus "take it" (Monday)?
6. Which mic gives usable speech at 2 m with crowd noise, and does it enumerate on L4T (Monday)?
7. Can the head camera see the rack at hand height and the lifted can from the stand (Tuesday 09:00)?
8. RESOLVED Monday morning (office): see-and-grab works on the robot with a different mechanism than planned. The can's 3D position comes from the head camera's box (YOLOE or Gemma) plus RealSense depth; the left arm goes through g1-fetch IK with a raise-first path, a lateral pre-grasp 10 cm beside the can, two measured-position corrections, a 1 cm-step slide that stops on contact, and the thumb-first staged grasp; the one calibration needed was the palm's forward offset (9.6 cm, found by a jog the owner watched). Six grasps in a row followed (trials 5-9 on slim and standard cans, then a full voice run: 'purple' heard by Gemma from the webcam mic in 0.26 s, the purple can boxed by Gemma and matched to YOLOE among two cans, grasped, lifted, offered). The can's diameter is classified from the box width and depth. Details in hackathon/spikes/2026-10-19-office-grab.md. Original question: does a teleop-recorded reach replay to the slot with a 0.37 kg can at 8/10?
9. Memory and thermals with everything loaded: llama-server at most 6 GB, 2.5 GB free after a 2-hour soak (Tuesday).
10. Does `LocoClient.Move` work on our firmware in FSM 500 (Monday, 15 min; only matters for Tier 3)? A G1 EDU+ on software 1.5.3 silently ignored it in walk-run mode.

### A8. Top risks

- The headline "no speech recognizer" depends on Orin audio (unknown 2). Plan C keeps the same demo with sherpa-onnx Whisper in front of Gemma and says so on the slide.
- No autonomous grasp has ever run on this robot. Human-assisted pick ("would you put it in my hand?") is rehearsed as a labelled tier; the handover stays autonomous either way.
- A fall with BrainCo hands fitted breaks fingers and ends the demo. The stand, the taped remote, and "arms extend only in locked stand" exist for this.
- Loud room: push-to-talk only, 8 s clips, confirmation line with a cancel window, enum validation, only verified languages promised.
- Battery: one pack is about 2 h with the GPU busy; a second pack is a hard requirement.
- No-cloud proof must cover the whole robot: PC1 runs Unitree's cloud client when the robot is in Wi-Fi mode; Tailscale must be stopped and disabled; the factory assistant must be asleep. The preflight prints the evidence on the brain view before the first judge.

### A9. Alternatives the panel considered

Lead Me / Lantern (a blindfolded judge guided by the robot): the most quotable clip and the investor judge's favourite, but it depends on the unverified walking path and puts a person on a biped whose e-stop is a fall. Show Me Once / Apprentice (teach a chore through the robot's arms via XR teleop, Gemma labels it, anyone runs it by voice): the robotics judge's favourite and the safest mechanically, but teleop in view is discounted on sight by this crowd and Gemma becomes a label on a macro recorder; its record-and-replay machinery is exactly how our reach is built. Show Once (one-shot chore imitation from video): the organizers' own sentence, but open VLMs score near zero at it and it needs thinking-on plan turns (6-12 s on the Orin). The Robot That Remembers / Reunite (EmbeddingGemma 2 memory via LiteRT-LM): the strongest LiteRT claim but a modest physical act and a robot filming attendees all day. Pixel Is the Brain: the only concept touching the $15k pool; dropped by the owner (no phone, not worth the trouble). Polyglot Porter (lobby concierge reading signage): the Pepper shape nobody films; its grace window and ask-back grammar are in our loop.

### A11. Stand or free-standing (your question)

The red team made the protective stand the bench default for four reasons, and it is a trade-off you should decide, not an assumption:

1. Safety. The only software e-stop is L2+B (damp), which makes a standing G1 collapse. During a handover the judge is inside the arm span, and a fall with BrainCo hands fitted breaks fingers and ends the demo. Clipped into the stand with the feet on the floor in locked stand (FSM 500) and a few centimetres of strap slack, L2+B means the robot hangs instead of falling, and Unitree's own arm_sdk routine says to test arm motions suspended in locked stand.
2. Battery. With one pack rated about 2 h (less with the GPU busy) and judging from 10:00 to 15:00 plus the stage, the stand lets the robot sit in Damp between judge groups at near-zero draw and stand up only at :00, :20 and :40. Free-standing, the balance controller runs all day. The charger helps only if the pack can come out and charge (about 2 h) while the robot is idle, which means a 90-minute gap in the bench day unless a second pack is found.
3. Calibration and the move to the stage. The can rack is a jig referenced to the stand frame, so the recorded reach stays valid after wheeling the stand to the stage.
4. Unitree warns against squat or lying boot with hands fitted, so the stand is also the easiest way to boot and park the robot safely in a crowd.

Free-standing is a legitimate choice if you accept the rules: judges always on the far side of the table, outside arm reach; the handover across the table edge; the spotter holds the remote on L2+B and never drives; arms extend only in locked stand, never while stepping; no pull-based release (vision gate plus "take it"); and a floor plan for battery (a second pack, or two bench windows around a charge). It looks more like a robot and less like a lab rig, and it keeps the stage walk (Tier 3) possible. If you do not own the stand or it will not travel, say so and the plan switches to these rules.

### A12. Verified on the robot, Sunday evening Oct 18

- PC2: JetPack 6.2 (L4T 36.4.3), CUDA 12.6 runtime and TensorRT 10.3 present but no compiler; a root-free CUDA 12.6 toolkit (nvcc, cuBLAS headers, CUB) is extracted under `~/cuda-user` (1.7 GB) and llama.cpp is being built from commit a2878d30d (the Mac benchmark build) with `-DCMAKE_CUDA_ARCHITECTURES=87`. Power mode is 15 W with 4 of 8 cores; modes are MAXN, 10 W, 15 W, 25 W; changing it needs a PC2 reboot. 13 GB RAM free, 1.7 TB NVMe free.
- Model files (E2B UD-Q4_K_XL, mmproj-BF16 with the audio encoder, MTP drafter) are at `~/models/gemma4` on PC2; the harness benchmark scripts and the 480x336 image set are at `~/harness/bench`; probe scripts at `~/spike`.
- Your `g1-fetch` project on PC2 already provides: LocoClient wrapper with the real velocity deadband (0.14 m/s minimum), arm_sdk streamer with pinocchio IK for the 5-DoF arms, BrainCo hand control, RealSense via pip `pyrealsense2` (stop `teleimager-realsense-webrtc.service` first), a read-only `cli check` preflight, TTS status through `AudioClient`, and an OpenAI-compatible yes/no VLM verifier that can point straight at llama-server. The Oct 16 session opened a fridge door with a hook grasp; reach-in was the open problem. Part B's arm plan should reuse this stack rather than xr_teleoperate's controller. Hard rules from its learnings: DDS interface is `enP8p1s0`, `mode_machine` is 4, poll `rt/lowstate` instead of a 500 Hz callback, warm the detector before opening the camera, never `pkill -f` a pattern that matches your own shell.
- Audio: `AudioClient.TtsMaker` (speaker 1, English) played through the robot speaker. The 4-mic multicast stream (239.168.123.161:5555, 5120-byte packets of 16 kHz mono) and the local recognizer on `rt/audio_msg` (SenseVoice-style tags, azimuth, language) only came alive after PC1 was connected to the internet; a 15.8 s capture was transcribed correctly in Mandarin by Gemma on the Orin. Monday must confirm the stream survives PC1 going offline (no-cloud rule). Owner's decision Sunday night: onboard array first; a Logitech C922 webcam on PC2 (`/dev/video6`, ALSA `plughw:2,0`) is the backup mic and a second camera, both verified with Gemma on the Orin.
- Vendor preset arm actions returned status 3102 in the owner's own preflight two days ago, which supports Part B's choice of `rt/arm_sdk` as the only arm path.
- Robot-side checks done Sunday night in the stand (FSM 500): the arm-action service switches off and on in 0.82 s with no pose jump off and a 0.08 rad settle on; g1-fetch's arm streamer on `rt/arm_sdk` holds a pose within 0.02 rad and a 0.3 rad raise settles within 0.034 rad, so it is the arm path (toggle the service once at preflight, once at shutdown). Hands: the right thumb motor is faulty, so the can hand is the LEFT; grasp in three stages, confirmed by the owner to hold a can firmly: thumb-aux to 0.8 with the thumb open `[0, 0.8, 0, 0, 0, 0]` for 1 s, fingers `[0, 0.8, 0.9, 0.9, 0.9, 0.9]` for 1.5 s, then the thumb `[0.9, 0.8, 0.9, 0.9, 0.9, 0.9]`; fingers stall near 0.47 on a can versus 0.90 empty, which is the grasp-verified signal; a left-arm reach pose [-0.5, 0.25, 0, 0.6, 0] held through arm_sdk with a 0.07 rad gravity sag at the shoulder (hand 0.34 m forward of the arm base, about 85 cm above the floor by tape); the rack puts the can's mid-height at that hand height, i.e. the can's base about 79 cm up for a 12 cm can, roughly 35 cm in front of the chest and 20 cm left of centre, and the pose is re-recorded on the real rack; `tau_est` carries no pull signal, so release is the vision gate plus "take it" (staged release: fingers first, thumb last). Details in hackathon/spikes/2026-10-18-orin-sunday.md.

### A13. Lessons from the harness history (latency-study and earlier phases)

1. Valid syntax is not a correct decision. Every one of 99 early requests produced a valid native tool call while the actions were often wrong; score the decision, never the protocol (RESULTS.md, FORMAT_RESULTS.md). The brain view and the success table exist for this.
2. Thinking does not fit a control loop. Brief thinking cut reasoning tokens by a third but stayed at 4-9 s with a 16 s tail, reasoning was 94% of generated tokens, and budgets under 1 s gave nothing; with thinking off a "plan the actions" prompt collapsed to [forward] every time (THINKING_RESULTS.md, LATENCY_RESULTS.md). Hence: thinking off, one direct perception question per frame, sequencing in code.
3. The interface shapes behaviour. No-argument atomic tools made the model hand off after one action; a list-valued plan tool completed sequences; a tool whose argument is the percept (face_target(position), now order(item, language)) is the fast, accurate shape. The template sorts arguments alphabetically and the grammar does not enforce enums, so validate client-side and treat "no call" as unsure.
4. Prompt placement decides accuracy. The question goes after the image: in the system turn it fell from 99% to 32%, before the image from 99% to 85%. Only the system text and tools are cacheable, so keep them byte-identical across every call type.
5. Token economics on a short request: prompt processing is about 90% of it; each output token costs about 9 ms on the Mac and 27 ms on the Orin at MAXN; 480x336 is the 70-token floor and skips the server's own resize; assistant prefill cut box detection from 42 to 17 tokens; the two-word answer is 3 tokens. Streaming tool-call deltas arrive early (253 of 324 ms), so the client can react before the call closes.
6. Measurement hygiene, or the numbers lie: never time repeated identical images (KV reuse fakes latencies), run one slot with --cache-ram 0, seed every request when sampling, use greedy for control (temperature 1 costs 6-8 points on word and tool answers), report n and per-class counts, and keep Mac and Orin numbers apart. --swa-full with -c 4096 saves 35-55 ms; --ctx-checkpoints 0 loses the prefix cache; send a warm-up request after start (the first image request was 2x slower).
7. Absent targets are hallucinated by fast prompts (none chosen 6/14 times; a yes/no gate alone 12/14 with wide-view false positives), so the demo's honest negative needs a presence gate asked twice, a superset enum and a code branch, and must be rehearsed as a feature.
8. Box detection is the robust percept (100%, no left/right flips, immune to temperature); face_target flipped left for right one way only, and one-word answers miss at label boundaries. Use boxes where a wrong side is costly, one word for gates.
9. Three generated images times seeds measure sampling variation, not generalization; permissive rubrics hid unnecessary turns. Score gates on real frames at the venue and keep the misses in the table.
10. From the chunk proposal: a plan is a set of commitments with feedback, a command acknowledgement is not physical success, elapsed time is never a release condition, and reliability compounds (0.95^8 = 0.66), so recovery and skill quality matter more than planner polish. The brain is a state machine with verified gates and an assisted-pick fallback for that reason.
11. From the deployment notes: record the baseline (hashes, commit, flags, power mode, clocks), one slot, cheap flag A/Bs, MTP only after plain numbers exist; E4B was 1.6x slower with no planning gain; a JetPack upgrade is compatibility, not speed. MTP is still an open A/B for the 21-token tool call on the Orin; the two-word path makes it moot.

### A14. Judge talk points

- One model is the whole cognitive loop, on the robot: Gemma 4 E2B hears the guest natively (no speech recognizer), sees the rack, and decides; our code does geometry, sequencing and safety. Nothing leaves the Jetson in the robot's chest.
- Measured on this robot this week, not on a laptop: 320 ms for a one-word perception gate, 772 ms for box detection with 1.7% horizontal error, 0.73 s from the end of your sentence to a validated order() call (0.22 s in the two-word format), 27 ms per output token, Mac-identical accuracy (99%, 97%, 100% on 78 frames). 5.7 GB RAM, 63 C under sustained load.
- The finding behind the design: a 2B model without thinking perceives well but cannot compose a percept into a plan (every planning prompt collapsed to "forward"; sub-second reasoning budgets gave nothing). So we ask one grounded question per frame and compose in code. Gemma supplies percepts and intent; code supplies geometry.
- Why it is sub-second: thinking off, the question placed after the image (moving it earlier costs up to 67 points), 70-token frames at the server's floor, one byte-identical cached prefix across all call types, and as few output tokens as the answer allows.
- Native function calling as the carrier of meaning: order(item, language) with enums validated on our side, because the tool grammar does not enforce them and the template reorders arguments.
- Honest negatives are a feature we measured for: fast prompts hallucinate an absent target, so the loop gates presence twice and says "I don't see a blue can; I see red and green" instead of inventing one.
- Multilingual by the model, not by a pipeline: the same audio turn returns the language it heard; Gemma 4's 305M-parameter audio conformer takes 16 kHz clips at 25 tokens per second of speech. Only languages verified with native speakers are promised, with n on the slide.
- The robot side: Unitree's balance controller keeps the G1 standing while our 50 Hz arm_sdk streamer owns the arms (service hand-off in 0.8 s, pose held within 0.02 rad); the reach is a recorded trajectory replayed to the slot Gemma chose; the BrainCo hand grasps in three stages (thumb into opposition, fingers, thumb lock) and verifies the grasp by finger stall at 0.47 versus 0.90 on an empty hand; release waits for Gemma to see the guest's hand plus a spoken "take it", never a timer, because the hand's torque estimate carries no pull signal.
- Audio capture: the G1's own 4-mic array streams 160 ms packets straight into Gemma; the local recognizer's direction-of-arrival is a free turn-to-speaker cue; a USB webcam mic is the backup.
- Transparency: every decision is on screen with its question, answer, milliseconds and a provenance tag (Gemma decision versus recorded skill); the success table has n and includes the misses; the no-cloud proof is live (no default route, Wi-Fi off, the robot's own PC1 offline, the factory assistant asleep).
- Deployment story: a root-free CUDA 12.6 toolkit on the Jetson, llama.cpp built natively for sm_87 at the same commit as the Mac benchmark for apples-to-apples numbers, and a 2.3x gain from the 15 W mode to MAXN.
- We evaluated LiteRT-LM on the same board honestly: it runs on the CPU (3 s per spoken order with 8 threads), the GPU path is not available on Jetson, so the demo stays on llama.cpp CUDA; the numbers are on the slide.
- What we deliberately did not do, and why: no learned policy, no thinking mode, no teleoperation during the demo, no cloud, no walking in a crowded room.
- The road ahead: the same stack opened a fridge door with a hook grasp on Oct 16; the next skill is the door, then the fridge fetch end to end.

### A10. Today's to-do

1. Answer A0.
2. Place the A5 orders (mics, button, speaker, light, monitor, props); battery emails.
3. Email the organizers the A6 Sunday questions; decide on Arm Create Monday.
4. Recruit two native speakers per language for Tuesday.
5. Copy the cached E2B GGUF and `mmproj-BF16.gguf` to PC2 when the robot is on; downloads are pre-approved.
6. Run the Sunday Mac spike (unknown 1).

## Part B. Detailed build plan (revised after the red team)

Editor's note: Part A overrides Part B in two places. Part B states "no LiteRT claim"; Part A keeps LiteRT-LM as a gated backup for the voice turn only (A3 Tier 1), cut at a dated gate if it misses. Part B's "Pixel not bought" stands (the owner dropped the Android tier). Part B states "no walking at all on Oct 24"; Part A keeps that as the default and allows a stage walk only under the Tier 3 gate. Everything else in Part B (demo script, architecture, tool API, no-cloud proof, hardware, schedule, spikes, risk register, cuts, questions, alternatives, red-team change log) is the working plan.

### 1. Executive summary

1. We build **Any Language, One Can**: a Unitree G1 drinks host. A judge holds a push-to-talk stick and orders a can in their own language; Gemma 4 E2B on the robot's Orin NX hears the clip natively (no speech recognizer) and emits `order(item, language)`; a second Gemma call finds that can on the rack (`box_2d`); the robot confirms in the judge's language, picks the can with a recorded `rt/arm_sdk` reach, and opens its hand when Gemma sees the judge's hand on the can. When the can is not there, it says so.
2. One model, one runtime, one arm owner. llama.cpp CUDA serves every call (order, gates, box) from one identical cached prefix. `rt/arm_sdk` through xr_teleoperate's `G1_23_ArmController(motion_mode=True)` owns the arms all day; the factory arm service `g1_arm_example` is switched off at preflight and back on at shutdown. Piper speaks. brain.py sequences and owns safety.
3. Scope was cut today, not at a gate: no memory tier, no LiteRT claim, no direction-of-arrival, no walking, no hip holster, no preset gestures, languages en/zh/es plus any language with two native speakers on call Tuesday. Rough budget after the cuts is about 100 engineering hours over three streams; robot and GPU time are scheduled in 2-hour blocks because one robot and one GPU serialize everything.
4. The robot stays clipped into its protective stand the whole day: feet on the floor in locked stand (FSM 500), strap slack, casters locked, so L2+B means hang, not fall. The can is handed across the table edge. The stand is the dolly to the stage and the rack jig is referenced to the stand frame, so the calibration travels.
5. Target: Track 2 only. Honest estimate: P(the loop runs at some tier on Oct 23) about 0.8; P(1st | runs) about 0.35; EV about $3.3k. No LiteRT, Pixel or hardware awards.
6. Risk one: Gemma 4 audio on the Orin under llama.cpp CUDA is unverified. Monday 09:00 toolchain check, native build (or the pinned JetPack-6 CUDA container), verdict by 14:00. Plan B (audio-only tool turn, then vision turns) is already the design default; plan A (image in the same turn) is a config flag; plan C (sherpa-onnx Whisper in front of Gemma) has its own written story and language table.
7. Risk two: no autonomous grasp has run on this robot. Teleop-recorded trajectories with `--motion` in FSM 500, replayed by the same controller class and gains that recorded them, rack height set from the loaded pose, 20-trial gates on the stand, human-assisted pick as the labelled fallback.
8. Risk three: the release signal. Monday's `q`/`tau_est` trace decides whether a pull threshold exists; otherwise release on two consecutive vision yes answers plus a spoken "take it", opening to 0.4 first.
9. Risk four: the day itself. Second battery is a hard requirement with a Monday deadline; 60-minute setup checklist timed Friday from a packed case; bench-to-stage move timed under 10 minutes; no-cloud proof covering PC1 and the factory voice service; the R3 remote taped down to L2 and B.
10. Code freeze Friday 12:00. The stage script carries typed number slots filled from the final Orin table. 30 logged trials Thursday to Friday morning. A 90-second captioned backup video on the laptop and a phone with a rehearsed hardware-fault branch.

### 2. The pitch

**Project name:** Any Language, One Can.

**One-liner (plans A/B):** Order a drink in your own language; one Gemma 4 model on the robot hears you, finds the can, hands it to you, and says so when it can't.

**Second sentence:** Everything runs on the Jetson in the robot's chest with no network, and every number on the slide was measured on this robot this week, misses included.

**The stage opener (about 90 s; `__` slots are filled Friday by R4 from the final Orin table; nothing is spoken that is not on the slide):**
"[A true two-sentence anecdote from a team member about someone who could not ask for a drink in a room full of them. If nobody has one, the opener is one word: Imagine.] [beat] This is a Unitree G1. Its brain is Gemma 4 E2B, the two-billion-effective-parameter model, on the Jetson in its chest. Nothing in this loop has an internet connection: here is the unplugged cable, here is the robot's own network page with Wi-Fi off, here is `ip route` with no default. The same model hears you in your language, no speech recognizer in between, and calls one function: order. Then it looks at the rack and finds your can. Our code does what code is good at: reaching, closing a hand, not dropping you. [beat] Watch the screen: every decision shows up with its latency, `__` s to understand you, `__` ms per look. The reach is a recorded trajectory replayed to the slot Gemma chose; the hand closes and opens on what the sensors and Gemma see; nobody teleoperates during the demo. The person holding the remote is a safety spotter; he never drives. [beat] Who is thirsty? Any of these languages." (the verified list is on screen)

**Two sentences for the winners post:** A Unitree G1 that takes your drink order in your own language: Gemma 4 E2B on the robot's Jetson hears the audio natively, emits one `order()` tool call, finds the can on the rack with `box_2d`, and the robot picks it and releases it only when Gemma sees your hand on it. No speech recognizer, no cloud, Orin-measured latencies on the slide, and it says "I don't see a blue can" instead of inventing one.

**Plan C story (written now, chosen only if Monday's Orin audio verdict is C):** Name unchanged. One-liner: "Order a drink in your own language; an on-device speech recognizer hears you, Gemma 4 on the robot decides, finds the can, hands it to you, and says so when it can't." Slide line: "sherpa-onnx Whisper ASR → Gemma 4 decides, finds, gates." Language table: the same en/zh/es native clips scored through Whisper small int8 → text → the same `order()` tool turn, item and language scored separately. The Mac audio result appears only as a slide line, "Gemma 4 hears natively on the Mac, not yet on the robot", and only if the organizers allow a tethered Mac in writing; it is never performed. On stage we say plainly that this is the 2025 Jetson-prize shape (ASR, Gemma, Piper) on a humanoid with a vision-gated handover.

### 3. Demo script

**Setup (bench and stage).** The robot is clipped into its protective stand, feet on the floor in locked stand (FSM 500), strap with a few centimetres of slack, the four casters locked. A folding table stands in front of the stand; on it a 3-slot can rack (12 cm pitch, saturated koozies, matte backdrop board) built as a jig referenced to the stand frame, at the hand height measured from the loaded pose. Judges stand on the far side of the table, outside the stand footprint. The bench monitor shows the brain view: live 480x336 head-camera frame, the question, the answer or tool-call JSON, milliseconds, state, provenance tag (`[Gemma decision]` or `[recorded skill: teleop replay]`), the autonomous success counter, and the radios panel (`ip -br link`, `ip route`, the photo of the robot's network page with Wi-Fi off). A USB status light on the table shows the brain state (legend card); the head LED is left to the firmware (blue normal, orange damped, red abnormal) so the spotter can read it. A privacy card is read first: "The camera is analysed live and shown on this screen. Frames that decide a gate are logged for the success table and deleted before we leave. No audio is stored. The factory voice assistant is asleep." A "camera on" sign sits on the table.

**Bench loop (about 2 minutes, repeats all day, resumable from any state; the presenter picks segment order per group: order and handover first, the planted negative and the can swap when a judge asks or time allows).**

- 0:00 Presenter: "Take the stick, hold the button, order one of those cans in any language. Swap two cans first if you like." Judge speaks (push-to-talk, VAD cut, 8 s cap). Status light: listening.
- 0:06 UNDERSTAND: one audio-only request (instruction text, audio part last, tools) returns `order(item=green_can, language=es)` on screen with ms. CONFIRM: Piper says the templated line in Spanish if `es` is in the verified set ("La lata verde. Ya voy."), else the English line with the item name. Grace window: end of the confirmation speech plus 3 s with a visible countdown; a button press or "no" cancels with no inference.
- 0:12 LOCATE: presence gate on a fresh rack frame ("Is there a green can on the rack? yes/no"), then `box_2d` for the green can with assistant prefill. The slot is the box centre against the three taped slot bands; a box outside the rack band or of implausible width is `none`. The box is drawn on the frame.
- 0:15 PICK `slot=2`: the recorded reach for that slot, replayed through `G1_23_ArmController(motion_mode=True)` on `rt/arm_sdk`; BrainCo right hand to 0.7; lift to the chest. VERIFY: finger stall on `rt/brainco/right/state` plus "Is the robot's hand holding a can? yes/no" (two consecutive answers). Both shown.
- 0:35 HANDOVER: present pose over the table edge; "Is a human hand holding the can? yes/no" at about 1 Hz on the full 70-token frame. On two consecutive yes answers (plus the pull threshold if Monday's trace found one), the robot says "take it", opens to 0.4, then fully; "Que la disfrutes." If no hand in 8 s: "I will hold it until you are ready," and the gate keeps running.
- 0:55 Participatory moment two: the judge swaps two cans and orders again; the brain view shows the new box and slot. The swap is a listed test with its own row on the numbers board, and judges are invited to run it.
- 1:15 Visible recovery: the judge orders a colour that is not on the rack (`blue_can` is a valid enum value). The presence gate answers no twice, LOCATE returns `none`, and the robot says "I don't see a blue can; I see red and green" (the colours it sees come from LOCATE calls on the other two colours). On a grasp failure (the "nudged slot", disclosed on the card, used only on request), VERIFY fails, the robot retries the slot once, then says "I could not grab it, would you put it in my hand?", opens the hand, closes on the stall plus the yes gate, and completes the handover.
- 1:40 Optional: `wave()` on request, a 2-keyframe pose through the same trajectory player, kept only if clean by Wednesday.
- 1:50 Numbers board handed to the judge on paper, with the verified-language list.

Between groups: Damp in the stand (the robot hangs a few centimetres) whenever the gap exceeds a few minutes; the robot stands at :00, :20 and :40 so judges come at known times; battery swaps at 12:00 and 14:00, each followed by the 5-minute preflight.

**Stage (3 minutes, stationary, robot in the stand, wheeled over on its casters). If the stage has steps or a rug, we perform at the bench and the judges walk over; this is agreed with the organizers this week, not on the day.**
- 0:00-0:25 Opener and the one slide.
- 0:25-0:55 A pre-agreed bilingual speaker (a teammate, or a judge who agreed backstage) orders in a verified language; the brain view is projected; the robot confirms in that language.
- 0:55-1:45 LOCATE on the projected frame, pick, handover at the table edge on the hand gate; the volunteer walks to the table.
- 1:45-2:20 A second volunteer orders the missing colour: the honest negative. If time allows, they swap two cans and reorder.
- 2:20-3:00 Numbers slide and the honest sentence: "Reach: one teleop-recorded trajectory replayed open-loop to the slot Gemma chose. Hand close and release: sensor- and Gemma-gated. Nobody teleoperates during the demo. Pick tier: rack, or human-assisted, as labelled."

**The one slide:** Orin-measured latency per call type with n (ORDER audio turn at 3 s and 8 s clips, presence gate, box LOCATE, hand gate, Piper, speech-end to robot reply); the language table (n per language, item and language fields scored separately, unverified languages listed as "not tested"); the success table (30 trials: hear, locate, pick, release, recovery, plus the swap-test row); what runs where (PC2: llama.cpp CUDA for E2B, Piper, brain.py; laptop: display and PA mirror only); the no-cloud evidence including "the robot's own computer PC1 has no uplink"; the battery plan.

### 4. Prize coverage map

| Award | What in our build qualifies | What else is needed | Honest probability (team estimate) |
| --- | --- | --- | --- |
| Track 2 Physical AI ($7.5k/$5k/$2.5k + Break Glass trophy) | Humanoid hear-see-decide-act loop, fully offline, native audio and tool calls, Gemma-chosen can, vision-gated handover, honest numbers, visible recovery, swap test | Ten clean loops in a row on Oct 23, the numbers board, the stand-based safety story told first | P(works at some tier) 0.8; P(1st given works) 0.35, 2nd 0.2, 3rd 0.15; EV about $3.3k |
| Best Use of LiteRT ($7.5k/$5k/$2.5k) | Nothing. Gemma 4 runs on llama.cpp; the EmbeddingGemma 2 memory tier is cut | Re-enters only if, by Mon 20:00, the organizers say in writing that a LiteRT-LM side component counts, a fourth teammate owns it end to end off the loop's slot, and it is done by Wed 20:00; we do not plan for it | Not targeted |
| Best in Show Android/Pixel ($15k + Pixel 11) | Nothing | A committed Android developer by Mon 20:00 plus a Pixel 11 order kiosk | Not targeted |
| Best Use of Pixel/TPU (2x Pixel 11) | Nothing | Same | Not targeted |
| Raspberry Pi, Coralboard, Qualcomm | Nothing | A side device nobody owns; VENTUNO Q cannot arrive; criteria unpublished | Not targeted |

Stacking: moot, the plan pays off on Track 2 alone. Ask in writing today anyway; the answer decides whether the LiteRT re-entry condition can ever fire.

### 5. Architecture

```
 judge's voice ──► DJI Mic Mini RX (UAC) ─┐   wired USB handheld mic (bench fallback) ─┐
 PTT arcade button (evdev) ───────────────┤                                            │
                                          ▼                                            ▼
 ┌──────────────────────── PC2: Jetson Orin NX 16 GB, JetPack 6.2 (L4T 36.4.3) ─────────────────────┐
 │ ears.py (arecord 16 kHz mono, webrtcvad, 8 s cap)   eyes.py (D435i colour V4L2 node via OpenCV, │
 │           │ clip                                     640x480 YUYV → 480x336 JPEG q85, locked     │
 │           ▼                                          exposure/WB; teleimager + mediamtx stopped)  │
 │  llama-server :8080  Gemma 4 E2B QAT UD-Q4_K_XL + mmproj-BF16 (vision + audio), CUDA sm_87     │
 │  --jinja -ngl 99 -np 1 --cache-ram 0 -c 4096 --swa-full; thinking off; greedy                   │
 │  ONE system message + ONE tools array on every call, question after the image/audio:            │
 │     ORDER: text + audio → order()/unsure()/wave()   GATE: one word   LOCATE: box_2d prefill     │
 │           │ validated tool call / one-word answer / box                                          │
 │           ▼                                                                                      │
 │  brain.py: IDLE→LISTEN→UNDERSTAND→CONFIRM→LOCATE→PICK→VERIFY→HANDOVER→RECOVER (+ demo_mode)     │
 │     ├ arm: G1_23_ArmController(motion_mode=True) on rt/arm_sdk 50 Hz; trajectory player         │
 │     │      (reach slot 1/2/3, present, home, wave keyframes); g1_arm_example OFF via            │
 │     │      RobotStateClient.ServiceSwitch at preflight, ON at shutdown                           │
 │     ├ hand: rt/brainco/right/cmd (0..1) + /state (q, tau_est at 100 Hz: stall, pull)            │
 │     ├ stand: LocoClient.GetFsmId()==500 asserted; no Move anywhere                               │
 │     ├ speak: Piper → Pebble V3 (ALSA); same pre-rendered WAVs mirrored on the laptop for the PA  │
 │     ├ light: USB status light on the table (head LED untouched)                                  │
 │     └ preflight.sh: whole-robot no-cloud, assistant asleep, services, devices, FSM, memory       │
 │  brainview :8000 (SSE) ──► laptop browser over the robot's MT7612U AP, 5 GHz, no uplink          │
 └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Component | Device | Model / runtime | Modality | Token budget | Expected on the Orin (projection until Monday's table; the stage script quotes nothing until then) |
| --- | --- | --- | --- | --- | --- |
| ORDER turn | PC2 GPU | Gemma 4 E2B via llama.cpp CUDA | instruction text + audio clip (last), native tools | shared prefix ~300 cached, 25 text, ≤200 audio (8 s at 25 tok/s), 15-20 output | 0.8-1.5 s; the audio encoder on Orin is unmeasured, so the cover (status light + "un momento") is budgeted at 2.5 s |
| Gates (presence, can-in-hand, hand-on-can) | PC2 GPU, same slot, same prefix | same | 480x336 frame (70 tokens) + one-word question after the image | shared prefix + 70 image + 25 question + 2 output | 0.3-0.45 s; the 280-token crop is used only if Tuesday's scoring proves it is needed (0.5-0.7 s) |
| LOCATE | PC2 GPU | same | `box_2d` with assistant prefill, stop on `]` | shared prefix + 70-140 image + 17 output | 0.65-0.9 s |
| Speech out | PC2 CPU | Piper (en, zh, es; hi only if verified) | 16 kHz mono int16, templated lines pre-rendered | n/a | 0.2-0.4 s |
| Sequencing and safety | PC2 CPU | brain.py (Python 3.10) | state machine, timeouts, watchdog | n/a | speech end to robot reply 1.5-2.5 s |

Memory budget: llama-server budgeted at 6 GB (E2B 2.62 GB + mmproj 0.99 GB + KV at `-c 4096` + CUDA workspace; the one on-Orin audio report ran in a 5.7 GiB GPU budget), Piper 0.2 GB, OpenCV 0.3 GB, Unitree services 2-3 GB. `teleimager-realsense-webrtc.service`, `teleimager-compat.service` and `mediamtx.service` are stopped for the demo (they also hold the camera node). The Tuesday 2-hour `tegrastats` soak must show at least 2.5 GB free.

**Tool API Gemma calls (enums validated client-side; the native grammar does not enforce them; arguments arrive alphabetically):**

| Tool | Arguments | Validation and effect |
| --- | --- | --- |
| `order` | `item`: enum `red_can`, `green_can`, `blue_can`, `other` (a superset of what is on the rack, so a missing colour reaches LOCATE and the honest negative); `language`: enum of Tuesday-verified languages plus `other` | `item=other` or invalid → amber ask-back in English ("Red, green or blue?"); valid item → confirmation in `language` if verified, else in English with the item name; then LOCATE |
| `unsure` | none | status light amber, "This room is loud, once more?" |
| `wave` | none | 2-keyframe pose through the trajectory player; kept only if clean Wednesday |

**Gates and LOCATE.** Every request carries the same system message and the same `tools` array, so the rendered prefix is byte-identical across ORDER, gate and box calls and stays warm on the single slot; the per-call question goes after the image (the harness showed accuracy collapses when it is moved earlier). Monday's table records the server `timings` on alternating call types to prove that only the image or audio and the question are fresh tokens. Gate questions: "Is there a green can on the rack? yes/no", "Is the robot's hand holding a can? yes/no", "Is a human hand holding the can? yes/no". A gate must give the same answer twice before the robot acts on a failure. LOCATE is "Detect the green can" with the `{"box_2d": [` prefill; the slot is computed in code from the box centre against the three slot bands calibrated Tuesday from the camera pose on the stand; the one-word alternative "Which slot holds the green can? 1/2/3/none" is scored on the same 30 frames and wins only if it beats the box.

**On-device, verifiably, for the whole robot (printed by preflight.sh on the brain view before the first judge):**
- PC2: `ip route` empty; WAN cable unplugged and held up; `sudo systemctl stop tailscaled && sudo systemctl disable tailscaled`; onboard Wi-Fi off (`nmcli radio wifi off`); the MT7612U AP on 5 GHz with no uplink; `ip neigh` on 192.168.123.0/24 showing only the robot's own hosts and no gateway.
- PC1: the robot's Wi-Fi mode set off (or AP-only) in the Unitree app, the network page photographed, the app disconnected and the phone's Bluetooth off; if PC1 credentials exist, a `ping -c1 8.8.8.8` from PC1 fails; otherwise the photo is the evidence. PC1 runs Unitree's cloud client (MQTT for OTA and WebRTC signalling) and performs network time sync whenever the robot is in Wi-Fi mode, so "PC2 has no default route" alone is not proof.
- Laptop and phone: on the robot's AP only; venue Wi-Fi and venue Ethernet never joined; phone in airplane mode with Wi-Fi on for the AP.
- Factory voice service: set to 关闭交互 (close interaction: program sleeps, stops recording) in the app before disconnecting; verified by speaking at the robot (no blue breathing LED) and by `rt/audio_msg` staying silent for 30 s; re-verified after every reboot and battery swap. The built-in ASR and TTS are documented as local offline (VuiClient doc), but they stay out of the loop: no `rt/audio_msg`, no `TtsMaker`, Piper only.
- The R3 remote: Select, A, X, Y and the right stick taped over (Select+Y/A/X fire preset gestures, Select+right stick drives the waist, L2+Select wakes the assistant, L1+L2 toggles its mode); the spotter's thumbs rest on L2 and B only; never L2+R2.
- The slide's no-cloud line reads: "PC2 has no route, PC1 has no uplink, the assistant is asleep, the remote is local."

### 6. Hardware

| Item | Owned / buy | Vendor, price | Order by |
| --- | --- | --- | --- |
| G1 EDU, BrainCo hands, D435i, Mid-360, R3 remote, protective stand (four lockable casters), suitcase, 54V 5A charger | owned | | |
| MacBook Pro M4 Pro (dashboard, Mac-side spikes), MT7612U USB AP | owned | | |
| DJI Mic Mini 2-TX kit with USB-C receiver (the handheld "talking stick"; stage mic) | buy | Amazon, ~$170 | Sun Oct 18, next-day |
| Hollyland Lark M2 (second wireless brand; UAC on L4T untested) | buy | Amazon, ~$130 | Sun Oct 18 |
| Wired USB handheld mic (e.g. Samson Q2U) + 5 m USB extension (bench default if the DJI drops twice) | buy | Amazon, ~$80 | Sun Oct 18 |
| USB HID arcade push-to-talk button | buy | Adafruit/Amazon, ~$25 | Sun Oct 18 |
| Creative Pebble V3 USB speaker (the 3 W onboard speaker loses the hall) | buy | Amazon/Micro Center, ~$40 | Sun Oct 18 |
| USB RGB status light (blink(1) or similar) | buy | Amazon, ~$30 | Sun Oct 18 |
| 15-inch portable USB-C monitor for the brain view | buy | Amazon, ~$100 | Sun Oct 18 |
| USB-C PD power bank (100 W class) + USB-C hub powered from it, 10 m Cat6, 10 m 3.5 mm cable, HDMI and USB-C adapters, a second complete cable set | buy | Micro Center Santa Clara, ~$180 | Mon pickup |
| Folding table, 3-slot rack jig (12 cm pitch, referenced to the stand frame), 12 cans, saturated silicone koozies, matte backdrop board | buy | Home Depot/Amazon, ~$100 | Sun-Mon |
| 1.2 x 1.2 m MDF or plywood board (only if the venue floor is carpet or rug) | buy | Home Depot, ~$40 | Mon, after the organizers answer |
| Gaffer and floor tape, power strip, printed cards, "camera on" sign | buy | ~$60 | Mon |
| Second G1 battery | **hard requirement** | Unitree, a reseller, a Bay Area G1 owner or a rental firm; confirmed Friday delivery or a loaner | Sun email, Mon calls, Mon 20:00 deadline |
| Logitech C920 + clamp | contingency only | Micro Center, ~$60 | Tue noon, only if the head camera FOV fails at 09:00 |
| GL.iNet Beryl AX travel router (backup AP, no uplink) | optional | ~$90 | Sun Oct 18 |
| Pixel 11 | not bought | | |

Removed from the original list: ReSpeaker XVF3800, 2x2 m foam mat, Kokoro, EmbeddingGemma 2 bundle, litert-lm wheels. Total about $950-1,050 without the battery.

Downloads (pre-approved by the owner on Sunday): llama.cpp master clone on PC2 (Monday), the pinned JetPack-6 CUDA container `b9066-r36.4.tegra-aarch64-cu129-22.04` only if `nvcc` is missing on PC2, Piper aarch64 binary and en/zh/es (hi) voices, sherpa-onnx plus Whisper small int8 (plan C), webrtcvad, and the ggml-org Q8_0 mmproj only if the BF16 projector fails audio on the Orin. No new Gemma 4 weights; the cached E2B GGUF and mmproj-BF16 are copied from the Mac over the wired link.

**Microphone decision (revised Sunday night by the owner):** the onboard 4-mic array first (its stream and local recognizer work; the recognizer's azimuth is a free turn-to-speaker cue), the C922 webcam mic as backup; push-to-talk gating stays the design in the hall; a handheld wireless mic is optional. **Speaker decision:** Pebble V3 over ALSA at the bench; on stage the same pre-rendered WAVs play from the laptop into the house PA (3.5 mm or HDMI), triggered by the brain view's `say <line_id>` event, with `AudioClient.PlayStream` as the last resort. **Camera decision:** the D435i colour stream is a plain V4L2 UVC node on PC2 (realsense-webrtc captures it without librealsense), so no pyrealsense2 build and no chest webcam by default; the head viewpoint is checked Tuesday 09:00 against the rack at hand height and the lifted can. **Pixel decision:** not bought.

### 7. Work plan Oct 18-24

Roles for a team whose skills are unknown: **R1** owner: robot, safety, remote, trajectories, go/no-go. **R2** anyone comfortable with Linux and CMake: Orin build, llama-server, prompts, latency and accuracy tables, soak. **R3** any web/Python developer: brain.py, ears/mouth/light, brain view, PTT, preflight.sh, demo narrative. **R4** no technical skill needed: orders, organizer liaison, battery, props, transport, filming, timing, story. With three people R4 folds into R1 and R3. Rule: one robot, one GPU. Robot blocks belong to R1, GPU blocks to R2 (R3 scores gates inside R2's soak block); R3 integrates against mocked skills until Tuesday 17:00; never two inference jobs at once.

**Sun Oct 18 (robot offline).** R2: spikes 1-2 on the Mac (plan-B ORDER payload, language table v0, prefix identity across call types). R3: brain.py skeleton in the plan-B shape against mocked skills; ears.py (PTT + webrtcvad); mouth.py (Piper lines pre-rendered); brain view v1; status light; preflight.sh v1. R1: rack jig design referenced to the stand frame; trajectory player design around `G1_23_ArmController`; recruit two native speakers each for en/zh/es for Tuesday; record 20 phone clips per language for spike 1. R4: orders; organizer email (load-in 08:30, stage HDMI input, PA and audio input, steps and floor surface, demo length, tethered laptop, another G1 team on site, privacy sign, which languages the judges speak, stacking); battery emails to Unitree, a reseller and Bay Area owners; registration; download approvals. **20:00 gate 0:** plan-B ORDER works on the Mac (≥18/20) or plan C is the design; the plan-C story reviewed.

**Mon Oct 19 (robot on).**
| Block | Robot (R1) | GPU (R2) | Integration (R3) | Logistics (R4) |
| --- | --- | --- | --- | --- |
| 08:30 | Robot on in the stand (zero torque), 3.6 GB model set copied to PC2 over the wired link, battery % logged, leave for Arm Create | | | |
| 09:00-11:00 | | Remote on PC2: `nvcc --version`, `dpkg -l \| grep -i cuda-toolkit`, `sudo nvpmodel -q`, `df -h`, `free -g`; llama.cpp master `cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87`, or the build inside the pinned container if no toolkit | brain.py against mocks | Battery calls |
| 11:00-13:00 | Arm Create with R4: phone video, three questions (scoring, judges' languages, tethered laptop) | `llama-server --jinja -ngl 99 -np 1 --cache-ram 0 -c 4096 --swa-full`; harness `face-tool-480x336` and `box-prefill-480x336` payloads; 3 s and 8 s WAVs; Sunday's ORDER payload. If audio aborts: `--no-mmproj-offload`, then the Q8_0 mmproj | PTT page on the AP; Pebble over ALSA | |
| 13:00-15:00 | | Orin table v1: cold vs warm, 70 vs 280 tokens, alternating call types with the shared prefix (`timings`); MTP and `-fa` A/B only if time. **14:00 audio verdict** | preflight.sh v2 (whole-robot checks) | |
| 15:00-17:00 | In the stand, FSM 500: `RobotStateClient.GetPkgVersion()`, `LocoClient.GetFsmId()==500`, `mode_machine==1`; `ServiceSwitch("g1_arm_example", False)` timed, arm pose jump on off and on; `G1_23_ArmController(motion_mode=True)` holds the pose, a 2-keyframe wave, `ctrl_dual_arm_go_home`; hands: brainco bridge, 0.0/0.7, `q` and `tau_est` at 100 Hz with a can placed, pulled, and nobody pulling; assistant 关闭交互 set and verified; `PlayStream` test; remote taped | | brain view on the robot's AP | Props |
| 17:00-19:00 | | Mics on the robot: `arecord -l` (DJI, Lark, wired); 30 s at 2 m with 75 dB crowd playback; through `order()`; mic choice | same | |
| **20:00 gate 1** | Orin audio verdict (A/B or C); release-signal verdict (pull threshold or vision-only); arm ownership working; second battery sourced or the two-window day plan adopted | | | |

**Tue Oct 20.**
| Block | Robot (R1) | GPU (R2) | Integration (R3) | Logistics (R4) |
| --- | --- | --- | --- | --- |
| 09:00-11:00 | Rack jig height set from the loaded pose (hand holding a can at the recorded pose) | Native speakers arrive; clip session set up | Camera: stop the three services; open the D435i node (`/dev/v4l/by-id/...`) with OpenCV 640x480 YUYV → 480x336; lock exposure and white balance with `v4l2-ctl`; confirm the rack and the lifted can are in frame from the head viewpoint; define slot bands and crop rectangles. If the FOV fails, R4 picks up a C920 at noon | |
| 11:00-13:00 | `xr_teleoperate --arm G1_23 --ee brainco --input-mode hand --motion --record` in FSM 500 in the stand: reach-to-slot x3, present, home (hand-authored 3 keyframes per slot through the same controller if no headset); convert to 50 Hz joint trajectories | Language table on the real mic: 10 clips per language per native speaker at 2 m with crowd playback; item and language scored separately | Trajectory player + hand timing in code | Crowd-noise playlist |
| 13:00-15:00 | Replay through `G1_23_ArmController(motion_mode=True)` (its gains, velocity clamp, `speed_gradual_max`); log commanded vs measured `q` with the can (sag); adjust the jig; 20 picks on the stand (session 1) | Finish the table; plan-C table on the same clips if the verdict was C | | |
| 15:00-17:00 | | 2-hour soak under `tegrastats` with everything loaded; the load is R3's scoring | Score presence, can-in-hand, hand-on-can, LOCATE box and the one-word slot question on 30 real frames each, crop vs full; battery % logged every minute from `rt/slam_info` `batteryPower` | Printed cards |
| 17:00-19:00 | 20 picks (session 2) | | End-to-end on the stand with real skills begins | |
| **20:00 gate 2** | Promised languages (≥9/10 on item and ≥9/10 on language per native speaker); mic; camera; story A/B or C; release rule; pick trend | | | |

**Wed Oct 21.** 09:00-12:00 R3+R1: full loop end-to-end on the stand; target one complete loop by 12:00. 12:00-14:00 R3: recoveries (missing colour, grasp fail → retry → assisted, no hand in 8 s, `unsure`, swap test), grace window, status light. 14:00-17:00 R1: rack pick, two 10-trial sessions inside the loop; R2: latency table v2 (Orin only) and gate re-scoring if the crop is needed; R4 films. 17:00-20:00: ten full bench loops; backup video v1. **20:00 gate 3:** pick tier (rack ≥8/10 in two consecutive sessions, else human-assisted, labelled); release gate ≥28/30; wave kept or cut; language set final.

**Thu Oct 22.** 09:00-13:00: logged trials 1-15 with per-stage counts. 13:00-15:00: RF test with everything radiating (AP on 5 GHz, DJI, laptop, phones), any "remote feedback data timeout" logged; 10-minute full-stack run unplugged on the power bank; judge-interrupt drill (resume from any state). 15:00-18:00: trials 16-30; strangers ordering in their languages; numbers board v1; backup video v2 (90 s, captioned, one clean run plus a recovery). 19:00-21:00: two dress rehearsals with crowd noise.

**Fri Oct 23.** 09:00-12:00: trials to complete the 30 if Thursday fell short; fixes only from the tables. **12:00 code freeze** (git tag; `demo_mode` disables everything not in the success table). 13:00-15:00: transport rehearsal: pack the case, carry it out, unpack and run the 60-minute setup checklist in another room against the stopwatch; the bench-to-stage move on casters timed under 10 minutes including the warm-up request and preflight. 15:00-18:00: five timed stage rehearsals ≤3:00 (one with the hardware-fault branch), ten bench loops, drills (L2+B hang, server restart with warm-up under 60 s, mic battery swap, PC2 reboot with preflight); R4 fills the number slots from the final Orin table. Evening: load the car; early night.

**Sat Oct 24.** 08:00 load with two lifters; 08:30 load-in if granted, 09:30 at the latest; the 60-minute checklist (stand assembled, casters locked, robot hung and stood: L2+B, L2+UP, lower, R2+A, wait; eth0 DDS; AP on a channel from an on-site scan; WAN unplugged; tailscaled stopped; services stopped; warm-up request; preflight.sh; gates re-scored on 10 frames in venue light); one dry run with a teammate before 10:00; bench loops at :00/:20/:40 from 10:00 to 15:00, Damp in the stand between groups, battery swaps at 12:00 and 14:00; stage as rehearsed; nobody touches code.

Rehearsal count: 30 logged trials, two dress rehearsals, one transport rehearsal, five timed stage rehearsals, ten frozen bench loops.

### 8. First-48-hour spikes, in retirement order

1. **Mac, Sun, 1 h, R2.** On the current `run_llama.sh` server: the plan-B ORDER payload (system message + tools `order`/`unsure`/`wave`, user turn = instruction text then `input_audio` 16 kHz mono WAV last, `chat_template_kwargs.enable_thinking=false`, temperature 0, `cache_prompt`); 20 rotated clips in en/zh/es. Pass: correct `order()` on ≥18/20, no looping or thinking leakage. Save `requests.jsonl` as the reference payload for Monday. Also one plan-A variant (image + text + audio) for the record, and a prefix check: ORDER, one-word gate and box calls alternating with the same system and tools text, `timings` showing only image/audio and question tokens fresh.
2. **Mac, Sun, 1 h, R2.** Language table v0: 10 clips x en/zh/es (plus any team-native language), E2B greedy; E4B only on a language E2B fails (1.6x slower, it would replace E2B entirely).
3. **PC2, Mon 09:00, 2-4 h, R2.** Toolchain check, native CUDA sm_87 build or the pinned container, harness payloads, 3 s and 8 s WAVs, the ORDER payload; Orin table v1 (cold vs warm, 70 vs 280 tokens, alternating call types); `--no-mmproj-offload` then the Q8_0 mmproj if audio aborts; `nvpmodel -q`, `jetson_clocks`. Decides gate 1 by 14:00.
4. **PC2, Mon 15:00, 15 min, R1.** In the stand: `GetPkgVersion()`, `GetFsmId()==500`, `mode_machine==1`; `ServiceSwitch("g1_arm_example", False)` and back, both timed, arm pose jump observed. If `ServiceSwitch` fails on this firmware, the C++ `turn_off_arm_example` route from the arm-action doc is the fallback. No `Move` test: nothing walks on Oct 24.
5. **PC2, Mon 15:15, 45 min, R1.** `G1_23_ArmController(motion_mode=True)` on `rt/arm_sdk` holds the current pose, plays a 2-keyframe wave, `ctrl_dual_arm_go_home` ramps the weight down; hands: `ls /dev/ttyUSB*`, brainco service, 0.0 and 0.7 on `rt/brainco/right/cmd`, `q` and `tau_est` logged at 100 Hz with a can placed by hand, while a human pulls it out, and while nobody does. Decides whether a pull threshold exists. Assistant 关闭交互 set in the app and verified; `PlayStream` test; remote taped.
6. **PC2, Mon 17:00, 1 h, R2+R3.** `arecord -l` shows the DJI and Lark receivers and the wired mic; 30 s recordings at 2 m standing with 75 dB crowd playback from each, plus the onboard multicast as a comparison only; all through `order()`. Decides the mic.
7. **PC2, Tue 09:00, 1 h, R3.** Stop `teleimager-realsense-webrtc.service`, `teleimager-compat.service`, `mediamtx.service`; OpenCV on the D435i V4L2 node at 640x480 YUYU → 480x336 JPEG q85 at 5 fps; `v4l2-ctl` exposure and white balance locked; rack at hand height and lifted can confirmed in frame; slot bands and crop rectangles defined. Decides the camera.
8. **PC2, Tue 11:00-15:00, R1.** Record with `--motion` in FSM 500 in the stand (never without `--motion`: that path calls `MotionSwitcher.Enter_Debug_Mode()`, which kills ai_sport until reboot); convert the episode to a 50 Hz joint trajectory; replay through the same controller class and gains with the velocity clamp; log commanded vs measured `q` with the 0.37 kg can and record the sag; set the jig to the loaded pose; 20 picks. Decides the pick tier trend at gate 2 and the tier at gate 3.
9. **PC2, Tue 15:00, 2 h, R2+R3.** Everything loaded (llama-server, Piper, DDS clients, camera, brain view) for 2 hours under `tegrastats` while R3 scores the gates and LOCATE on 30 real frames each: peak RSS (llama-server ≤6 GB), temperature, ≥2.5 GB free, battery % per minute. Decides MAXN versus default, the gate frame size, and the runtime extrapolation for Saturday.
10. **PC2, Tue 17:00-Wed 12:00, R3+R1.** ORDER → LOCATE → PICK → VERIFY → HANDOVER end to end on the stand with real skills. Decides whether Wednesday afternoon is reliability work or integration debt.

### 9. Risk register

| Risk | Mitigation | Demo-day fallback |
| --- | --- | --- |
| Gemma 4 audio fails or loops on the Orin under llama.cpp CUDA | Monday verdict by 14:00; `--no-mmproj-offload`, Q8_0 mmproj, pinned container; plan B is already the design; plan C story written | sherpa-onnx Whisper → text into the same tool turn, "ASR in front of Gemma" on the slide; the single-model line goes |
| Audio noise, accented speakers, language ID | Push-to-talk stick, 8 s clips, confirmation line, grace window, enum validation, only languages verified by native speakers promised, language field scored separately | English confirmation with the item name; amber ask-back; the wired mic if the DJI drops twice |
| Arm ownership (`g1_arm_example` versus `rt/arm_sdk`) | One owner: arm_sdk all day; service off at preflight, on at shutdown; switch time and pose jump measured Monday; no `ExecuteAction` anywhere | preflight.sh asserts the service is off; no loop runs until it is |
| Grasp failure (never done on this robot) | Same controller and gains for record and replay; loaded-pose rack height; sag logged; koozies; stall plus yes/no gate; one retry; 20-trial gates in the stand | Human-assisted pick, "would you put it in my hand?", labelled on the slide; handover stays autonomous |
| Release signal unproven | Monday `q`/`tau_est` trace; two consecutive vision yes answers plus "take it"; open to 0.4 first; every release logged with its frame | "I will hold it until you are ready"; presenter asks the judge to lift the can |
| Wrong can, swapped cans, missing colour | Presence gate twice, `box_2d` LOCATE, box plausibility, `none` branch independent of the gate; swap test rehearsed | "I don't see a blue can; I see red and green" |
| Fall with BrainCo hands fitted | Robot in the stand all day, strap slack, casters locked; L2+B = hang; judges on the far side of the table; remote taped to L2 and B; never L2+R2 | Damp in the stand, check hands, continue with voice turns only |
| Battery (about 2 h rated, less with the GPU busy; judging 10:00-15:00 plus stage) | Second pack as a hard requirement; charger and a mains outlet at the bench; runtime extrapolated from Tuesday's soak; Damp in the stand between groups; swaps at 12:00 and 14:00 | Without a spare: two 75-minute windows around a 90-minute charge, the robot in Damp doing voice turns only, stated on the card and the board |
| RF: three 2.4 GHz links, the remote is the e-stop | AP on 5 GHz from an on-site scan; remote charged, within 3 m line of sight, in the spotter's hand; Thursday test with everything radiating; wired mic as the bench default if needed | The DJI only on stage; the stick and button need no network |
| Setup and the bench-to-stage move | 60-minute checklist timed Friday from a packed case; rack jig on the stand frame; the move timed under 10 minutes; 08:30 load-in requested; second cable set | The first loop is a dry run; stage at the bench if steps or rug |
| No-cloud gaps (PC1 cloud client, NTP in Wi-Fi mode, tailscaled) | Whole-robot preflight: Wi-Fi mode off and photographed, tailscaled stopped and disabled, `ip neigh`, MacBook on the robot AP only | Slide line and photo evidence; nothing changes on the day |
| Factory assistant and LEDs | 关闭交互 verified by voice and `rt/audio_msg`; head LED left to the firmware; USB status light | Re-verify after every reboot and swap |
| Latency above budget on the Orin | Shared prefix, 70-token frames, one-word gates, few output tokens, warm-up request at boot; 2.5 s cover budgeted | Status light plus "un momento"; no timer-driven motion |
| Memory pressure and thermal | 2-hour soak; llama-server ≤6 GB; teleimager and mediamtx stopped; ≥2.5 GB free | Server restart with warm-up under 60 s (drilled) |
| Lighting and camera drift | Locked exposure and white balance; saturated koozies and matte backdrop; gates re-scored on 10 frames at 09:30 on site | Assisted pick; hold and ask |
| USB tree re-enumeration | Hub on a PD power bank; devices pinned by `/dev/v4l/by-id`, ALSA card name, `/dev/input/by-id`; 10-minute unplugged run Thursday | preflight.sh names every device before the first loop |
| Stage AV | HDMI and USB-C adapters, 3.5 mm run, PA mirror from the laptop, organizer answers on inputs and PA | The backup video (90 s, captioned) on the laptop and a phone, with the live robot still doing the voice turn |
| Transport | Suitcase 690x450x300 mm, two lifters, SUV, 08:00 load, hands protected, stand and charger travel | Hardware fault: backup video announced as such |
| Model hallucination (absent target, wide-view false positives) | Gates answered twice, box plausibility, honest negatives rehearsed as a feature | "I don't see a blue can" is the planned recovery |

### 10. What we deliberately do not do, and why

The fridge door (bimanual articulated contact, no path to reliable in six days; named on the slide as the next skill). Grasping from clutter (a rack with taped slots). Walking anywhere on Oct 24 (LocoClient `Move` is firmware-gated and untested here, a lidar guard on `rt/utlidar/cloud_livox_mid360` would be a fourth subsystem, and the robot lives in its stand all day; the volunteer walks to the robot). The hip-holster pick tier (a second recorded trajectory that also removes Gemma's can choice). Preset gestures through `G1ArmActionClient.ExecuteAction` during the demo (the service must be off for `rt/arm_sdk`, and `ExecuteAction(int)` blocks). The memory tier, EmbeddingGemma 2, litert-lm serve and any LiteRT claim (token use with three-value rows; the half day goes to pick and handover reliability). Direction-of-arrival and the XVF3800. `AudioClient.LedControl` (the head LED is the spotter's status indicator and the factory assistant drives it). Any learned policy. A Pixel app, Pi coach, Coralboard or Qualcomm board. JetPack 7.2 or MAXN_SUPER reflash. TensorRT Edge-LLM and vLLM. Thinking mode (brief thinking was 90% at 3.5 s p50 and 11.2 s max on the Mac; E2B burns small budgets into empty content). Multi-step plans from Gemma (every thinking-off composition test failed; sequencing lives in code). Wake words and the onboard mic. `TtsMaker` and `rt/audio_msg` (documented as local offline, still kept out of the loop). E4B unless Tuesday's table demands it for one language. Any language not verified by native speakers Tuesday. A foam mat under the feet. A free-standing bench demo. Timer-based release. Canned video as the stage demo. A MacBook doing inference (written permission only, and then only as a slide line). Stage numbers that are not Orin-measured with n.

### 11. Decisions that depend on the owner's answers

| Question | How the answer changes the plan |
| --- | --- |
| Who are the teammates and what can each do (Linux/CMake, Python/web, robotics)? | Fixes R2/R3 ownership; with three people R4 folds into R1 and R3 and the wave is the first thing cut |
| Which native speakers can we reach Tuesday (two per language), and which languages do the judges speak (Arm Create, email)? | Sets the verified set; only those are promised and spoken on stage |
| A true anecdote for the opener? | Else the opener is "Imagine" |
| Does the owner attend Arm Create Monday (11:45 Ballantyne, 13:15 Grundmann)? | If not, R4 goes with a phone video, or the three questions go by email; the 15:00 robot block moves earlier |
| Robot transport: vehicle, two lifters, does the stand come, can we load in at 08:30? | Determines the 08:00 load and whether the stand is the dolly on site |
| Budget: ~$1,000 of audio, light, props and monitor, plus a second battery at an unverified price? | Without a second battery the bench runs in two 75-minute windows, said on the card |
| Is a headset (Quest/AVP/PICO) available Tuesday for `xr_teleoperate --motion --record`? | If not, reach and present are 3 hand-authored keyframes per slot through the same controller |
| Robot software version, PC1 credentials, BrainCo edition (Basic or Touch), both hands detected? | Version decides the FSM path; PC1 credentials make the no-uplink check a command instead of a photo; Touch would add a tactile release signal |
| Organizer answers: stage HDMI and PA, steps and floor surface, demo length, tethered laptop, another G1 team, privacy sign, stacking | Steps or rug → stage at the bench; carpet → MDF board; "no" on the tethered laptop removes the plan-C Mac line; stacking only matters for the LiteRT re-entry condition |
| Downloads (llama.cpp clone, pinned container if needed, Piper and voices, sherpa-onnx + Whisper, webrtcvad, Q8_0 mmproj if needed): pre-approved Sunday | Without Piper there is no voice; without sherpa-onnx there is no plan C |
| Rack pick attempted, or human-assisted from the start? | Assisted-first frees Wednesday for release-gate reliability and makes the honest label the default |

### 12. Alternatives considered

**Lead Me / Lantern (guide).** The most quotable clip, but it depends entirely on the unverified LocoClient path, puts a blindfolded person on a 35 kg biped whose e-stop is a fall, and its stationary fallback is a weaker demo. Grafted: pre-rendered Piper lines for every guard event, no walking at all, and the rule that every spatial word spoken comes from a one-word class answer or a box.

**The Robot That Remembers / Reunite.** The strongest LiteRT claim and a test any judge can run, but the physical act is modest, a robot filming attendees all day needs sign-off, and in our loop the rows reduce to three enum values, which is a lookup, not retrieval. Cut; the privacy line said first and the honest negatives survive as our own.

**Show Me Once (teach through the robot's arms) / Apprentice.** The most reliable shape (the robot stays on its stand) but teleop in view lost rooms before, and Gemma becomes a label on a macro recorder. Grafted: the record-and-replay machinery (`--motion --record` to `rt/arm_sdk` through the same controller, with blends, clamps and the weight ramp) is exactly how our reach and present poses are built, disclosed as such on the slide, and the robot-in-the-stand rule.

**Show Me Once (plan-composing versions) and Show Once.** The organizers' own sentence, but a thinking-on plan turn on the Orin (6-12 s with empty-content and looping failures), open-model SeeDo baselines near zero, and 170-220 person-hours against our roughly 100 after today's cuts. Grafted: the provenance tags and the autonomous success counter.

**Pixel Is the Brain.** The only concept touching the $15k pool, and the most stacking-dependent: a Kotlin fork across the 0.12 to 0.18 API drift on an unproven Pixel 11 TPU path with no Android developer. Not pursued.

**Polyglot Porter, Show Me Around, Any-Language Butler, Fetch.** Porter is the Pepper shape nobody films; its grace window, ask-back and status grammar are in our loop. Show Me Around needs following through a crowd and errand composition from a 3-sample probe. Any-Language Butler's CPU "slow brain" is a second 3 GB engine for no judge-visible gain. Fetch is the engineering spine we adopted (spike order, brain view, preflight.sh, `demo_mode`, assisted pick under an honest label), with the fridge door cut and the Mac-tethered audio demoted to a written-permission slide line.

### 13. Changes from the red team

**Technical lens**
1. Arm stack (blocker): `rt/arm_sdk` through `G1_23_ArmController` is the only arm owner; `g1_arm_example` off at preflight, on at shutdown, switch time and pose jump measured Monday; `ExecuteAction`, the shrug and preset gestures dropped; wave and present are keyframes through the same player.
2. Zero-slack schedule (blocker): memory tier, DOA, stage walk, holster tier and languages beyond en/zh/es (+team natives) cut today; 2-hour robot and GPU blocks published; R3 on mocks until Tue 17:00; end-to-end target Wed 12:00; 30 trials Thu-Fri morning; freeze Fri 12:00.
3. Gains and Debug Mode (major): record only with `--motion` in FSM 500 in the stand; replay through the same controller class and gains; sag logged with the can; rack height from the loaded pose; keyframe fallback without a headset.
4. Unverified headline and toolchain (major): plan B is the design default and plan A a config flag; the exact ORDER payload runs on the Mac tonight; Monday 09:00 toolchain check; pinned JetPack-6 CUDA container as the build fallback.
5. Multilingual validation (major): only languages with two native speakers Tuesday; item and language fields scored separately with n; confirmation in the detected language only if verified; "not tested" list on the slide.
6. Camera premise (major): D435i colour V4L2 node through OpenCV with teleimager and mediamtx stopped; C920 is a Tuesday contingency; crop rectangles and slot bands from the stand camera pose; gates scored Tuesday, not Wednesday.
7. Release signal (major): Monday `q`/`tau_est` pull trace; default release on two consecutive vision yes answers plus "take it", opening to 0.4 first; every release logged.
8. Latency budget and prefix thrash (major): one system message and tools array on every call; Monday measures 3 s/8 s clips, 70/280 tokens, cold/warm and alternating call types; 2.5 s cover; gates at about 1 Hz on 70-token frames unless the crop proves necessary.
9. Battery (major): second pack is a hard requirement with a Monday deadline; runtime from Tuesday's soak; two-window fallback stated on the card.
10. Stage walk (minor): no walking at all on Oct 24; the lidar topic corrected to `rt/utlidar/cloud_livox_mid360` for the record. The suggested Thursday walk bonus was rejected: the stand design and the fourth-subsystem cost rule it out.
11. Memory and DOA (minor): llama-server budgeted at 6 GB; teleimager and mediamtx stopped during the demo; DOA and the XVF3800 cut.

**Rules lens**
12. Gemma decides the can (blocker): presence gate plus `box_2d` LOCATE after every order; slot from the box in code; `item` enum is a superset with `other`; `none` is a code branch independent of the gate; the can swap is a listed bench test with its own row.
13. No-cloud covers PC1 (major): robot Wi-Fi mode off and photographed, app disconnected, `ip neigh`, tailscaled stopped and disabled, MacBook on the robot AP only, "PC1 has no uplink" on the slide.
14. Factory voice service (major): 关闭交互 set and verified in preflight (voice test, `rt/audio_msg` silent), re-verified after every reboot and swap; remote taped to L2 and B; privacy card corrected; the `TtsMaker` statement corrected (documented local offline, still unused). The "LED colours the factory never uses" fix was superseded by leaving the head LED to the firmware.
15. LiteRT token use (major): memory tier and every LiteRT mention cut; "remembers who asked for what" removed everywhere; a narrow written re-entry condition stated. The "make the memory real if the organizers say yes" branch was rejected because the schedule blocker outranks it.
16. Plan-C story (major): written in full in §2 with its slide line and language table.
17. Stage numbers (major): all numbers replaced by typed slots filled Friday; "nothing in this loop"; "two-billion-effective-parameter"; the release-date line dropped; "measured on this robot" only for rows with Orin n.
18. Teleop disclosure (major): the closing sentence, the slide and the `[recorded skill: teleop replay]` tag disclose the replay first.
19. Two-sentence spine (major): one spine on every surface; extras never enter the name, one-liner or opener.
20. Stage speaker (major): a pre-agreed bilingual speaker in a verified language; judges' languages asked Monday; the verified list on the board.
21. Stage walk with a can (major): cut with item 10.
22. Privacy versus storage (minor): no memory JPEGs; gate frames logged for the table and deleted; the card says exactly what is captured; "camera on" sign.
23. Named relative (minor): a true anecdote or "Imagine".

**Demo-day lens**
24. Free-standing bench demo (blocker): the robot stays clipped into the stand bench and stage, L2+B is a hang, the can crosses the table edge, the spotter has one job. The "free-standing stage if Monday's walk gate passed" option was rejected along with the walk.
25. Power budget (blocker): merged with item 9; charger and mains at the bench; stands at :00/:20/:40; swaps at 12:00 and 14:00.
26. Bench-to-stage move (major): rack jig referenced to the stand frame; the move timed Friday under 10 minutes; stage at the bench if steps or rug, agreed with the organizers this week.
27. Setup window (major): 08:30 load-in requested; a 60-minute checklist timed Friday from a packed case in another room; second cable set; the first loop is a dry run.
28. LED collision (major): head LED left to the firmware; USB status light with a legend; assistant sleep in preflight.
29. Foam mat (major): removed; MDF board if the floor is carpet; floor question in today's email.
30. USB tree (major): hub on a PD power bank; devices pinned by stable paths in preflight.sh; 10-minute unplugged run Thursday.
31. Two arm paths (major): same as item 1.
32. Stage AV and backup video (major): organizer questions on HDMI, PA and steps; adapters and a 3.5 mm run; PA mirror from the laptop; 90-second captioned video on the laptop and a phone; fault branch rehearsed once.
33. RF and the e-stop remote (major): AP on 5 GHz from an on-site scan; remote within 3 m, charged, in the spotter's hand; Thursday test with everything radiating. The wired XVF3800 fallback was replaced by a wired USB handheld mic because the XVF3800 was cut.
34. Privacy on the public monitor (minor): merged with item 22; the live frame stays on the brain view (it is the proof that Gemma sees), with the sign and the card saying so.
35. Rehearsal realism (minor): transport rehearsal Friday; locked exposure and white balance; saturated koozies and a backdrop; on-site re-score at 09:30; the Tuesday soak extended to 2 hours; presenter-chosen segment order; grace window = end of confirmation speech plus 3 s with a countdown.

**Editor's own cuts beyond the findings:** the hip-holster tier (a second recorded trajectory that also removes Gemma's can choice) and Kokoro/Japanese (no native speakers on call; Piper has no Japanese voice).