# Judges' dashboard

One page that shows what the robot is doing while brain v2 runs: the stage it is in, the sentence it just said, the head camera with
every can boxed and numbered (the chosen one in green), Gemma's description of each can's crop with its latency, the guest's audio clip
and the can Gemma picked from it, every Gemma call (question, answer, ms, tokens in/out), and the movement steps (raise, reach, lower,
hand check, each 1 cm approach step with the gap left, close, grasp check, lift, offer, release) with what decided each one: Gemma,
a sensor gate or a scripted skill.

`dashboard.py` (stdlib, Python 3.8+) only **reads** what `brain.py` already writes under `hackathon/brain/runs/`:
`live/status.json` and `live/frame.jpg`, and per order `<session>/order_NN.jsonl` with its `order_NN/` frames and clips. Nothing in
`hackathon/brain` changed, so the brain tree stays clean for `--expect-calib`. It lives outside that folder so that editing this page
never makes the brain tree dirty either. It replaces `brain/brainview.py`; both default to port 8000, so run only one.

## On PC2

```bash
cd ~/harness/hackathon/dashboard
python3 dashboard.py                  # http://0.0.0.0:8000; start it before or after brain.py, it follows whatever runs
```

Getting it onto PC2 without touching the brain: `scp -r hackathon/dashboard g1-ap:~/harness/hackathon/` from the Mac, or commit it and
deploy the usual way.

From the MacBook, whichever network you are on with the robot:

- the robot's access point: `http://10.42.0.1:8000`
- the robot's Ethernet: `http://192.168.123.164:8000`
- any ssh path (`ssh -N -L 8000:127.0.0.1:8000 g1-ap`, then `http://localhost:8000`)

The page loads nothing from the internet. A browser window wider than 1200 px (full screen: Ctrl-Cmd-F) gives the three-column layout
with no scrolling; narrower windows stack the panels.

The footer shows the no-cloud evidence PC2 sees (`ip route`, `nmcli radio wifi`, `tailscaled`; click it for the raw output), the
preflight result if `preflight.py` ran, llama-server's health, and the brain commit and calib sha of the order on screen with any
CLI overrides. The header counts the orders and autonomous hand-overs of the last 14 hours (`--hours`), and Gemma calls with their
median latency.

## Replay (backup demo, testing)

```bash
# from the repo root
python3 hackathon/dashboard/dashboard.py --replay hackathon/spikes/2026-10-23-v2-grasp/runs-pc2/20261024T035958 --max-gap 4 --loop
```

Plays recorded sessions (a session folder, or a folder of them) with their own timing; pauses longer than `--max-gap` seconds are
shortened, `--speed` scales the clock. The page shows an amber REPLAY bar with the session and recording time, so it cannot pass for
live.

## What it cannot show

- Between decision frames the brain holds the head-camera frame (`frame_hold`), so during the arm motion the "live" tile is the
  last decision frame; the side-camera (C922) shots arrive at the pre-grasp, after the approach, after the close and after the lift.
- The guest's words: Gemma maps the audio straight to a can number and there is no transcript. The clip itself plays on the page.
  During the handover the "take it" transcripts are shown.
- With `--orders 1` every order is its own brain process; between processes the page says BRAIN NOT RUNNING and keeps the last
  order on screen.

Tested on the Mac only (2026-10-24): replay of the Oct 23 robot sessions 034032 (run 2, assisted) and 035958 (run 6, grasp on
its own, no way home), and live against `brain.py --mock --mock-gemma` (scenes `three` and `mid`). Not yet run on PC2.
