"""No-motion scene read: YOLOE can boxes with widths, Gemma colour list and per-colour gates."""
import sys, base64, numpy as np, cv2
sys.path.insert(0, "/home/unitree/g1-fetch"); sys.path.insert(0, "/home/unitree/harness/bench")
from client import timed_chat
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml"); cfg.cameras.head.enabled = False
from g1_fetch.perception.detector import build_detector
from g1_fetch.perception.camera import RealSenseCamera
from g1_fetch.perception.localize import median_depth, can_axis_from_box
from g1_fetch.frames import Frames
det = build_detector(cfg)
for _ in range(2): det.detect(np.zeros((480, 640, 3), np.uint8))
frames = Frames(cfg); cam = RealSenseCamera(cfg)
for _ in range(12): f = cam.read()
cans = sorted([d for d in det.detect(f.color) if d.label == "can"], key=lambda d: d.box[0])
for d in cans:
    z = median_depth(f, d.box, 0.5); p = can_axis_from_box(f, d, frames, cfg)
    print("YOLOE can conf %.2f box %s depth %.2f m width %.3f m pelvis %s" % (d.conf, tuple(int(v) for v in d.box), z or -1, (d.width * z / f.intrinsics.fx) if z else -1, None if p is None else np.round(p, 3).tolist()), flush=True)
cv2.imwrite("/home/unitree/spike/scene.jpg", f.color, [cv2.IMWRITE_JPEG_QUALITY, 90])
small = cv2.resize(f.color, (480, 336), interpolation=cv2.INTER_AREA); ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85]); b64 = base64.b64encode(buf.tobytes()).decode()
def ask(text, max_tokens=24):
    r = timed_chat("http://127.0.0.1:8080/v1", {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False}, "messages": [{"role": "system", "content": "You are a robot's vision module. Image left/right are robot left/right."},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}, {"type": "text", "text": text}]}]})
    print("%s -> %r (%.2fs)" % (text, r["content"].strip(), r["total_s"]), flush=True)
    return r["content"].strip().lower()
ask("How many soda cans are on the table? Answer with a number only.", 3)
ask("List the main colour of each soda can from left to right, comma separated, colour words only.", 16)
for c in ("red", "green", "blue", "white", "black", "silver"):
    ask("Is there a %s can in the image? Answer with one word: yes or no." % c, 3)
cam.close()
