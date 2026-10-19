import base64, sys
sys.path.insert(0, "/home/unitree/harness/bench")
from client import timed_chat
path = sys.argv[1] if len(sys.argv) > 1 else "/home/unitree/spike/mic_capture.wav"
b64 = base64.b64encode(open(path, "rb").read()).decode()
for q in ("Transcribe this audio.", "Transcribe this audio, then translate it to English."):
    payload = {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 120,
               "chat_template_kwargs": {"enable_thinking": False},
               "messages": [{"role": "user", "content": [{"type": "text", "text": q},
                                                         {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}]}]}
    r = timed_chat("http://127.0.0.1:8080/v1", payload)
    content = r["content"]; total = r["total_s"]; ptok = r["timings"].get("prompt_n")
    print(q, "->", repr(content), "total=%.2fs prompt=%s tok" % (total, ptok))
