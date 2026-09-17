#!/usr/bin/env python3
"""Compare tool serialization with an explicit two-action, text-only instruction."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import random
import statistics
from types import SimpleNamespace

from run import (ROOT, add_common_arguments, build_payload, complete, evaluate_response,
                 evaluation_sampling, request_json, save)
from tools import FORMATS

PROMPT = "Rotate left in place, then translate forward one step. Include both actions in this response."
EXPECTED_ACTIONS = ["turn_left", "forward"]
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
                "tool_only_answer": sum(r.get("tool_only_answer", False) for r in group),
                "thinking_compliant": sum(r.get("thinking_compliant", False) for r in group),
                "metrics": metrics,
                "correct_plan_median_wall_s": statistics.median(
                    r["total_request_seconds"] for r in correct) if correct else None,
            }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    # Keep the diagnostic's explicit sequence by default; an explicitly supplied
    # prompt file is honored, while the exact two-action assessment stays fixed.
    parser.set_defaults(prompt_file=None)
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    if not args.base_url.endswith("/v1"):
        parser.error("--base-url must end in /v1")
    if args.max_actions < len(EXPECTED_ACTIONS):
        parser.error("--max-actions must allow the diagnostic's two requested actions")
    prompt = args.prompt_file.read_text().strip() if args.prompt_file else PROMPT
    sampling = evaluation_sampling()
    output = ROOT / "experiments" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-serialization")
    output.mkdir(parents=True)
    props = request_json(args.base_url[:-3] + "/props", timeout=15)
    save(output / "server-props.json", props)
    (output / "active-chat-template.jinja").write_text(props["chat_template"])
    (output / "prompt.txt").write_text(prompt + "\n")
    sources = ["serialize_formats.py", "run.py", "tools.py", "request-defaults.json",
               "runner-defaults.json", "evaluation-sampling.json",
               "prompts/system.txt", "prompts/user.txt", "prompts/brief-thinking.txt", "cases.json"]
    for relative in sources:
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    save(output / "manifest.json", {
        "arguments": {key: str(value) if key == "prompt_file" and value is not None else value
                      for key, value in vars(args).items()},
        "prompt": prompt, "expected_actions": EXPECTED_ACTIONS,
        "max_actions": args.max_actions, "sampling": sampling, "seeds": SEEDS,
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
        local = SimpleNamespace(**{**vars(args), "format": item["format"], "seed": item["seed"],
                                   "cache": "off" if item["cache_mode"] == "cold" else "on",
                                   "prompt_file": args.prompt_file or ROOT / "prompts/user.txt"})
        try:
            payload, _ = build_payload(local, case)
            payload["messages"][1]["content"] = prompt
            payload.update(sampling)
            save(run_dir / "input.json", {**item, "prompt": prompt, "thinking": args.thinking,
                                         "expected_actions": EXPECTED_ACTIONS,
                                         "max_actions": args.max_actions})
            save(run_dir / "server-props.json", props)
            response, elapsed = complete(args.base_url, payload, run_dir)
            row, results = evaluate_response(response, elapsed, item["format"], args.max_actions)
            reasoning = response["choices"][0]["message"].get("reasoning_content") or ""
            row["thinking_compliant"] = args.thinking != "off" or not reasoning.strip()
            row["exact_plan_match"] = row["actions"] == EXPECTED_ACTIONS
            row["success"] = (row["tool_only_answer"] and row["thinking_compliant"]
                              and row["exact_plan_match"])
            save(run_dir / "turn-01-tool-results.json", results)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as error:
            row = {"error": str(error), "protocol_ok": False, "success": False}
            save(run_dir / "error.json", row)
        row.update(item, thinking=args.thinking, run_dir=str(run_dir))
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
