# hackathon/brain: the drinks-host loop as one long-running program

One process on PC2 (the G1's Jetson Orin NX) that keeps the robot, the head camera, the YOLOE detector, the BrainCo hand, the
C922 mic/camera and the llama-server connection warm, and runs the bench loop order after order. It merges the verified
`spikes/scripts/voice_grab.py` (voice front end) and `grab_loop.py` (one colour-verified pick) without rewriting their mechanics;
today each run of those rebuilt everything for about 20 s, here that happens once at start.

```
IDLE > LISTEN > UNDERSTAND > CONFIRM > LOCATE > PICK > VERIFY > LIFT > CHECK > HANDOVER > (RECOVER) > IDLE ...
```

| Stage | What happens | Decided by |
| --- | --- | --- |
| LISTEN | TTS "Which can would you like? Tell me the colour.", 4 s `arecord` from the C922 (`plughw:N,0`, 16 kHz mono), up to 3 attempts | scripted |
| UNDERSTAND | Gemma hears the clip natively (any language) and answers the English colour word, or `none` | Gemma |
| CONFIRM | TTS "The purple can. Coming up." | scripted |
| LOCATE | fresh D435i frame, YOLOE can boxes, Gemma "What is the main colour of this can?" per crop, RealSense depth to the pelvis frame, can diameter from the box width (55 / 66 mm), lane guard with a spoken reason and one re-look, IK feasibility | Gemma (colour), code (geometry) |
| PICK | raise, reach high, lower beside the can with two proprioceptive corrections, thumb opposed, 1 cm slide steps with a contact stop, staged grasp | scripted skill |
| VERIFY | every finger stalled between 0.15 and 0.82 (not closed on nothing, not blocked open) | sensor gate |
| LIFT | 6 cm with correction | scripted skill |
| CHECK | third-person C922 frame, Gemma "Is the robot holding the soda can in its hand, off the table?" (advisory only, logged and shown) | Gemma advisory |
| HANDOVER | offer pose, TTS "I have the can. Please take it."; release when Gemma sees a human hand on the can in two consecutive third-person frames, or a 2 s clip transcribes to a let-go phrase ("take it", "got it", "thank you", "let go", ...), or the `r` key, or `--release-after`; otherwise hold and say so every 15 s | Gemma + sensor gate |
| RECOVER | colour absent: "I do not see a blue can. I see purple and silver." (no motion). Grasp miss: open, retreat, re-locate, retry once; second miss: hold the open hand at the offer pose and ask the guest to place the can, verified by the stall. Out of lane: ask to move the can, look again once, then ask to order again. | scripted |

Every order ends with the arm back over the table edge, then at the park pose (`--park zero`: Unitree joint zero, elbows bent, forearm
forward, the arm streamer stays on; `home` for g1-fetch's home_q; `release` fades the streamer out and the arm drops to the controller's
pose). The arm service is switched off once at start and on at exit.

## Files

- `brain.py`: the state machine and the main loop. `python brain.py -h` lists every parameter.
- `gemma.py`: the Gemma calls (payloads identical to the spike scripts), each returned as a record with question, answer, milliseconds, provenance tag and server timings.
- `preflight.py`: pass/fail table; `brain.py` runs it at start and refuses to start on a failure.
- `brainview.py`: the page for the laptop, stdlib HTTP + server-sent events, port 8000.
- `mock_robot.py`: Mac-side mock of g1-fetch, the mic and the C922 so the loop can be exercised without the robot (`--mock`, `--mock-gemma`).
- `runs/` (git-ignored): `live/` for the view, one folder per session with one JSON-lines file and one frame folder per order.

## Start on PC2

```bash
# once per boot, owner (sudo): clocks, and free the D435i from the streaming services
sudo jetson_clocks
sudo systemctl stop teleimager-realsense-webrtc.service teleimager-compat.service
# robot in its stand, FSM 500 (R1+X); owner holds the remote on L2+B
~/spike/serve-orin.sh                                 # llama-server, 127.0.0.1:8080, healthy in ~9 s
source ~/miniconda3/etc/profile.d/conda.sh && conda activate g1fetch
cd ~/harness/hackathon/brain
python preflight.py                                   # table; --venue makes the no-cloud checks hard failures
python brainview.py &                                 # laptop on the robot's AP: http://10.42.0.1:8000
python brain.py                                       # preflight again, build once, then loop
```

`brain.py` changes directory to `~/g1-fetch` itself (so `configs/pc2.yaml` and the detector weights resolve) and imports
`bench/client.py` from this repo; `--g1fetch` or `G1FETCH` override the location. Keys on stdin: `q` quit with a safe release,
`a` abort the current order, `r` release the can now, `p` pause / resume listening, Enter starts an order with `--manual`.
Ctrl-C or SIGTERM: hand opened (thumb last), arm streamer disabled, robot closed, arm service back on.

Preflight checks: server `/health` plus a warm-up request (a C922 frame through the vision path), FSM 500, both hands publishing
(right is a warning), D435i present, C922 video node and ALSA capture card, the teleimager camera services inactive, arm service
state, MAXN (8 cores online) and `jetson_clocks` (GPU min = max frequency), `rt/audio_msg` silent (factory assistant asleep),
no default route, Wi-Fi radio off, `tailscaled` inactive. The last three are warnings unless `--venue`.

## Parameters (defaults are the verified ones)

| Parameter | Default | Where it came from |
| --- | ---: | --- |
| `--dx` | -0.096 | palm centre vs the can axis, calibrated with `jog_x.py` (the arm model's palm is 9.6 cm short) |
| `--dz` | 0.0 | palm at the can's mid-height |
| `--pre` | 0.05 | pre-grasp offset to the can's left |
| `--contact` | 0.015 | tracking-error rise that counts as contact |
| `--press` | 0.02 | slide this far past the can's near surface |
| `--tol` | 0.035 | IK tolerance |
| `--pause` | 4.0 | pause at the pre-grasp (owner's palm check); lower it for the show |
| `--diam` | auto | 55 mm if the box is under 60 mm wide, else 66 mm |
| thumb first | on | `--no-prethumb` to disable |
| `--lane-y` | 0.06 0.30 | can left of the centre line (grab_loop's guards); the comfortable lane is 10-25 cm |
| `--lane-x` | 0.28 0.46 | can ahead of the pelvis (reach map 26-44 cm, minus the torso-collision case at 25 cm) |
| `--seconds` | 4 | order recording |
| `--retries` | 3 | listen attempts per order |
| `--relook` | 1 | re-looks after asking to move an out-of-lane can |
| `--assist-wait` | 8 | seconds for the guest to place the can after two misses |
| `--hold-reminder` | 15 | seconds between "take it" reminders |
| `--release-after` | 0 | rehearsal only: timed release |
| `--verify` | strict | strict: every finger stalled in (0.15, 0.82); majority: thumb under 0.3 and at least 3 of 4 fingers stalled |
| `--park` | zero | left-arm pose between orders (zero / home / release) |
| `--orders` | 0 | stop after N orders (0 = until `q` / Ctrl-C) |
| `--dry` | off | listen, locate, report the target and stop before PICK (no arm motion) |

The located point: the localizer measures the can's front surface and pushes it back by half of `cfg.fridge.can_diameter_m`; the brain
runs with that value at 0 (auto diameter) and moves the point to the true axis itself once the can is classified. `--dx -0.096` was
calibrated against the true axis (jog_x.py); grasping the front surface instead put a sleek can at the fingertips (2026-10-21).
Release during HANDOVER also fires when two or more fingers close past their stall values (the guest pulled the can out), and no
clip is recorded within 4 s of the robot's own sentences (it heard itself say "take it" once).

Lane and pelvis frame: x ahead, y left, metres. Grasp point = can axis + (dx, radius + 1 cm, dz); pre-grasp = grasp + (0, pre, 0).

## Logs

`runs/<session>/order_NN.jsonl`, one JSON object per line, `ev` in: `order` (parameters), `say`, `record`, `gemma` (question,
answer, ms, tag `Gemma decision` / `Gemma advisory`, prompt and output token counts, cache hits, media), `detect`, `target`,
`lane`, `move`, `slide`, `verify` (tag `sensor gate`), `release`, `stage` (milliseconds per state), `error`, `result`
(the whole order: colours seen, target, closure, hand state, release reason, `autonomous`, total ms). `runs/<session>/orders.jsonl`
holds one summary line per order. Frames and clips: `runs/<session>/order_NN/` (`head_boxes.jpg`, `cam3_<stage>.jpg`,
`order_N.wav`, `hold_NN.wav`). Counters shown on the view: orders, autonomous (grasped and released on the guest's hand or voice),
honest negatives, assisted (guest placed the can), manual release (`r` key or timer), failed, grasps / misses.

## Brain view

`brainview.py` serves `/` (the page), `/events` (SSE), `/frame.jpg`, `/status.json`, `/nocloud`. The page shows the latest
head-camera frame with the boxes and colours, the state, the last question / answer / milliseconds with its provenance tag, the
spoken line, the counters, the stage times, the decisions of the current order, the preflight table and the no-cloud panel
(`ip route`, `nmcli radio status`, `systemctl is-active tailscaled`, `ip -br addr`, refreshed every 10 s). It only reads
`runs/live/`, so it can run before and after the brain.

## Validation so far

On the robot (office, Oct 19-20, `grab_loop.py` + `voice_grab.py`, the same mechanics and parameters): 8 grasps in a row (slim
and standard cans), 2 correct honest negatives (red, blue), 0 wrong-can picks; Gemma colour word from the C922 clip 0.26-0.34 s,
one-word vision gate 320 ms, YOLOE 105-135 ms, third-person "can in hand" after the lift 4/5 correct (hence advisory). Details:
`spikes/2026-10-19-office-grab.md`, `spikes/office-mon/grab_trials.jsonl`.

On the Mac (2026-10-19, `--mock` robot, real Gemma 4 E2B on llama.cpp, office clips and frames): three orders, purple
(grasp, lift, check `yes`, hold, timed release), blue (refused: "I see purple and silver"), white spoken in another language
(heard `White`, the silver can accepted as white, refused for the lane since that can stood 5 cm from the centre line, one re-look);
colour from audio 178-259 ms, crop colour 206-404 ms, all correct. A scripted-Gemma run exercised two misses, the assisted
placement and the vision release. Spoken let-go detection on 14 synthetic clips (7 phrases, 2 voices): transcript + keywords
14/14, the yes/no judgement 9/14, so the transcript is the default.

Not yet validated, needs the robot and the owner present: the long-running loop itself on PC2 (persistent camera, detector,
arm streamer and C922 across orders), the handover release on a real guest's hand, the `take it` clip through the C922 in a
room, and the ten-consecutive-order run. `rb.speak` is assumed non-blocking as in the spike scripts (the listen prompt uses the
same sleeps as `voice_grab.py`).
