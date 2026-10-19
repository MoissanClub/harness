"""See a soda can with the head camera: YOLOE and Gemma boxes on the same frame, depth to a pelvis-frame point, left-arm IK feasibility. No motion."""
import sys, re, base64, json, time
import numpy as np, cv2
sys.path.insert(0, "/home/unitree/g1-fetch"); sys.path.insert(0, "/home/unitree/harness/bench")
from client import timed_chat
from g1_fetch.config import load_config
cfg = load_config("configs/pc2.yaml")
from g1_fetch.perception.detector import build_detector, Detection
from g1_fetch.perception.camera import RealSenseCamera
from g1_fetch.perception.localize import can_axis_from_box
from g1_fetch.frames import Frames
from g1_fetch.control.arm import ArmKinematics
OUT = "/home/unitree/spike/"
det = build_detector(cfg)
for _ in range(2): det.detect(np.zeros((480, 640, 3), np.uint8))      # warm the engines before the camera opens
frames = Frames(cfg); kin = ArmKinematics(cfg)
cam = RealSenseCamera(cfg)
for _ in range(12): f = cam.read()
color = f.color
cv2.imwrite(OUT + "see_color.jpg", color, [cv2.IMWRITE_JPEG_QUALITY, 90])
small = cv2.resize(color, (480, 336), interpolation=cv2.INTER_AREA)
cv2.imwrite(OUT + "see_480x336.jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
depth_valid = float((f.depth > 0).mean())
print(f"frame {color.shape} depth valid {depth_valid:.0%}", flush=True)
# YOLOE
t = time.perf_counter(); dets = det.detect(color); dt = (time.perf_counter() - t) * 1e3
print(f"YOLOE {dt:.0f} ms: " + ", ".join(f"{d.label} {d.conf:.2f} {tuple(int(v) for v in d.box)}" for d in dets), flush=True)
cans = sorted([d for d in dets if d.label == "can"], key=lambda d: -d.conf)
p_yolo = can_axis_from_box(f, cans[0], frames, cfg) if cans else None
# Gemma
b64 = base64.b64encode(open(OUT + "see_480x336.jpg", "rb").read()).decode()
def ask(text, max_tokens, prefill=None, stop=None, system=None):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}, {"type": "text", "text": text}]}]
    if prefill: msgs.append({"role": "assistant", "content": prefill})
    p = {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": max_tokens,
         "chat_template_kwargs": {"enable_thinking": False}, "messages": msgs}
    if stop: p["stop"] = stop
    r = timed_chat("http://127.0.0.1:8080/v1", p)
    return r["content"], r["total_s"]
gate, dt = ask("Is there a soda can in the image? Answer with one word: yes or no.", 3, system="You are a robot's vision module. Image left/right are robot left/right.")
print(f"Gemma gate: {gate.strip()!r} {dt:.2f}s", flush=True)
BOX_USER = ('Detect the soda can. Output only JSON: [{"box_2d": [ymin, xmin, ymax, xmax], "label": "soda can"}] with coordinates normalized to 0-1000.')
txt, dt = ask(BOX_USER, 24, prefill='```json\n[\n  {"box_2d": [', stop=["]"])
nums = [int(n) for n in re.findall(r"\d+", txt[txt.rindex("[") + 1:])][:4] if "[" in txt else []
print(f"Gemma box raw {txt!r} -> {nums} {dt:.2f}s", flush=True)
p_gemma = None
if len(nums) == 4:
    y1, x1, y2, x2 = nums
    box = (x1 / 1000 * 640, y1 / 1000 * 480, x2 / 1000 * 640, y2 / 1000 * 480)
    dg = Detection("can", 1.0, box, "gemma")
    p_gemma = can_axis_from_box(f, dg, frames, cfg)
    vis = color.copy(); cv2.rectangle(vis, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 255, 0), 2)
    for d in cans: cv2.rectangle(vis, (int(d.box[0]), int(d.box[1])), (int(d.box[2]), int(d.box[3])), (255, 0, 0), 2)
    cv2.imwrite(OUT + "see_boxes.jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 90])
palm, x_dir, r = np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]), float(cfg.fridge.can_diameter_m) / 2
for name, p in (("YOLOE", p_yolo), ("Gemma", p_gemma)):
    if p is None:
        print(f"{name}: no 3D point", flush=True); continue
    hand_p = p - palm * (r + 0.01)
    res = kin.ik("left", hand_p, x_dir, dir_weight=float(cfg.arm.ik_dir_weight))
    info = {k: (np.round(v, 3).tolist() if isinstance(v, np.ndarray) else (round(v, 4) if isinstance(v, float) else v)) for k, v in vars(res).items()}
    print(f"{name}: can axis pelvis {np.round(p, 3).tolist()} floor height {frames.floor_height(p):.2f} m; hand target {np.round(hand_p, 3).tolist()}; IK {info}", flush=True)
if p_yolo is not None and p_gemma is not None:
    print(f"YOLOE vs Gemma point difference {np.round(p_gemma - p_yolo, 3).tolist()} m (norm {np.linalg.norm(p_gemma - p_yolo):.3f})", flush=True)
cam.close()
