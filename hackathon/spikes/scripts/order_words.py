"""Variant probe: spoken order -> two-word text answer (no tool syntax), plus an unsure-aware tool prompt. Stdlib only."""
import base64, json, sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path.home() / "harness/bench"))
from client import timed_chat  # noqa: E402
BASE = "http://127.0.0.1:8080/v1"
CLIPS = sorted((Path.home() / "spike/clips").glob("*.wav"))
EXPECT = {"en_green": ("green", "en"), "en_red": ("red", "en"), "en_blue": ("blue", "en"),
          "zh_green": ("green", "zh"), "es_red": ("red", "es"), "en_other": ("none", "en")}
BASEP = {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1,
         "chat_template_kwargs": {"enable_thinking": False}}
WORDS_SYSTEM = ("You are a drinks host robot. A guest may ask for a can in any language. "
                "Answer with exactly two words: the can colour (red, green, blue, or none if no can was requested) "
                "and the language code the guest spoke (en, zh, es, or other).")
TOOLS = json.loads(Path.home().joinpath("spike/tools.json").read_text()) if Path.home().joinpath("spike/tools.json").exists() else None

def audio_part(p):
    return {"type": "input_audio", "input_audio": {"data": base64.b64encode(p.read_bytes()).decode(), "format": "wav"}}

def run(label, make_payload, score):
    timed_chat(BASE, make_payload(CLIPS[-1]))  # warm-up
    rows = []
    for r in range(2):
        for clip in CLIPS:
            res = timed_chat(BASE, make_payload(clip))
            ok = score(clip, res)
            rows.append((clip.name, ok, res["total_s"], res["timings"].get("prompt_n"), res["timings"].get("predicted_n"), (res["content"] or json.dumps(res["tool_calls"]))[:60]))
    for row in rows: print(f"  {row[0]:13s} ok={row[1]} total={row[2]:.3f}s prompt={row[3]} out={row[4]} -> {row[5]!r}")
    tot = [r[2] for r in rows]
    print(f"{label}: correct {sum(r[1] for r in rows)}/{len(rows)}, p50 {statistics.median(tot):.3f}s max {max(tot):.3f}s\n", flush=True)

def words_payload(clip):
    return {**BASEP, "max_tokens": 6, "messages": [{"role": "system", "content": WORDS_SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": "What did the guest ask for?"}, audio_part(clip)]}]}

def words_score(clip, res):
    w = res["content"].strip().lower().replace(",", " ").split()
    exp = EXPECT[clip.stem]
    return len(w) >= 2 and w[0] == exp[0] and w[1] == exp[1]

print("== two-word answer, question before the audio")
run("two-word", words_payload, words_score)
