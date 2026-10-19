import sys, time, base64, json, cv2
sys.path.insert(0, "/home/unitree/harness/bench")
from client import timed_chat
cap = cv2.VideoCapture("/dev/video6", cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
ok = False
for i in range(15):
    ok, frame = cap.read()
cap.release()
print("frame ok:", ok, None if not ok else frame.shape)
if not ok: sys.exit(1)
cv2.imwrite("/home/unitree/spike/usbcam.jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
small = cv2.resize(frame, (480, 336), interpolation=cv2.INTER_AREA)
cv2.imwrite("/home/unitree/spike/usbcam-480x336.jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
b64 = base64.b64encode(open("/home/unitree/spike/usbcam-480x336.jpg", "rb").read()).decode()
def ask(text, max_tokens=60, prefill=None, stop=None):
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}, {"type": "text", "text": text}]}]
    if prefill: msgs.append({"role": "assistant", "content": prefill})
    p = {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": max_tokens,
         "chat_template_kwargs": {"enable_thinking": False}, "messages": msgs}
    if stop: p["stop"] = stop
    r = timed_chat("http://127.0.0.1:8080/v1", p)
    print(text, "->", repr((prefill or "") + r["content"]), "total=%.2fs" % r["total_s"])
ask("Describe what the camera sees in one short sentence.")
ask("Is a person visible? Answer with one word: yes or no.", max_tokens=3)
ask("Detect the person.", max_tokens=24, prefill='{"box_2d": [', stop=["]"])
