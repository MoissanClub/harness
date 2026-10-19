"""Voice-to-grab: the robot asks which can, records from the C922 mic, Gemma hears the clip and names the colour, the robot confirms and picks that can.
Usage: python voice_grab.py [--seconds 4] [--mic plughw:2,0] [--dry] [extra grab_loop args]"""
import sys, subprocess, base64, time, re
sys.path.insert(0, "/home/unitree/g1-fetch"); sys.path.insert(0, "/home/unitree/harness/bench")
from client import timed_chat
from g1_fetch.config import load_config
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
SECONDS, MIC, DRY = arg("--seconds", 4.0), arg("--mic", "plughw:2,0", str), "--dry" in sys.argv
cfg = load_config("/home/unitree/g1-fetch/configs/pc2.yaml")
ChannelFactoryInitialize(0, str(cfg.network_interface))
ac = AudioClient(); ac.SetTimeout(5.0); ac.Init()
def say(t): print("SAY:", t, flush=True); ac.TtsMaker(t, 1)
COLORS = ["red", "green", "blue", "white", "purple", "black", "silver", "yellow", "orange", "pink"]
color = None
for attempt in range(3):
    say("Which can would you like? Tell me the colour." if attempt == 0 else "Please say the colour again.")
    time.sleep(2.8 if attempt == 0 else 1.6)
    say("Listening.")
    time.sleep(0.6)
    clip = "/home/unitree/spike/voice_order.wav"
    subprocess.run(["arecord", "-q", "-D", MIC, "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(int(SECONDS)), clip], check=True)
    b64 = base64.b64encode(open(clip, "rb").read()).decode()
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 6,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "system", "content": "You are a drinks host robot. The guest names the colour of the can they want. The guest may speak any language. Answer with the English colour word only, or none if no colour was named."},
                     {"role": "user", "content": [{"type": "text", "text": "Which colour did the guest ask for?"}, {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}]}]})
    answer = r["content"].strip().lower()
    print("Gemma heard: %r (%.2fs)" % (answer, r["total_s"]), flush=True)
    words = re.findall(r"[a-z]+", answer)
    color = next((w for w in words if w in COLORS), None)
    if color: break
if color is None:
    say("Sorry, I did not catch a colour."); print("NO COLOUR"); sys.exit(2)
say("The %s can. Coming up." % color)
if DRY:
    print("DRY: would pick", color); sys.exit(0)
extra = [a for a in sys.argv[1:] if a not in ("--dry",) and not a.startswith("--seconds") and not a.startswith("--mic")]
cmd = ["python", "/home/unitree/spike/grab_loop.py", "--color", color, "--dx", "-0.096", "--dz", "0.0", "--contact", "0.015", "--prethumb", "--pre", "0.05", "--note", "voice order %s" % color] + extra
print("RUN:", " ".join(cmd), flush=True)
sys.exit(subprocess.call(cmd, cwd="/home/unitree/g1-fetch"))
