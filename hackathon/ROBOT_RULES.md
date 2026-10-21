# Robot rules (G1, hackathon/brain and everything after)

Hard rules, one line each, with the day that taught them. Process lives in `DEV_WORKFLOW.md`; what is verified with n lives in `HACKATHON_PLAN.md` §2; incidents in `hackathon/INCIDENTS.md`. A rule changes only through a post-mortem.

## Safety

- The robot moves only with the owner present and holding L2+B through every motion; the agent announces each motion by TTS before sending it. (Oct 18)
- No stepping or walking with the robot in the stand: pulses gave 2-27 cm with drift and yaw, and the approach loop once commanded a step toward the table. Stepping needs a free-standing robot, a spotter, a ramped velocity controller, a displacement cap and its own run plan. (Oct 19)
- Left hand only; the right thumb motor is faulty. (Oct 18)
- Grasp order: thumb into opposition first (thumb-aux 0.8), then the four fingers (0.9), then the thumb lock (0.9); staged release in the reverse order. Never bend the fingers before the thumb is placed. (Oct 18, owner)
- After a grasp or a miss the arm retreats upward first, then back over the table edge. (Oct 19: the forward approach dragged the fingers across the edge and pushed the can 19 cm)
- Nothing within 0.30 m straight ahead at chest height, in the depth image, moves the arm forward. (Oct 19)
- Hands enter the workspace and cans are moved only with the arm streamer paused (`p`, ARM OFF shown on the console and the view). (Oct 20)
- No code edits on PC2. Code arrives by rsync from a committed tree whose hash is checked; a parameter changes once per written hypothesis with its predicted effect, and the change is logged as a deviation. (Oct 20)
- Never `pkill -f` a pattern that matches the calling shell or script. Stop the inference server only through its serve script (it stops only the port-8080 process; the Llama.app router on the Mac is the owner's). (g1-fetch learnings, `CLAUDE.md`)
- The PC2 sudo password is known to the owner and the agent and is never written into notes, logs, scripts or chat.
- Battery under 30 percent, 100 minutes elapsed or the owner's named cutoff: no new trials; "stop" from the owner ends the motion at once.

## Per boot (PC2 and robot)

- PC2 power mode MAXN persists across reboots; `jetson_clocks` does not: run it every boot (GPU 63 C under load is normal). (Oct 18)
- Stop the `teleimager-realsense-webrtc` and `-compat` services before opening the D435i; the RealSense is single-owner. (Oct 19)
- Inference server through `hackathon/spikes/scripts/serve-orin.sh` (`-np 1 --cache-ram 0`, one request at a time); warm it with one request before the first order.
- FSM 500 by R1+X on the remote; `ServiceSwitch("g1_arm_example")` off before streaming the arm, on again at the end (0.8 s each). (Oct 19)
- Build the `Robot` object once per session (11 s) and keep the camera, detector and server warm between orders; warm the detector before the first camera frame; read `lowstate` by polling, not by waiting on one message. (Oct 20, g1-fetch learnings)
- The C922 capture must be pumped continuously; otherwise every shot lags one stage. (Oct 20)
- The robot hears its own TTS through the C922: no recording within 4 s of a spoken sentence, and no recording while speaking. (Oct 20: the robot's own "take it" released the can)
- The onboard 4-mic stream only ran with PC1 online; until it is tested offline the C922 (`arecord plughw:2,0`, 16 kHz mono) is the microphone. (Oct 18)
- No cloud in the loop: no default route on PC2 during the demo, Wi-Fi off, Tailscale stopped, PC1 offline, the factory assistant asleep. The proof covers PC1 too.

## Measurement

- Depth at a box centre is the can's front surface; the can axis is half a diameter further along the ray. Every grasp number is in axis coordinates. (Oct 20: 3.3 cm put a slim can at the fingertips)
- The grasp height comes from the measured table plane plus half the can height, never from the box-centre depth; a slide step re-applies the measured joint correction. (Oct 20: the hand ended 2.1-3.6 cm low)
- Geometric numbers live in `hackathon/brain/calib.json` with provenance (value, unit, frame, method, date, pose, can, n, log); no distance literal in motion code; CLI overrides are logged as deviations. Mac numbers are not Orin numbers; office numbers are not venue numbers.
- The palm point is about 0.246 m along the wrist-roll axis (model 0.15 m plus the 0.096 m jog), measured by the owner's eye on Oct 19 and 20 at one pose; it rotates with the forearm. (Oct 19, V2_STRATEGY)
- Hand state is the grasp signal: fingers stall at 0.40-0.55 on a can and reach 0.90 empty; the thumb stalls at 0.07-0.22 on a can; a grasp needs every finger stalled between 0.15 and 0.82. `tau_est` is 0 with or without a can. A stalled finger ignores a repeated target: detecting a pulled-out can needs a fresh setpoint. (Oct 19, 20)
- Stall patterns mean something: thumb 0.9 with fingers stalled = can forward of the palm; pinky 0.9 = hand low or can base narrow; all 0.9 = can pushed away. Two misses with the same pattern end the block. (Oct 20)
- Gemma's yes/no presence gate is unreliable; presence is decided by per-detection crop verification (one-word answer), never by a yes/no gate alone. Gemma's third-person "can in hand" is right after the lift (8 of 9), not before. (Oct 19)
- Can diameter class from the box width and depth (55 vs 66 mm, threshold 60 mm); slim and standard cans need different closure expectations. (Oct 19)
- Never time repeated identical images (the server reuses the image KV); benchmarks are serial and GPU-exclusive; report n and per-class counts; seed every sampled request differently. (`CLAUDE.md`)
- Owner observations are data, recorded next to the hand state they explain, in the fixed vocabulary (contact palm | fingers | heel | wrist | none; pushed 0 | under 2 | 2-5 | over 5 cm; grip firm | loose | none; height low | ok | high), never centimetres by eye. (Oct 20)

## Boot checklist (owner, 15 min, before any motion)

1. Battery percentage noted; charger at hand.
2. Stand straps on; nothing on the table within 0.30 m of the chest; cans on the taped slots, named and photographed.
3. Remote in hand, FSM 500 (R1+X), L2+B rehearsed once.
4. PC2: `jetson_clocks`, camera services stopped, server up and warm, `preflight.py --json` green, no default route if this is a demo rehearsal.
5. C922 aimed at the offer pose and checked on the live frame; phone filming the hand.
6. PC1 state known (online for the factory assistant, offline for the no-cloud proof), factory assistant asleep.
7. Tape numbers entered: table height, can x/y per slot, diameters.

## Pending copies

- g1-fetch's `docs/05_deploy_learnings.md` and `06_dependency_learnings.md` live on PC2 only (`~/g1-fetch`); copy them into `hackathon/research/g1-fetch-learnings/` at the next robot session (PC2 was unreachable on 2026-10-20 evening). The three rules above marked "g1-fetch learnings" are from memory of those files.
