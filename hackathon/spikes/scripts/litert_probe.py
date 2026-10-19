"""LiteRT-LM persistent-engine probe on PC2 (CPU): load once, then time text, audio transcription and audio->order() tool call."""
import json, sys, time, traceback
from pathlib import Path
import litert_lm as L

M = str(Path.home() / "litert/gemma-4-E2B-it.litertlm")
CLIPS = sorted((Path.home() / "spike/clips").glob("*.wav"))
threads = int(sys.argv[1]) if len(sys.argv) > 1 else 4
NOTHINK = L.ThinkingConfig(enable_thinking=False)
SYSTEM = ("You are a drinks host robot. A guest asks for a can in any language. "
          "Call order with the can they want and the language they spoke. If no can is requested or you are unsure, call unsure.")
CALLS = []

def order(item: str, language: str) -> str:
    """Register the guest's drink order.

    Args:
        item: The can the guest asked for: red_can, green_can, blue_can, or other.
        language: The language the guest spoke: en, zh, es, or other.
    """
    CALLS.append({"tool": "order", "item": item, "language": language})
    return "ok"

def unsure() -> str:
    """The request was not understood; ask the guest to repeat."""
    CALLS.append({"tool": "unsure"})
    return "ok"

t0 = time.perf_counter()
engine = L.Engine(M, backend=L.Backend.CPU(thread_count=threads), audio_backend=L.Backend.CPU(),
                  vision_backend=L.Backend.CPU(), max_num_tokens=2048, cache_dir=str(Path.home() / "litert/cache"))
print(f"engine load {time.perf_counter()-t0:.1f}s threads={threads}", flush=True)

def timed(label, fn):
    t = time.perf_counter()
    try:
        r = fn()
        dt = time.perf_counter() - t
        print(f"{label}: {dt:.2f}s -> {str(r)[:160]!r}", flush=True)
        return r, dt
    except Exception:
        print(f"{label}: FAILED\n{traceback.format_exc()[-600:]}", flush=True)
        return None, None

# 1. text turn (twice: cold then warm)
for i in range(2):
    conv = engine.create_conversation(messages=[{"role": "system", "content": "Reply with one word."}], thinking_config=NOTHINK)
    timed(f"text turn {i}", lambda: conv.send_message("Say meow."))
    try: print("   bench:", conv.get_benchmark_info(), flush=True)
    except Exception as e: print("   bench n/a", e)
    conv.close()

# 2. audio transcription per clip
for clip in CLIPS:
    conv = engine.create_conversation(thinking_config=NOTHINK)
    timed(f"transcribe {clip.name}", lambda: conv.send_message(L.Contents([L.Content.Text("Transcribe this audio."), L.Content.AudioFile(str(clip))])))
    conv.close()

# 3. audio -> order() tool call, automatic tool calling on (the function records the call)
for clip in CLIPS:
    CALLS.clear()
    conv = engine.create_conversation(messages=[{"role": "system", "content": SYSTEM}], tools=[order, unsure], thinking_config=NOTHINK)
    r, dt = timed(f"order {clip.name}", lambda: conv.send_message(L.Contents([L.Content.Text("Take the order from this audio."), L.Content.AudioFile(str(clip))])))
    print(f"   calls: {CALLS}", flush=True)
    try: print("   bench:", conv.get_benchmark_info(), flush=True)
    except Exception as e: print("   bench n/a", e)
    conv.close()
engine.close()
