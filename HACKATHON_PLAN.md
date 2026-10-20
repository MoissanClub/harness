# Gemma Hardware Hackathon: "Any Language, One Can"

Google Gemma Hardware Hackathon, AGI House (Hillsborough), Saturday 2026-10-24, 10:00-17:00, teams of 3-4. One rule: a Gemma-based model, entirely on-device. Judges rotate past workbenches, top six demo on stage. Cash pools: Track 2 Physical AI $7.5k/5k/2.5k (our target), Best Use of LiteRT $7.5k pool (not claimed: LiteRT-LM measured 4-15x slower on the Orin, see `hackathon/spikes/2026-10-18-orin-sunday.md`), Best in Show Android $15k (dropped: no Pixel). Research corpus: `hackathon/research/`. History of this plan: `hackathon/archive/`.

## 1. The demo

A judge orders a can by colour, in any language, through the robot's microphone. Gemma 4 E2B on the G1's Jetson hears the audio natively (no speech recognizer), names the colour, and the robot confirms. The head camera finds the cans; Gemma verifies each can's colour; the requested one is located in 3D with RealSense depth. The left arm raises, reaches forward high, lowers beside the can, slides sideways until it touches, closes thumb-first, verifies the grasp from the finger stall, lifts, confirms the can in hand from the third-person camera, and offers it. Order a colour that is not there and the robot says "I don't see a blue can; I see purple and silver." Every decision is shown on a screen with its question, answer and latency, tagged "Gemma decision" or "scripted skill".

Why it wins Track 2: a humanoid that hears, sees, decides and completes a physical act, live, offline, with Gemma-specific features (native audio, vision, grounded colour verification) and honest numbers.

## 2. Verified on this robot (Oct 18-19)

| Piece | Result | Evidence |
| --- | --- | --- |
| Gemma 4 E2B on the Orin NX at MAXN (llama.cpp CUDA, commit a2878d30d) | one-word gate 320 ms, `face_target` tool call 686 ms, box detection 772 ms, Mac-identical accuracy (99/97/100% on 78 frames); 5.7 GB RAM, GPU 63 C | `experiments/20261019T002612*-orin-maxn`, `hackathon/spikes/2026-10-18-orin-sunday.md` |
| Spoken order, audio straight into Gemma | 0.73 s as a native tool call, 0.22 s as a two-word answer; colour word from the C922 mic in 0.26-0.34 s, English or another language | same, plus `hackathon/spikes/2026-10-19-office-grab.md` |
| Can localization | YOLOE and Gemma boxes agree within 5 cm in 3D (RealSense depth, pelvis frame); can diameter classified from box width and depth (55 vs 66 mm) | office notes |
| Colour selection and honest negative | per-can crop asked "what colour is this can" (one word); 0 wrong-can picks, 2 correct refusals; the yes/no presence gate alone is unreliable | office notes |
| Grasp | 8 grasps in a row (slim and standard cans) after calibrating the palm offset (9.6 cm behind g1-fetch's model); closure stalls at 0.40-0.52 on a can vs 0.90 empty; lift within 6 mm; third-person Gemma "can in hand" 4/5 correct after the lift | `hackathon/spikes/office-mon/grab_trials.jsonl` |
| Arm path | g1-fetch `UnitreeArmStreamer` on `rt/arm_sdk` at 50 Hz; `ServiceSwitch("g1_arm_example")` off at start, on at end (0.8 s each); measured-position correction brings the palm within 5-8 mm of the target | office notes, `scripts/arm_test.py` |
| Hands | left hand only (right thumb motor faulty); grasp order thumb-aux 0.8 first, fingers 0.9, thumb 0.9 last; staged release | Sunday notes |
| Audio out | Unitree `AudioClient.TtsMaker` (English voice) through the chest speaker, local | Sunday notes |
| Mic | C922 webcam mic (`arecord plughw:2,0`, 16 kHz mono) is the working path; the onboard 4-mic stream only ran after PC1 had internet, untested offline | Sunday notes |
| Not usable | LiteRT-LM on the Orin (CPU only, 3 s per order); side-stepping in the stand (erratic: 2-27 cm per pulse); the approach loop that steps until the can is in reach (sign bug fixed and guarded, but needs a free-standing robot) | both notes |

Hand lane (where the left hand can grasp with the robot in its stand): can 10-25 cm left of the centre line, 32-40 cm ahead of the pelvis, cans 18-20 cm apart. Cans outside the lane are refused with a spoken reason.

## 3. Architecture as built

```
C922 mic --arecord 4 s--> Gemma (llama-server :8080, audio in) --> colour word --> TTS confirm
head D435i --> YOLOE can boxes --> Gemma crop colour per can --> target box --> depth --> pelvis-frame can axis
                                                                              |
brain (g1-fetch Robot: loco read-only, arm streamer, BrainCo hand, camera, detector)
  raise -> reach high -> lower beside the can (measured-position correction) -> slide 1 cm steps until contact
  -> thumb-first grasp -> finger-stall check -> lift 6 cm -> third-person Gemma check -> offer -> release -> retreat up
C922 as third-person camera --> frames per stage, Gemma "can in hand" after the lift
```

Scripts (all in `hackathon/spikes/scripts/`, run on PC2 in the `g1fetch` env from `~/g1-fetch`): `serve-orin.sh` (server), `voice_grab.py` (voice front end, retries, chains the pick), `grab_loop.py` (one pick trial with all parameters and logging), `scene_cans.py` (no-motion scene read), `see_can.py`, `jog_x.py` (palm-offset calibration), `reach_map.py`, `approach_can.py` (stepping; off), `arm_test.py`, `hands_test_staged2.py`, `audio_probe.py`, `order_probe.py`, `order_words.py`.

Pick parameters that work: `--dx -0.096 --dz 0.0 --contact 0.015 --prethumb --pre 0.05`, diameter auto.

## 4. Hardware

Used: G1 EDU 23 DoF with BrainCo hands (left hand), PC2 Orin NX 16 GB at MAXN (`jetson_clocks` after every boot), D435i head camera, chest speaker, Logitech C922 on PC2 (mic plus third-person camera), the protective stand, the R3 remote (spotter on L2+B), the MT7612U USB access point for the laptop, the MacBook for the brain view.

Still needed: a second G1 battery or a charging window plan; a table and two to three cans in clearly distinct colours (slim or standard); a mount for the C922 facing the hand; a portable monitor for the brain view if the laptop screen is too small for a crowd. Nothing else.

## 5. Next milestone: the full end-to-end demo

Build `hackathon/brain/` as one program that runs the bench loop repeatedly and is what judges see. Done when it runs ten loops in a row on the robot in the stand with two cans and one absent colour, and a 90-second backup video exists.

1. **Loop.** IDLE, LISTEN (TTS prompt, 4 s record, retry), UNDERSTAND (Gemma colour word), CONFIRM (TTS in the guest's language if verified, else English), LOCATE (YOLOE plus crop colour, depth), PICK (the verified parameters), VERIFY (finger stall), LIFT, CHECK (third-person Gemma), HANDOVER (offer, open on the guest's hand seen by Gemma or after a spoken "take it"), RECOVER (refusal with colours seen; grasp miss: retry once then ask for help; out of lane: ask to move the can). All of this exists in `voice_grab.py` plus `grab_loop.py`; the work is to merge them into one process that keeps the robot, camera and server warm between orders instead of rebuilding per run (20 s today).
2. **Brain view.** A page on the laptop over the robot's AP: live frame, question, answer, milliseconds, state, provenance tag, autonomous success counter, no-cloud panel.
3. **Preflight.** One script: server health and warm-up, `jetson_clocks`, FSM 500, hands, camera, C922, arm service state, no-cloud evidence (no default route on PC2, Wi-Fi off, Tailscale stopped, PC1 offline, factory assistant asleep).
4. **Language table.** Native speakers for the promised languages, item and language scored separately with n; only verified languages are spoken on stage.
5. **Rehearsal.** Ten loops in a row logged with per-stage counts; a judge-interrupt drill (resume from any state); the backup video; the stage pitch with the measured numbers (section 7).

Open checks folded into the milestone: does the onboard mic stream run with PC1 offline (if not, the C922 stays the mic); battery runtime with the full stack; the handover release rule (Gemma sees the guest's hand, plus "take it").

## 6. Risks that remain

- Lighting and crowd at the venue change colours and detections: re-score the crop colour check on site; keep the koozies or distinct cans.
- The lane is narrow: tape the table and stand positions so the setup is repeatable; the refusal message covers mistakes.
- One battery: Damp in the stand between judge groups; swap or charge windows.
- No-cloud proof must cover PC1 and the factory assistant, not only PC2.
- Stepping and walking stay out of the judged loop.

## 7. Judge talk points

- One model is the cognitive loop, on the robot: Gemma 4 E2B hears the guest natively, sees the table, decides; code does geometry, control and safety. Nothing leaves the Jetson.
- Measured on this robot: perception gate 320 ms, box detection 772 ms, spoken order 0.26-0.73 s, 27 ms per output token, accuracy identical to the Mac on 78 frames.
- Why sub-second: thinking off, the question after the image, 70-token frames, one cached prefix, few output tokens. A 2B model without thinking perceives well but cannot compose plans, so we ask one grounded question per frame and compose in code.
- Grounded colour choice: every detected can is asked its colour; the requested one is picked by verified colour, not by a presence guess. Honest negatives name what is on the table.
- Multilingual by the model: the same audio turn returns the English colour word from any language the guest speaks.
- The hand: a calibrated palm offset, contact-stop sliding, thumb-first grasp verified by finger stall, release only when the guest's hand is seen. Eight for eight in testing.
- Transparency: every decision on screen with latency and provenance; a live no-cloud proof.
- What we did not do and why: no learned policy, no thinking mode, no teleoperation, no cloud, no walking in a crowd. LiteRT-LM evaluated on the same board and left out with its numbers on the slide.
- Next skill: the fridge door (this stack opened one with a hook grasp on Oct 16).
