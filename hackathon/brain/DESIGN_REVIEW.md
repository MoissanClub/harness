# Design review of hackathon/brain after the first robot session (2026-10-21)

Written at the owner's request after a disappointing session. Brief for the v2 redesign.

## Why the current implementation is fragile

1. **Open-loop in the dimension that matters.** The hand is placed by forward kinematics of an arm model whose palm point is
   wrong by ~10 cm and whose error changes with configuration (the jog pose and the pick pose disagree by 3-4 cm). A calibrated
   constant (`dx -0.096`) hides this only at the pose it was measured in. The head camera sees both the can and the hand, so the
   hand-to-can offset can be measured directly in one frame; `grab_lateral.py` did exactly this on Oct 19 and it was dropped for
   proprioceptive corrections, which correct the model against itself.
2. **Guards instead of feasibility.** The lane (y 0.06-0.30, x 0.31-0.50) encodes two incidents (a torso collision with the forearm
   forced forward at y 0.8 cm, the jog's reach limit at 48 cm) as hard windows. Both are properties of ONE grasp strategy: forearm
   along +x, palm facing the midline, lateral slide. With shoulder yaw and elbow rotation free, the hand reaches near the body centre
   from the left-front. The right check is IK feasibility over a set of forearm directions plus a torso-clearance test, not a window
   of distances that will differ on every table and stand position.
3. **The approach pushes what it should grasp.** The slide is a blind 1 cm march until a tracking-error rise. When the palm is not
   centred on the can, the fingers reach the can first and push it (every miss today). Contact was only detected when the alignment
   was already right, so the contact stop confirms success rather than producing it.
4. **Failure modes are diagnosed by the hand but not used.** The stall pattern is informative: thumb 0.9 with fingers stalled means
   the can is forward of the palm; pinky 0.9 means the hand is low or the can base is narrow; all 0.9 means the can was pushed away.
   The brain treats all three as "retry the same thing" and then asks the guest for help.
5. **Order understanding is narrower than the model.** The guest must say a colour word; the model can match any description
   (flavour, fruit picture, brand, "the tall one") against the crops in one multimodal call, in any language.
6. **The verification camera was never designed.** The C922 placement is ad hoc; at the offer pose the hand leaves its view, so the
   vision release can never fire. The head camera should be the verification camera wherever the hand is in its view, and the offer
   pose should be chosen inside that view.
7. **Process.** I reused "verified" mechanics that were verified on one day, two can positions, one can type, and treated their
   parameters as fixed. On the robot I tuned deltas before isolating causes. The correct order is: instrument (live frames, per-stage
   logs, hand state per cycle), reproduce, find the cause, change one thing.

## What was learned and must be kept

- Perception: YOLOE boxes (105-135 ms) plus one-word Gemma crop answers (310-360 ms on the Orin) are reliable; depth to the box
  centre is the front surface; the can axis is half a diameter further. Gemma hears the colour word from the C922 clip in 255-340 ms
  in any language. Gemma's third-person "can in hand" is right after the lift (4/5 yesterday, 4/4 today); the human-hand question
  only works if the camera sees the hand.
- Hand: the finger stall pattern is the grasp signal (fingers 0.40-0.55 on a can, 0.90 empty; thumb stalls at 0.07-0.22 on a can);
  `tau_est` is zero with or without a can; a stalled finger ignores a repeated target, so detecting a removed can needs a fresh setpoint.
- Arm: `cart_move` plus two proprioceptive corrections reaches the MODEL target within 8 mm; the model's palm is ~10 cm ahead of its
  nominal point; the reach of the lateral strategy ends at a can axis ~50 cm ahead at 22 cm left.
- Timing: build once 11 s, then every stage is sub-second except motion; a full order is 100-150 s, mostly motion and the 4 s pause.
- Robot hygiene: camera services and jetson_clocks per boot; the C922 must be pumped continuously; the robot hears its own TTS.

## v2: the three areas

### 1. Reach: free the forearm, test feasibility, measure the table

- Replace the lane with a feasibility search: for the can point, try forearm directions from +x to 45 deg inward (yaw) and small
  pitch, with the palm facing the midline or facing back toward the body; accept the first solution whose IK error is under
  tolerance and whose elbow and forearm segment clear a torso box (pelvis frame, measured once). Cans near the centre line are then
  approached from the left-front with the elbow rotated in, which is what the owner demonstrated by hand.
- The table plane comes from the depth image (`fit_plane_ransac` exists in g1-fetch); the pre-grasp height is table + can half-height,
  not a fixed z; the "up first" retreat clears the measured table edge.
- Keep one hard safety: nothing inside 0.30 m straight ahead at chest height moves the arm forward.

### 2. Order: "tell me which one you'd like"

- LOCATE first: boxes, then one short Gemma description per crop ("What is this can? Three words.") -> e.g. "purple La Croix",
  "lychee sparkling water", "black coffee".
- UNDERSTAND with the audio AND the list: system prompt lists the numbered descriptions; user turn = the clip; answer = the number
  or none. One call, any language, any attribute; the descriptions double as the spoken confirmation ("The lychee one. Coming up.")
  and as the honest negative ("I do not see that. I see a purple La Croix and a lychee water."). Measured path: image+audio in one
  request was 0.98 s on the Orin; audio+text will be faster.
- Fallback when the clip is ambiguous: ask "the purple one or the lychee one?" rather than "say the colour again".

### 3. Grasp: visual servoing of the hand to the can, decisions from the hand state

- Pre-grasp as today (raise, reach high, lower beside the can at the pre-grasp offset), then CLOSE THE LOOP IN THE HEAD CAMERA:
  one fresh frame gives the can (YOLOE + depth) and the hand (depth blob at the expected place, or a Gemma box of "the robot's white
  hand", both exist) in the same pelvis frame; command the relative correction (x, z) and repeat until the measured palm-to-can
  offset is under 1 cm (2-3 iterations). No `dx`, no jog, no distance dependence: the model error cancels because both points are
  measured by the same camera.
- Approach along y in two halves with a visual check between them; stop when the can's centre is inside the palm's x window as
  measured, not when the tracking error rises. Contact stop stays as a safety.
- Close, read the stall pattern, act on it: thumb 0.9 -> open, move 3 cm forward, close again; pinky 0.9 -> open, lift 2 cm, close
  again; all 0.9 -> re-locate (the can was pushed). One targeted correction, then the assisted path.
- Lift, then verify with the head camera (the can moves with the hand: its box rises) in addition to the stall, since the camera
  is already looking there; the C922 becomes optional.
- Handover inside the head camera's view (offer pose chosen so the hand is visible): release on the pulled-can cue (fresh setpoint
  each cycle), on a human hand seen twice in the HEAD camera, or on a let-go transcript; never record while speaking.

## What to do first in the new session (in this order)

1. Hand localization in the head camera at the pre-grasp (no can motion): report the measured palm-to-can offset versus the model's;
   this one number decides whether the servo loop is viable. Expect 3-4 cm disagreement.
2. The servo loop on one can at three positions (left, centre-left, centre), with the free-forearm IK; log offsets per iteration.
3. Stall-pattern corrections; then the description-based order; then ten orders.

Keep from v1: the process structure (one build, states, logs, view, preflight, park pose, keys, safe shutdown), gemma.py, the
hand sequence (thumb opposed, fingers, thumb lock; the owner wants the thumb lock re-examined), the lift and offer poses.
