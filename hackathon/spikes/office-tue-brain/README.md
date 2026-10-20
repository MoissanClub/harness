# 2026-10-21 (01:50-03:15 CST), office: first on-robot session of hackathon/brain

Logs only (no frames or clips: those stay on PC2 under `~/harness/hackathon/brain/runs/`). One folder per brain session
(`order_NN.jsonl` with every Gemma call, stage and move; `orders.jsonl` summaries), `live*.log` console logs, `dry1.log`,
`jog_today.log` (palm-offset jog). Owner present on L2+B throughout; PC2 at MAXN with jetson_clocks, camera services stopped.

| Session | What ran | Result |
| --- | --- | --- |
| 021334 | `--dry --orders 1` | heard white on the retry, located the silver can 40 cm ahead / 3 cm left, lane refusal spoken, no motion |
| 021723 | `--orders 3`, verified defaults | lane refusal; white MISSED twice (thumb and 3 fingers on the can, pinky past it; retry found the can pushed 8 mm); no colour heard |
| jog | `jog_x_byid.py --start -0.12 --n 5 --dz 0` | owner picked step 1 = -0.097 (yesterday -0.096); reach limit at palm x 0.41 for a can 47.8 cm ahead |
| 023422 | `--orders 3` | missed, then the owner placed the can: held, lifted, released on a voice clip (the robot hearing its own reminder) |
| 023730 | `--orders 3 --pause 8` (live C922 frames) | missed twice; assisted placement rejected by the strict rule (pinky 0.9); frames showed the can at the fingertips |
| 024115 | `--orders 3 --pause 8 --dx -0.06 --verify majority` | **two autonomous successes** (closure 0.48 / 0.50, fingers 0.40-0.55, contact detected, lift within 3 mm, Gemma yes); releases were self-triggered by the robot's own "take it"; third can 49 cm ahead refused |
| 025243 | commit 91a2e2e, axis fix, default dx | three lane refusals: the far bound (46 cm) was still in surface coordinates |
| 025439 | lane 31-50 cm on the axis | **two more grasps** (closure 0.42 / 0.43, fingers 0.32-0.50), both released by the operator key after the guest pulled the can (stalled fingers do not move without a fresh command) |
| 030059 | 83d7c0e (re-commanded grasp during the hold) | can only 7-8 cm left of centre: missed twice (the slide pushed it), assisted placement missed; battery low, session ended |

Root cause of the morning's misses: the brain (and `grab_loop.py` in auto-diameter mode) grasped the can's FRONT SURFACE
(`cfg.fridge.can_diameter_m` = 0 while `can_axis_from_box` adds half of it), while `jog_x.py` calibrated `dx = -0.096` against the
true axis (config diameter 0.066). 3.3 cm back put a sleek can at the fingertips. Fixed in the brain (point moved to the axis once the can
is classified); `--dx -0.06` from the surface and `-0.096` from the axis are the same hand position.

Other lessons: the C922 capture must be pumped continuously or every shot lags one stage; the robot hears its own TTS through the C922
(no recording within 4 s of its sentences); BrainCo `tau_est` is 0 with or without a can and a stalled finger ignores a repeated
target, so a pulled-out can is detected by re-commanding the grasp with a fresh setpoint; Gemma's "human hand on the can" never fired
because the webcam did not see the offer pose; cans nearer than ~10 cm to the centre line get pushed by the slide; the arm reaches a
can axis up to ~50 cm ahead. Latencies on the robot: colour from audio 255-342 ms, crop colour 313-364 ms, yes/no 304-340 ms, transcript
of a 2 s clip 222-577 ms, build 11.1 s once per session.

Open for the next session: grasp calibration with `hands_test_staged2.py` (owner feels the thumb lock after the fingers loosens the hold),
the pulled-can cue on the robot, the webcam aimed at the offer pose, the absent-colour order, and the ten-order run.
