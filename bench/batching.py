#!/usr/bin/env python3
"""Cost of batching N actions into one native tool call (text-only, thinking off, stdlib only).

The plan is dictated in the prompt, so this measures serialization cost alone:
output tokens, decode time, and when the first tool-call delta (the function name) streams out.
The prompt is identical across repeats and cached, so prefill is near zero here by design.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from client import timed_chat  # noqa: E402
from tools import encode_actions, tool_schemas  # noqa: E402

SEQUENCE = ["turn_left", "forward", "forward", "turn_right", "forward", "forward", "left", "forward"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="gemma4-e2b")
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()
    table = []
    print("format    actions out_tok decode_ms total_ms first_delta_ms ms_per_action exact")
    for format_name in ("plan", "atomic"):
        for count in (1, 2, 4, 8):
            actions = SEQUENCE[:count]
            wanted = [json.loads(call["function"]["arguments"]) | {"name": call["function"]["name"]}
                      for call in encode_actions(actions, format_name)]
            rows = []
            for seed in range(args.repeat + 1):
                result = timed_chat(args.base_url, {
                    "model": args.model, "seed": seed, "temperature": 0, "top_k": 1, "cache_prompt": True,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "tools": tool_schemas(format_name, 8), "tool_choice": "auto", "parallel_tool_calls": True,
                    "messages": [
                        {"role": "system", "content": "Output only tool calls."},
                        {"role": "user", "content": "Run exactly these robot actions in this order: "
                         + ", ".join(actions) + "."}]})
                got = [json.loads(call["arguments"] or "{}") | {"name": call["name"]}
                       for call in result["tool_calls"]]
                result["exact"] = got == wanted
                if seed:  # first request warms the prompt prefix
                    rows.append(result)
            median = lambda pick: statistics.median(pick(row) for row in rows)  # noqa: E731
            total = median(lambda row: row["total_s"]) * 1000
            table.append({"format": format_name, "actions": count,
                          "output_tokens": median(lambda row: row["timings"]["predicted_n"]),
                          "decode_ms": round(median(lambda row: row["timings"]["predicted_ms"]), 1),
                          "total_ms": round(total, 1),
                          "first_delta_ms": round(median(lambda row: row["first_call_s"]) * 1000, 1),
                          "exact": sum(row["exact"] for row in rows), "n": len(rows)})
            print(f"{format_name:9s} {count:7d} {median(lambda row: row['timings']['predicted_n']):7.0f} "
                  f"{median(lambda row: row['timings']['predicted_ms']):9.1f} {total:8.1f} "
                  f"{median(lambda row: row['first_call_s']) * 1000:14.1f} {total / count:13.1f} "
                  f"{sum(row['exact'] for row in rows)}/{len(rows)}", flush=True)
    out_dir = ROOT / "experiments" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}-batching"
    out_dir.mkdir(parents=True)
    (out_dir / "table.json").write_text(json.dumps(table, indent=2) + "\n")
    print(f"Saved: {out_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
