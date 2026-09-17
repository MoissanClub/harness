#!/usr/bin/env python3
"""Compare tool serialization with an explicit two-action, text-only instruction."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import random
import statistics
from types import SimpleNamespace

from run import ROOT, build_payload, complete, evaluate_response, request_json, save
from tools import FORMATS

PROMPT = "Rotate left in place, then translate forward one step. Include both actions in this response."
EXPECTED_ACTIONS = ["turn_left", "forward"]
SAMPLING = {"temperature": 1.0, "top_k": 64, "top_p": 0.95, "min_p": 0.0}
SEEDS = (201, 202, 203)
SCHEDULER_SEED = 20260917


def summarize(rows):
    result = {}
    for cache in ("cold", "warm"):
        result[cache] = {}
        for format_name in FORMATS:
            group = [r for r in rows if r["cache_mode"] == cache and r["format"] == format_name]
            if not group:
                continue
            measured = [r for r in group if "total_request_seconds" in r]
            metrics = {}
            fields = {
                "wall_s": lambda r: r["total_request_seconds"],
                "prompt_tokens": lambda r: r["usage"]["prompt_tokens"],
                "completion_tokens": lambda r: r["usage"]["completion_tokens"],
                "cached_tokens": lambda r: r["timings"]["cache_n"],
                "evaluated_prompt_tokens": lambda r: r["timings"]["prompt_n"],
                "prefill_ms": lambda r: r["timings"]["prompt_ms"],
                "decode_ms": lambda r: r["timings"]["predicted_ms"],
                "decode_tokens_s": lambda r: r["timings"]["predicted_per_second"],
            }
            for name, getter in fields.items():
                values = []
                for row in measured:
                    try:
                        values.append(getter(row))
                    except KeyError:
                        pass
                if values:
                    metrics[name] = {"median": statistics.median(values),
                                     "mean": statistics.mean(values),
                                     "min": min(values), "max": max(values)}
            correct = [r for r in measured if r.get("success")]
            result[cache][format_name] = {
                "n": len(group), "successes": len(correct),
                "protocol_ok": sum(r.get("protocol_ok", False) for r in group),
                "only_tool_output": sum(r.get("only_tool_output", False) for r in group),
                "metrics": metrics,
                "correct_plan_median_wall_s": statistics.median(
                    r["total_request_seconds"] for r in correct) if correct else None,
            }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="gemma4-e4b")
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    if not args.base_url.endswith("/v1"):
        parser.error("--base-url must end in /v1")
    output = ROOT / "experiments" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-serialization")
    output.mkdir(parents=True)
    props = request_json(args.base_url[:-3] + "/props", timeout=15)
    save(output / "server-props.json", props)
    (output / "active-chat-template.jinja").write_text(props["chat_template"])
    (output / "prompt.txt").write_text(PROMPT + "\n")
    sources = ["serialize_formats.py", "run.py", "tools.py", "request-defaults.json",
               "prompts/system.txt", "prompts/user.txt", "cases.json"]
    for relative in sources:
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    save(output / "manifest.json", {
        "arguments": vars(args), "prompt": PROMPT, "expected_actions": EXPECTED_ACTIONS,
        "max_actions": 4, "sampling": SAMPLING, "seeds": SEEDS,
        "scheduler_seed": SCHEDULER_SEED,
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in sources},
        "design": "Text-only explicit sequence; each shuffled format/seed pair is cold then identical warm.",
        "cache_note": "Cold disables prompt KV reuse, not all runtime caches.",
    })
    pairs = [(seed, format_name) for seed in SEEDS for format_name in FORMATS]
    random.Random(SCHEDULER_SEED).shuffle(pairs)
    schedule = [{"seed": seed, "format": format_name, "cache_mode": cache}
                for seed, format_name in pairs for cache in ("cold", "warm")]
    save(output / "schedule.json", schedule)
    # Reuse the runner's system prompt, defaults and schemas, then replace the
    # entire user message. No image or image-derived information is sent.
    case = json.loads((ROOT / "cases.json").read_text())["center"]
    rows = []
    print(f"Experiment: {output}; {len(schedule)} requests", flush=True)
    for index, item in enumerate(schedule, 1):
        run_dir = output / f'{index:03d}-{item["format"]}-{item["cache_mode"]}'
        run_dir.mkdir()
        local = SimpleNamespace(**vars(args), format=item["format"], seed=item["seed"],
                                cache="off" if item["cache_mode"] == "cold" else "on",
                                max_actions=4, prompt_file=ROOT / "prompts/user.txt")
        try:
            payload, _ = build_payload(local, case)
            payload["messages"][1]["content"] = PROMPT
            payload.update(SAMPLING)
            save(run_dir / "input.json", {**item, "prompt": PROMPT,
                                         "expected_actions": EXPECTED_ACTIONS, "max_actions": 4})
            save(run_dir / "server-props.json", props)
            response, elapsed = complete(args.base_url, payload, run_dir)
            row, results = evaluate_response(response, elapsed, item["format"], 4)
            row["exact_plan_match"] = row["actions"] == EXPECTED_ACTIONS
            row["success"] = row["only_tool_output"] and row["exact_plan_match"]
            save(run_dir / "turn-01-tool-results.json", results)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as error:
            row = {"error": str(error), "protocol_ok": False, "success": False}
            save(run_dir / "error.json", row)
        row.update(item, run_dir=str(run_dir))
        save(run_dir / "summary.json", row)
        rows.append(row)
        save(output / "trials.json", rows)
        save(output / "aggregate.json", summarize(rows))
        print(json.dumps({"trial": index, "total": len(schedule), **item,
                          "actions": row.get("actions"), "success": row["success"],
                          "seconds": round(row.get("total_request_seconds", 0), 3),
                          "tokens": row.get("usage", {}).get("completion_tokens"),
                          "error": row.get("error")}), flush=True)
    print(f"Saved experiment: {output}", flush=True)
    return int(any(row.get("error") for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
