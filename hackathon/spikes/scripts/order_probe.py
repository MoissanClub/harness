"""Audio ORDER probe for the Orin: spoken clip -> native Gemma tool call. Stdlib only.
Usage: python3 order_probe.py [--rounds N] [--mixed] ; expects llama-server at 127.0.0.1:8080 and clips in ~/spike/clips."""
import base64, json, sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path.home() / "harness/bench"))
from client import timed_chat, image_part  # noqa: E402

BASE = "http://127.0.0.1:8080/v1"
CLIPS = Path.home() / "spike/clips"
OUT = Path.home() / "spike/order_results.jsonl"
EXPECT = {"en_green": ("green_can", "en"), "en_red": ("red_can", "en"), "en_blue": ("blue_can", "en"),
          "zh_green": ("green_can", "zh"), "es_red": ("red_can", "es"), "en_other": ("other", "en")}
SYSTEM = ("You are a drinks host robot. A guest asks for a can in any language. "
          "Call order with the can they want and the language they spoke. "
          "If no can is requested or you are unsure, call unsure.")
TOOLS = [
    {"type": "function", "function": {"name": "order", "description": "Register the guest's drink order.",
     "parameters": {"type": "object", "properties": {
         "item": {"type": "string", "enum": ["red_can", "green_can", "blue_can", "other"],
                  "description": "The can the guest asked for, or other."},
         "language": {"type": "string", "enum": ["en", "zh", "es", "other"],
                      "description": "Language the guest spoke."}}, "required": ["item", "language"]}}},
    {"type": "function", "function": {"name": "unsure", "description": "The request was not understood.",
     "parameters": {"type": "object", "properties": {}}}},
]
BASE_PAYLOAD = {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1,
                "max_tokens": 64, "chat_template_kwargs": {"enable_thinking": False}, "tools": TOOLS}


def audio_part(path):
    return {"type": "input_audio", "input_audio": {"data": base64.b64encode(path.read_bytes()).decode(), "format": "wav"}}


def order_payload(clip, image=None):
    content = [{"type": "text", "text": "Take the order from this audio."}]
    if image is not None:
        content.insert(0, image_part(image))
    content.append(audio_part(clip))
    return {**BASE_PAYLOAD, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]}


def main():
    rounds = int(sys.argv[sys.argv.index("--rounds") + 1]) if "--rounds" in sys.argv else 2
    mixed = "--mixed" in sys.argv
    clips = sorted(CLIPS.glob("*.wav"))
    image = next(iter(sorted(CLIPS.glob("*.jpg"))), None)
    rows = []
    # warm-up on the last clip (untimed), then rotate clips so no two consecutive requests share audio
    timed_chat(BASE, order_payload(clips[-1]))
    for r in range(rounds):
        for clip in clips:
            res = timed_chat(BASE, order_payload(clip))
            call = res["tool_calls"][0] if res["tool_calls"] else None
            args = {}
            if call:
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": call["arguments"]}
            exp_item, exp_lang = EXPECT.get(clip.stem, (None, None))
            got_item = args.get("item") if call and call["name"] == "order" else ("other" if call and call["name"] == "unsure" else None)
            row = {"round": r, "clip": clip.name, "tool": call["name"] if call else None, "args": args,
                   "content": res["content"][:200], "finish": res["finish_reason"],
                   "item_ok": got_item == exp_item, "lang_ok": args.get("language") == exp_lang,
                   "total_s": round(res["total_s"], 3), "ttft_s": round(res["ttft_s"], 3) if res["ttft_s"] else None,
                   "timings": {k: res["timings"].get(k) for k in ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms", "cache_n")}}
            rows.append(row)
            print(f"{clip.name:14s} -> {row['tool']} {args} item_ok={row['item_ok']} lang_ok={row['lang_ok']} "
                  f"total={row['total_s']}s prompt={row['timings']['prompt_n']}tok/{row['timings']['prompt_ms']}ms "
                  f"gen={row['timings']['predicted_n']}tok/{row['timings']['predicted_ms']}ms", flush=True)
    if mixed and image is not None:
        res = timed_chat(BASE, order_payload(clips[0], image))
        print("MIXED image+audio:", res["tool_calls"], res["content"][:200], f"total={res['total_s']:.3f}s", res["timings"], flush=True)
        rows.append({"mixed": True, "tool_calls": res["tool_calls"], "content": res["content"][:200], "total_s": res["total_s"], "timings": res["timings"]})
    with OUT.open("a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    scored = [r for r in rows if "clip" in r]
    tot = [r["total_s"] for r in scored]
    print(f"\nitem correct {sum(r['item_ok'] for r in scored)}/{len(scored)}, language correct {sum(r['lang_ok'] for r in scored)}/{len(scored)}, "
          f"total p50 {statistics.median(tot):.3f}s max {max(tot):.3f}s")


if __name__ == "__main__":
    main()
