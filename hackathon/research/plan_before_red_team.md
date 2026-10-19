I have everything I need from the brief, the harness results, the SDK method names and the local G1 docs. Here is the plan.

# Any Language, One Can
## Build plan for the Google Gemma Hardware Hackathon, AGI House, Saturday Oct 24 2026

## 1. Executive summary

1. We build **Any Language, One Can**: a Unitree G1 drinks host. A judge orders a can in their own language; one Gemma 4 E2B turn on the robot's own Orin NX hears the audio and sees the rack, emits `order(item, language)`, the robot confirms in that language, picks the can and hands it over when Gemma sees the judge's hand on it.
2. EmbeddingGemma 2 served by LiteRT-LM on the same Jetson is the robot's memory: "what did the last person ask for?" is answered by retrieval, verified by Gemma, with honest negatives.
3. It wins because it is the Figure-01 handover shape with two twists judges have not seen (native multilingual hearing with no speech recognizer, and on-device memory), every Gemma 4 feature is load-bearing and visible on a brain view, and the one unproven primitive (the pick) has three implementations of the same skill so the Oct 23 table, not hope, picks the show.
4. We override the ranking's #1: the 322 at the top is a name collision (two unrelated "Show Me Once" concepts summed). The real leaders are within 12 points; this merge takes the Gemma judge's winner (Polyglot Butler), the investor's story pick (Any Language, One Can), the robotics judge's engineering (Fetch) and The Robot That Remembers' LiteRT claim.
5. Targets: Track 2 (first place realistic only if the loop runs ten times in a row), Best Use of LiteRT as a secondary bet, no hardware awards, no Pixel unless a committed Android developer joins by Monday 20:00.
6. Everything runs on PC2 (Orin NX 16 GB): llama.cpp CUDA for Gemma 4 E2B, litert-lm serve for EmbeddingGemma 2, Piper for speech, a Python state machine for sequencing and safety. The laptop only mirrors a web page over the robot's own AP.
7. Risk one: Gemma 4 audio on the Orin under llama.cpp CUDA is unverified. Retired Monday by 14:00; plan B (audio-only tool turn) and plan C (sherpa-onnx, declared) are wired by Tuesday.
8. Risk two: no autonomous grasp has ever run on this robot. Rack pick, hip-holster pick and human-assisted pick share one `pick(slot)` interface; the Wednesday 20:00 gate chooses, and the slide labels the tier.
9. Risk three: a loud 100-person house with a 35 kg biped. Handheld push-to-talk mic only, no walking at the bench, lidar hard stop independent of Gemma, spotter on L2+B, never L2+R2.
10. Code freeze Friday 12:00, five timed stage rehearsals, ten bench loops, backup video for a hardware fault only.

## 2. The pitch

**Project name:** Any Language, One Can.

**One-liner:** Order a drink from a humanoid in your own language; one Gemma 4 model on the robot hears you, sees the rack, picks the can and hands it over, and remembers who asked for what, with nothing leaving the robot.

**The 90-second story (stage opener):**
"My mother-in-law Yuki visited from Osaka last Thanksgiving. Thirty people, a table full of drinks, and she sat in the corner for two hours, because asking for a Coke in a language you do not have is harder than being thirsty. [beat] This is a Unitree G1. Its brain is one model, Gemma 4 E2B, two billion parameters, on the Jetson in its chest. Nothing in this room has an internet connection: here is the unplugged cable, here is the phone in airplane mode, here is `ip route` with no default. The same model hears you in your language, no speech recognizer in between, looks at the rack, decides which can you meant, and calls one function: order. Our code does what code is good at: reaching, closing a hand, not dropping you. [beat] Watch the screen: every decision shows up with its latency, about a second and a half to understand you, under half a second per look. A second Gemma model, EmbeddingGemma 2 on LiteRT-LM, remembers what it heard, so ask it what the last judge wanted. Every number on the slide was measured on this robot this week; the table is Thursday's thirty runs, misses included, because when it misses it says so and asks for help. The person holding the remote is a safety spotter; he never drives. [beat] Who is thirsty? Any language."

**Two sentences for the winners post:** A Unitree G1 that takes your drink order in your own language: a single Gemma 4 E2B turn on the robot's Jetson hears the audio and sees the rack, emits one `order()` tool call, and the robot picks the can and releases it only when Gemma sees your hand on it, while EmbeddingGemma 2 on LiteRT-LM remembers who asked for what. No speech recognizer, no cloud, Orin-measured latencies on the slide, and it says "I don't see a blue can" instead of inventing one.

## 3. Demo script

**Bench loop (2 minutes, repeats all day, resumable from any state).** The robot stands in FSM 500 on taped feet marks inside a 2x2 m mat; a 3-slot can rack sits on a table at the measured hand height, taped relative to the feet marks; nobody walks at the bench. The bench monitor shows the brain view: live 480x336 frame, last question, answer, tool-call JSON, milliseconds, state, provenance tag (`[Gemma decision]` or `[recorded skill]`), running autonomous success counter, and the radios panel (`ip -br link`, `ip route`, unplugged cable photo). A privacy card is read first: no faces, no continuous recording, memory wiped at 17:00.

- 0:00 Presenter: "Take the stick, hold the button, order one of those three in any language." Judge speaks; LED blue while listening (push-to-talk, VAD cut, 8 s cap).
- 0:06 LED cyan: one request (rack frame + instruction + audio + tools) returns `order(item=green_can, language=es)` on screen with ms. LED green; Piper says the templated line in Spanish ("La lata verde. Ya voy."). A 1.5 s grace window: a second button press or "no" cancels; a shrug (ExecuteAction 15 then 99) and "Once more?".
- 0:12 `pick(slot=2)`: recorded rt/arm_sdk reach, BrainCo right hand to 0.7, lift to chest. Gate: finger-stall on rt/brainco/right/state plus "Is the hand holding a can? yes/no" on a 280-token crop. Both shown.
- 0:35 Handover: present pose toward the judge; "Is a human hand holding the can? yes/no" at 2 Hz plus a finger-state pull; fingers open on that signal, never on a timer; "Que la disfrutes." If no hand in 8 s: "I will hold it until you are ready."
- 0:55 **Participatory moment two:** a second judge asks in their language "what did the last person ask for?" or "has anyone ordered a blue can?" The brain view shows the query embedding hitting litert-lm serve, the top-3 memory rows, Gemma's verify step and the answer in their language, or the honest negative.
- 1:15 **Visible recovery, every loop:** the judge orders a colour that is not on the rack; the presence gate answers no and the robot says "I don't see a blue can; I have red and green." When a rack slot is deliberately staged askew (disclosed on the card as "the nudged slot"), the grasp gate fails, the robot retries slot B once, then says "I could not grab it, would you put it in my hand?", opens the hand, closes on the yes gate and completes the handover.
- 1:40 Gesture on request in any language (`gesture(name)`: wave 26, heart 20, handshake 27; high five 18 only if the Tuesday hold pose is clean, with a palm-up sync gate).
- 1:50 Numbers board, handed to the judge on paper.

Between judge groups: Damp on the stand if the gap exceeds 10 minutes, battery swap around 12:30, five-minute preflight after any reboot.

**Stage (3 minutes).**
- 0:00-0:30 Yuki story, the cable held up, one slide on the projector.
- 0:30-1:00 A Gemma-team judge takes the stick and orders in their language; the brain view is projected; the robot confirms in that language (gasp one: a humanoid answering in Portuguese or Hindi with no internet).
- 1:00-2:00 Pick, then the only walk of the day: 2 m at 0.3 m/s in 1 s `Move` pulses toward the raised hand (box_2d at ~1 Hz, lidar front sector stop under 0.7 m, requester on a floor mark as the fallback cue), handover on the hand gate (gasp two).
- 2:00-2:30 A second volunteer orders the missing colour; the honest negative is the planted recovery. Then "what did she order?" answered from memory.
- 2:30-3:00 Numbers slide and the honest sentence: "Scripted skills, Gemma decisions, zero teleop. Pick: rack (or holster, or human-assisted). Handover: autonomous." If the stage has steps, we perform on the floor in front of it. If walking failed Monday's gate, the volunteer walks to the robot.

**The one slide:** Orin-measured latency per call type with n (one-word gate, box_2d, ORDER turn, Piper, speech-end to robot reply); the language table (n per language, `order()` correctness, only Tuesday-verified languages); success table (30 trials: hear, choose, pick, release, recovery); memory retrieval top-1 rate with n; what runs where (PC2: llama.cpp CUDA for E2B, litert-lm serve for EmbeddingGemma 2 on CPU, Piper, state machine; laptop: display only); the no-cloud evidence; battery and memory headroom.

## 4. Prize coverage map

| Award | What in our build qualifies | What else is needed | Honest probability (team estimate) |
| --- | --- | --- | --- |
| Track 2 Physical AI ($7.5k/$5k/$2.5k + Break Glass trophy) | Humanoid hear-see-decide-act loop, fully offline, native audio and tool calls, handover, honest numbers, visible recovery | Ten clean loops in a row on Oct 23, the numbers board, the stage walk if LocoClient works | P(works at some tier) 0.8; P(1st given works) 0.35, 2nd 0.2, 3rd 0.15; EV about $3.3k |
| Best Use of LiteRT ($7.5k/$5k/$2.5k) | EmbeddingGemma 2 via litert-lm serve `/v1/embeddings` on PC2 in the critical path of every memory query, twelve days after its release, visible on the brain view with the serve log | Memory tier survives the Wed 20:00 gate; organizers confirm a LiteRT-LM component beside llama.cpp counts | P(top-3) 0.25; EV about $1.0k; depends entirely on stacking being allowed |
| Best in Show Android/Pixel ($15k + Pixel 11) | Nothing by default | A committed Android developer by Mon 20:00 plus a Pixel 11 order kiosk; then P about 0.05 | Not targeted |
| Best Use of Pixel/TPU (2x Pixel 11) | Nothing by default | Same as above | Not targeted |
| Raspberry Pi, Coralboard, Qualcomm | Nothing | A side device nobody owns; VENTUNO Q cannot arrive in time; criteria unpublished | Not targeted |

Stacking: AGI House has not said one project can take Track 2 plus LiteRT. The plan pays off on Track 2 alone; the LiteRT work is capped at half a day and is cut if it threatens the loop. Ask the organizers in writing today.

## 5. Architecture

```
 judge's voice ──► DJI Mic Mini RX (UAC) ──┐          ReSpeaker XVF3800 (DOA only) ──┐
 PTT arcade button (evdev) ────────────────┤                                        │
                                           ▼                                        ▼
 ┌──────────────────────────── PC2: Jetson Orin NX 16 GB, JetPack 6.2 ─────────────────────────────┐
 │ ears.py (arecord 16 kHz mono, webrtcvad, 8 s cap)      eyes.py (UVC C920 → 480x336 JPEG, crops)│
 │            │ clip                                                │ frame                        │
 │            ▼                                                     ▼                              │
 │  llama-server :8080  Gemma 4 E2B QAT UD-Q4_K_XL + mmproj-BF16 (vision + audio), CUDA sm_87      │
 │  --jinja -np 1 --cache-ram 0 -c 4096 --swa-full, thinking off, greedy, cached prefix            │
 │     ORDER: image+text+audio+tools → order()/gesture()/recall()   GATES: one word   BOX: box_2d  │
 │            │ validated tool call / one-word answers                                             │
 │            ▼                                                                                    │
 │  brain.py state machine: IDLE→LISTEN→UNDERSTAND→CONFIRM(1.5 s)→PICK→VERIFY→HANDOVER→RECOVER     │
 │     │ skills (unitree_sdk2py, DDS on eth0 192.168.123.164)        │ memory.py                   │
 │     ├ loco: LocoClient GetFsmId/Move/StopMove (stage only)       ▼                              │
 │     ├ arm: rt/arm_sdk LowCmd 50 Hz (recorded reach/present)   litert-lm serve :9379 (CPU)       │
 │     ├ gesture: G1ArmActionClient.ExecuteAction 26/20/27/99    EmbeddingGemma 2 /v1/embeddings   │
 │     ├ hand: rt/brainco/right/cmd + /state (stall, pull)        SQLite rows: t, text, vec, jpeg   │
 │     ├ guard: rt/utlidar/cloud_livox_mid ±30° min range (10 Hz)                                  │
 │     ├ speak: Piper → USB speaker (ALSA) | AudioClient.PlayStream                                │
 │     └ led: AudioClient.LedControl (blue/cyan/green/amber/red, ≥200 ms apart)                    │
 │  brainview :8000 (SSE) ──► laptop browser over the robot's USB AP 10.42.0.1, no uplink          │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Component | Device | Model / runtime | Modality | Token budget | Expected on the Orin (projection until Monday) |
| --- | --- | --- | --- | --- | --- |
| ORDER turn | PC2 GPU | Gemma 4 E2B via llama.cpp CUDA | 480x336 image + text + audio clip, native tools | ~300 cached system+tools, 70 image, ≤200 audio (8 s at 25 tok/s), 15-20 output | 1.0-1.5 s (TTFT 0.4-0.6 s + ~20 tokens at ~27 ms) |
| Gates (presence, can-in-hand, hand-on-can, palm) | PC2 GPU | same server, same slot | image (70 tokens, or a 280-token hand crop) + one-word question after the image | ~40 cached + 70-280 image + 25 question + 2 output | 0.3-0.45 s (0.5-0.7 s on the crop) |
| Bearing (stage walk, Tier C alignment) | PC2 GPU | same | box_2d with assistant prefill, stop on `]` | 70-150 image + 17 output | 0.65-0.9 s |
| Memory write | PC2 CPU | EmbeddingGemma 2 (embeddinggemma-2-740m-litert-lm, 485 MB) via litert-lm serve 0.18 | text: every transcript as Gemma returned it, every tool call, a ≤12-word rack caption per order | 768-d vector per row | tens of ms (unmeasured) |
| Memory query | PC2 CPU + GPU | litert-lm serve, then Gemma verify (yes/no on the retrieved frame if any) | text query from the recall tool, cosine top-3 in numpy | n/a | <5 ms retrieval + 0.4 s verify |
| Speech out | PC2 CPU | Piper (en, es, pt, fr, de, it, zh voices; Kokoro for ja only if Tuesday's 1 h test passes) | 16 kHz mono int16 | templated lines pre-rendered | 0.2-0.4 s per sentence |
| Sequencing and safety | PC2 CPU | brain.py (Python 3.10) | state machine, timeouts, watchdog | n/a | speech end to robot reply 1.5-2 s |

Memory budget: llama-server about 4.5-5 GB (E2B + mmproj + KV at -c 4096), litert-lm serve 1-1.5 GB RSS, Piper 0.2 GB, OpenCV 0.3 GB, Unitree services 2-3 GB; the Tuesday 30-minute tegrastats soak must show at least 2.5 GB free or litert-lm serve is the first thing dropped. One llama-server slot: the memory captioner only runs at the end of an ORDER turn, never while a gate is pending.

**Tool API Gemma calls (all enums validated client-side; the native grammar does not enforce them; arguments arrive alphabetically):**

| Tool | Arguments | Validation and effect |
| --- | --- | --- |
| `order` | `item`: enum of the cans on the rack today (`red_can`, `green_can`, `blue_can`); `language`: enum of Tuesday-verified languages plus `other` | invalid or `other` → amber ask-back line in English ("Red or green?"); valid → templated confirmation in `language`, then PICK |
| `gesture` | `name`: enum `wave`, `heart`, `handshake`, `high_five` | maps to ExecuteAction 26/20/27/18 then 99 release; `high_five` waits for the palm-up gate (≤5 s) or is skipped |
| `recall` | `query`: string ≤12 words; `kind`: enum `request`, `scene` | embed query, top-3 within kind, Gemma verify, answer in the speaker's language; no hit → honest negative |
| `unsure` | none | amber LED, "This room is loud, once more?" |

Gates are plain one-word questions after the image: "Is a person facing the robot within two meters? yes/no", "Is the robot's hand holding a can? yes/no", "Is a human hand holding the can? yes/no", "Is there a blue can on the rack? yes/no", "Is the person holding a palm up? yes/no". A gate must say no twice before the robot speaks a failure (the harness saw 2/14 false positives on wide views, so hand gates run on crops and the handover release also needs the finger-state pull).

**On-device, verifiably.** PC2 has no default route (`ip route` empty on screen), WAN cable unplugged and held up, Tailscale stopped (`sudo tailscale down`), venue Wi-Fi never joined, the Unitree app not connected, the dashboard laptop and phone PTT page only on the robot's own MT7612U AP (10.42.0.1, no uplink), phone in airplane mode. The onboard mic array and the factory voice assistant are never in the loop: the mic stays out of wake mode, no `rt/audio_msg` ASR, no `TtsMaker` (its execution location is undocumented), Piper only. The preflight script prints all of this before the first judge.

**Where LiteRT-LM is genuinely in the loop.** litert-lm serve hosts EmbeddingGemma 2 on the Orin CPU (the officially supported path); every transcript, tool call and per-order rack caption is embedded on write and every `recall()` embeds its query on read. Rows are persisted to SQLite on the SSD because a battery swap reboots PC2. Judges can see the serve log window and the retrieved rows. No standby E2B engine, no second LLM, no LiteRT-LM GPU beyond a 30-minute attempt with the prebuilt/linux_arm64 LD_LIBRARY_PATH workaround. If the Tuesday spike fails, the slide claims no LiteRT.

## 6. Hardware

| Item | Owned / buy | Vendor, price | Order by |
| --- | --- | --- | --- |
| G1 EDU, BrainCo hands, D435i, Mid-360, R3 remote, stand, suitcase | owned | | |
| MacBook Pro M4 Pro (dashboard, Mac-side spikes), MT7612U USB AP | owned | | |
| DJI Mic Mini 2-TX kit with USB-C receiver (handheld "talking stick") | buy | Amazon, ~$170 | Sun Oct 18, next-day |
| Hollyland Lark M2 (second brand; UAC on L4T untested) | buy | Amazon, ~$130 | Sun Oct 18 |
| ReSpeaker XVF3800 USB 4-mic array (DOA turn-to-speaker, backup) | buy | Seeed/Amazon, ~$55-80 | Sun Oct 18 |
| USB HID arcade push-to-talk button | buy | Adafruit/Amazon, ~$25 | Sun Oct 18 |
| Creative Pebble V3 USB speaker (the 3 W onboard speaker loses the hall) | buy | Amazon/Micro Center, ~$40 | Sun Oct 18 |
| Logitech C920 webcam + clamp (chest view of the rack; avoids the pyrealsense2 source build) | buy | Micro Center Santa Clara, ~$60 | Mon pickup |
| Powered USB-C 3.0 hub, 10 m Cat6, spare cables | buy | Micro Center, ~$50 | Mon pickup |
| 15-inch portable USB-C monitor for the brain view | buy | Amazon, ~$100 | Sun Oct 18 |
| Folding table at hand height, 3-slot rack (12 cm pitch, wood or print), 12 cans, silicone koozies, hip holster sleeve for Tier B+ | buy | Home Depot/Amazon, ~$100 | Sun-Mon |
| Floor tape, 2x2 m foam mat, gaffer, power strip, printed cards | buy | ~$80 | Mon |
| GL.iNet Beryl AX travel router (backup AP, no uplink) | optional | ~$90 | Sun Oct 18 |
| Second G1 battery | ask | Unitree/reseller, price unverified | Sun Oct 18 email; else charging schedule |
| Pixel 11 256 GB | only if an Android developer joins by Mon 20:00 | Best Buy pickup, $899 | Tue morning |

Total about $750-900 without the battery or Pixel. Downloads that need the owner's approval today: EmbeddingGemma 2 LiteRT-LM bundle (485 MB), litert-lm and litert-lm-api wheels, Piper aarch64 binary and voices, Kokoro ja (optional), sherpa-onnx Parakeet (fallback ASR), webrtcvad. No new Gemma 4 weights; the cached E2B GGUF and mmproj-BF16 are copied from the Mac.

**Microphone decision:** handheld stick with push-to-talk is the only path in the house; the XVF3800 supplies direction of arrival for a free "turn toward the speaker" yaw pulse and is the backup capture; the onboard array is recorded Monday only as a comparison. **Speaker decision:** Pebble V3 over ALSA for the hall, `AudioClient.PlayStream` as the fallback. **Pixel decision:** do not buy by default; nobody on the team is known to ship Android, the TPU sample is Pixel 10 on paper with API drift to litertlm 0.18, the Pixel 10a report shows GPU corrupting tool arguments, and a chest-mounted half-built app loses both pools. If a committed Android developer appears Monday night, the Pixel becomes an order kiosk (Gemma 4 E2B via LiteRT-LM hears the order, sends `order()` over WebSocket on our AP) with a hard Tuesday 20:00 gate; TPU numbers stay off slides under the Tensor ML terms.

## 7. Work plan Oct 18-24

Roles for a team whose skills are unknown: **R1** owner: robot, safety, remote, trajectories, go/no-go calls. **R2** anyone comfortable with Linux and CMake: Orin build, llama-server, prompts, latency and accuracy tables, litert-lm. **R3** any web/Python developer: brain.py integration, ears/mouth/led, brain view, PTT, memory.py, demo narrative. **R4** no technical skill needed: hardware orders, props, transport, batteries, organizer liaison, filming, timing rehearsals, story. With three people R4 folds into R1 and R3.

| Day | Robot skills (R1) | Gemma brain on the Orin (R2) | Integration, memory, brain view (R3) | Demo, story, logistics (R4) | Gate |
| --- | --- | --- | --- | --- | --- |
| Sun Oct 18 (robot offline) | brain.py skeleton against mocked skills; rack and holster design; stage the Orin build script and the 3.6 GB model copy | Spikes 1-2 on the Mac: image+text+audio+tools in one request; language table v0 | ears.py (PTT + webrtcvad), mouth.py (Piper lines), brain view v1, LED grammar | Order everything; email organizers (stacking, tethered laptop, demo length, floor, privacy sign, load-in); register; story v1; approve downloads | 20:00: one-turn audio+image+tools works on the Mac or plan B is the design |
| Mon Oct 19 (robot on; R2 via Tailscale from 09:00) | 16:00-20:00 on the floor: spikes 4-6 (FSM 500, gestures, hands, mics); Layer 0 live on the robot by 20:00 | Spike 3: CUDA sm_87 build, llama-server, Orin latency table v1, audio yes/no by 14:00 | Piper to USB speaker and PlayStream, LED override test, PTT page on the AP | Owner at Arm Create 11:00-14:30 (phone video, three questions: scoring, LiteRT counting, tethered laptop); props | **20:00 gate 1:** Orin audio (A: one turn; B: audio-only turn + vision turns; C: sherpa-onnx, declared) and LocoClient verdict (stage walk or stationary stage) |
| Tue Oct 20 | Record reach-to-slot x3, present pose and holster reach by xr_teleoperate `--record` at the real rack height; replay on the stand over rt/arm_sdk; 20 stand trials | Language table on the real mic at 2 m with 75 dB crowd playback; memory/thermal soak; litert-lm serve spike (1 h cap) | ORDER → confirm → pick → verify → handover end to end on the stand; memory.py writes and recall | Floor tape, rack height, crowd-noise playlist, charging plan, story v2 | **20:00 gate 2:** promised languages (≥9/10 only); mic choice; Pixel in or out; Layer 0 and the voice turn on the robot |
| Wed Oct 21 | Standing extension with a 0.37 kg can on the floor with spotter (IMU log); rack pick 20 trials standing; holster pick 20 trials | Gate prompts scored on 30 real frames each (crop vs full); raised-hand box_2d on 30 crowd frames; latency table v2 | Recoveries (missing colour, failed grasp → retry → assisted, no hand in 8 s, `unsure`), grace window, memory verify step; full bench loop 10x | Film rehearsals, backup video v1, numbers-board layout | **20:00 gate 3:** pick tier (rack ≥8/10 in two consecutive sessions, else holster, else assisted); memory tier kept only if it cost ≤ half a day and top-1 ≥16/20; release gate ≥28/30 |
| Thu Oct 22 | Full loop 30 logged trials with per-stage counts; stage walk 10x on a taped lane (if gate 1 passed) | Fix only what the tables say; latency table final (Orin only) | 10 bench loops with strangers ordering in their languages; judge-interrupt drill (resume from any state) | Backup video v2 (one clean run + recovery); pack list; print two numbers boards; battery runtime logged | Two dress rehearsals in the evening with crowd noise |
| Fri Oct 23 | 12:00 **code freeze** (git tag, `demo_mode` flag disables everything not in the success table); five timed stage rehearsals ≤3:00; ten bench loops; drills: e-stop, server restart with warm-up under 60 s, mic battery swap, PC2 reboot with preflight | | | Load the suitcase, stand, table, rack, cans, mics, speaker, monitor, AP, cables, spare batteries; early night | |
| Sat Oct 24 | 08:00 load with two lifters; 09:30 setup: eth0 DDS, AP up, WAN unplugged, Tailscale down, warm-up request, preflight.sh, tape the mat; one dry run before 10:00; bench loops every ~5 min 10:00-15:00, Damp on the stand between groups, battery swap 12:30; stage as rehearsed; nobody touches code | | | | |

Rehearsal count: 30 logged trials Thursday, two dress rehearsals Thursday evening, five timed stage rehearsals and ten bench loops Friday.

## 8. First-48-hour spikes, in retirement order

1. **Mac, Sun, 1 h, R2.** On the current `run_llama.sh` server, one request with `image_url` (480x336 rack frame), the instruction, `input_audio` (16 kHz mono WAV) last, and `tools=[order]`, `chat_template_kwargs.enable_thinking=false`, temperature 0; 20 rotated clips in en/es/zh. Pass: correct `order()` on ≥18/20 with no looping or thinking leakage. Decides plan A (one turn) versus plan B (audio-only tool turn, then separate vision turns). Rotate clips; identical clips are KV-cached.
2. **Mac, Sun, 1 h, R2.** Language table v0: 10 clips x 6 languages (en, es, pt, fr, de, it, plus zh and ja), E2B versus E4B, greedy. Decides which languages to even attempt Tuesday and whether E4B (1.6x slower, it would replace E2B entirely, not sit beside it) is worth a Tuesday A/B.
3. **PC2, Mon 09:00, 2-3 h, R2.** `cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 && cmake --build build --config Release -j` on llama.cpp master; scp the cached E2B GGUF + mmproj-BF16; `llama-server --jinja -ngl 99 -np 1 --cache-ram 0 -c 4096 --swa-full --alias gemma4-e2b`; send the harness `face-tool-480x336` and `box-prefill-480x336` payloads, then a 3 s and an 8 s WAV, then image+audio+tools. Record Orin latency table v1. If audio aborts: `--no-mmproj-offload`, then the ggml-org Q8_0 mmproj (owner approves the download). Decides gate 1 by 14:00. Also `sudo nvpmodel -q`, `jetson_clocks`, and an MTP/`-fa` A/B only if time remains.
4. **PC2, Mon 16:00, 15 min, R1.** Boot to R1+X; `LocoClient.GetFsmId()==500`; `Move(0.3,0,0)` actually moves; `StopMove()`; `SetVelocity` with duration. If calls return 0 with no motion: `SwitchToUserCtrl`, then the 1→4→501 sequence. Record the software version. Decides stage walk versus stationary stage.
5. **PC2, Mon 16:30, 30 min, R1.** `G1ArmActionClient.GetActionList()`, `ExecuteAction` 26/20/27/18/99 in FSM 500 (watch for 7404); hands: `ls /dev/ttyUSB*`, brainco service, publish 0.0 and 0.7 on rt/brainco/right/cmd, read /state with a can placed by hand (finger stall), then pull it (release signal); `LedControl(255,0,0)` overrides the FSM colours for 10 s; `PlayStream` a Piper WAV in 50 ms chunks. Decides gesture ids and the handover pose source.
6. **PC2, Mon 17:30, 1 h, R2+R3.** `arecord -l` shows the DJI and Lark receivers and the XVF3800; 30 s recordings at 2 m standing with 75 dB crowd playback from each, plus the onboard multicast as a comparison only; run all through `order()`. Decides the mic; PTT stays regardless.
7. **PC2, Tue 09:00, 30 min, R3.** C920 through OpenCV at 640x480 → 480x336 JPEG q85, 5 fps, mounted on the chest, 280-token hand crops. Decides the camera (pyrealsense2 deferred).
8. **PC2, Tue, 1 h, R2.** `pip install litert-lm litert-lm-api` in a 3.10 venv; litert-lm serve with the EmbeddingGemma 2 bundle on :9379; curl `/v1/embeddings` with text; 100 synthetic captions, 20 queries, top-1 ≥16/20; embedding latency; 30-minute GPU attempt with prebuilt/linux_arm64 on LD_LIBRARY_PATH, then stop. Decides whether the memory tier exists.
9. **PC2, Tue, 1 h, R2.** Everything loaded (llama-server, litert-lm serve, Piper, DDS clients, webcam, brain view) for 30 min under `tegrastats`: peak RSS, temperature, ≥2.5 GB free. Decides MAXN versus default and whether serve stays.
10. **PC2, Tue-Wed, 3 h then 2 h, R1.** Convert a `--record` episode to a 50 Hz joint trajectory with velocity clamps; `RobotStateClient.ServiceSwitch('g1_arm_example', 0)`; replay on the stand over rt/arm_sdk with the kNotUsedJoint weight ramp (kp 60/kd 1.5); 2 s blend to the first frame; 20 rack picks and 20 holster picks on the stand; Wednesday, a standing extension with a 0.37 kg can on the floor with the spotter, rt/lowstate IMU logged. Decides the pick tier at gate 3 and whether any standing pick is allowed.

## 9. Risk register

| Risk | Mitigation | Demo-day fallback |
| --- | --- | --- |
| Gemma 4 audio fails or loops on the Orin under llama.cpp CUDA | Monday spike by 14:00; `--no-mmproj-offload`, Q8_0 mmproj; plan B audio-only tool turn | sherpa-onnx Parakeet → text into the same tool, labelled "ASR in front of Gemma" on the slide; the single-model line goes |
| Audio noise, accented speakers | Handheld stick with PTT, 8 s clips, confirmation line before acting, 1.5 s grace window, enum validation, only Tuesday-scored languages promised | Amber ask-back; English fallback line; the judge repeats once |
| Wi-Fi and networking | Own AP, no uplink, DDS on eth0, Beryl AX as backup, phone PTT page only on our AP | 10 m Ethernet to the laptop; the stick and button need no network at all |
| LocoClient firmware-gated | 15-minute Monday test, `SwitchToUserCtrl`, 1→4→501 | Stationary stage: the volunteer walks to the robot; bench never walked anyway |
| Grasp failure (never done on this robot) | Rack with taped slots, koozies, recorded reach, finger-stall plus yes/no gate, one retry, holster tier, 20-trial gates on the stand before any standing pick | Assisted pick: "would you put it in my hand?", closes on the gate, labelled "human-assisted" on the slide; handover stays autonomous |
| Fall with BrainCo hands fitted | Arms extend only in locked stand, never while stepping; spotter on L2+B within 1.5 m; never L2+R2; judges outside the tape; stand for every pick rehearsal until Thursday | Damp, check hands, continue with gestures and memory only |
| Battery (under 2 h with the GPU busy, judging spans five) | Charge between groups, Damp on the stand, swap at 12:30, second battery if Unitree ships one; index and config persisted to SSD | Five-minute preflight after the swap; memory survives the reboot |
| Transport | Suitcase 690x450x300 mm, two lifters, SUV, 08:00 load, hands protected, stand travels | Hardware fault: backup video announced as such, live robot still does the voice turn and gestures |
| Model hallucination (absent target, wide-view false positives) | Presence gates before any claim, two consecutive answers before speaking, hand gates on crops, honest negatives rehearsed as a feature, memory recall-then-verify | "I don't see a blue can" is the planned recovery |
| Latency above budget on the Orin | 70-token frames, cached prefix, one-word gates, few output tokens, warm-up request at boot | LED cyan and "un momento" cover a 2 s turn; no timer-driven motion |
| Memory pressure and slot contention | 30-minute tegrastats soak; captioner only after an ORDER turn; litert-lm serve dropped first | Memory tier cut, no LiteRT claim |
| Factory assistant or app in the loop | Mic never in wake mode, Unitree app disconnected, LED/speaker contention tested Monday | Preflight asserts no wake mode and no default route |
| Stacking disallowed | Plan pays off on Track 2 alone | Nothing changes on the day |

## 10. What we deliberately do not do, and why

The fridge door (bimanual articulated contact, no path to reliable in six days; it is the next skill, said on the slide). Grasping from clutter (a rack with taped slots). SLAM navigation (odometry plus one box_2d bearing for a 2 m walk). Any learned policy. A Pixel app, Pi coach, Coralboard or Qualcomm board unless staffed (every side device is the first cut; a UNO Q at 5.5 tok/s reads as padding). JetPack 7.2 or MAXN_SUPER reflash. TensorRT Edge-LLM and vLLM. LiteRT-LM GPU beyond a 30-minute cap and any standby E2B engine (two LLMs on 16 GB beside the robot stack). Thinking mode (brief thinking was 90% at 3.5 s p50 and 11.2 s max on the Mac, 6-8 s projected on the Orin, and E2B burns small budgets into empty content). Multi-step plans from Gemma (every thinking-off composition test failed; the text-only "works" is a 3-case probe); sequencing lives in code. Wake words and the onboard mic. `TtsMaker` and `rt/audio_msg`. E4B unless Tuesday's table demands it. Any language not scored Tuesday. Walking at the bench, reaching while stepping, timer-based release, a blindfolded judge coupled to the robot. Continuous filming of attendees. A MacBook doing inference (a gray zone for "runs on the device in front of you"; only if the organizers say yes in writing and the slide says so). Canned video as the stage demo.

## 11. Decisions that depend on the owner's answers

| Question | How the answer changes the plan |
| --- | --- |
| Who are the teammates and what can each do (Linux/CMake, Python/web, Android, robotics)? | Fixes R2/R3 ownership; an Android developer by Mon 20:00 unlocks the Pixel kiosk; with three people R4 folds into R1 and R3 and the memory tier is cut first |
| Does the owner attend Arm Create Monday? | If not, R4 goes with a phone video, or we email the three questions |
| Which languages will judges speak? | Sets the Tuesday table; only languages at ≥9/10 on the real mic are promised; Japanese confirmation needs Kokoro (1 h test) or falls back to English |
| Robot transport: vehicle, two lifters, does the stand come? | Determines the 08:00 load and whether pick rehearsals can continue on the stand at the venue |
| Budget: is ~$900 of audio, camera, props and monitor fine; a second battery (price unverified)? | Without a second battery the bench loop runs on a charging schedule with Damp between groups |
| Is a Quest headset available Tuesday for `xr_teleoperate --record`? | If not, reach and present poses are hand-tuned joint targets on the stand (slower, same replay path) |
| Robot software version, BrainCo edition (Basic or Touch), both hands detected? | Version decides the FSM workaround path; Touch would add a tactile release signal |
| Organizer answers: stacking, tethered laptop, demo length, floor lane, privacy sign | Stacking: LiteRT stays a capped side bet either way; tethered laptop "no" removes plan C-Mac; no 3 m lane removes the stage walk; privacy sign required for memory |
| Approval for downloads (EmbeddingGemma 2 bundle, litert-lm wheels, Piper, Kokoro, sherpa-onnx)? | Without them the memory tier and the ASR fallback do not exist; Piper is mandatory |
| Does the owner want the rack pick attempted at all, or holster-first? | Holster-first frees Wednesday for reliability and makes the robotics judge's "same demo, honest label" the default |

## 12. Alternatives considered

**Lead Me / Lantern (guide).** The investor's top pick and the most quotable clip, but it depends entirely on the unverified LocoClient path, puts a blindfolded person on a 35 kg biped that collapses on the e-stop (organizers may veto it), and its stationary fallback is a different, weaker demo. Grafted: the lidar front-sector hard stop independent of Gemma, pre-rendered Piper lines for every guard event, no walking at the bench, and the rule that every spatial word spoken comes from a one-word class answer or a range.

**The Robot That Remembers / Reunite.** The strongest LiteRT claim and a test any judge can run, but the physical act is modest, a robot filming attendees all day needs sign-off, and the captioner starves llama-server's single slot. Grafted as our memory tier: EmbeddingGemma 2 via litert-lm serve, recall-then-verify, honest negatives, the privacy line said first, captions only at order time.

**Show Me Once (teach through the robot's arms) / Apprentice.** The robotics judge's winner and the most reliable (the robot stays on its stand), but two judges read teleop in view as the image that lost the room, and Gemma becomes a label on a macro recorder. Grafted: the record-and-replay machinery (`--record` to rt/arm_sdk with blends, clamps and the weight ramp) is exactly how our reach and present poses are built, plus the distance-quoting refusal pattern and the palm sync gate.

**Show Me Once (both plan-composing versions) and Show Once.** The organizers' own sentence, but a thinking-on plan turn on the Orin (6-12 s, empty-content and looping failures), SeeDo-style open-model baselines near zero, an unproven push or slot pick, and 170-220 person-hours. Grafted: the provenance tags and the autonomous success counter on the brain view.

**Pixel Is the Brain.** The only concept touching the $15k pool, and the most stacking-dependent: a Kotlin fork across the 0.12 to 0.18 API drift on an unproven Pixel 11 TPU path by a team with no Android developer, and for Track 2 the phone becomes the project. Kept only as the optional order kiosk if a developer appears Monday night.

**Polyglot Porter, Show Me Around, Any-Language Butler, Fetch.** Porter is the Pepper shape nobody films; its grace window, ask-back and LED grammar are in our loop. Show Me Around needs following through a crowd, odometry over several legs and errand composition from a 3-sample probe. Any-Language Butler's CPU "slow brain" is a second 3 GB engine for no judge-visible gain. Fetch is the engineering spine we adopted (spike order, brain view, preflight.sh, `demo_mode`, assisted pick under an honest label), with the fridge door cut and the Mac-tethered audio demoted to a written-permission-only option.