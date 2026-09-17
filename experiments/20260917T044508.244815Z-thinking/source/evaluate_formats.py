#!/usr/bin/env python3
"""Paired cold/warm tool-format comparison. See FORMAT_HYPOTHESIS.md."""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import random
import statistics

from run import ROOT, add_common_arguments, build_payload, evaluation_sampling, request_json, run, save
from tools import FORMATS, encode_actions


def count_tokens(base, text):
    return len(request_json(base + "/tokenize", {
        "content": text, "add_special": False, "parse_special": True,
    })["tokens"])


def inspect_encodings(args, output):
    """Let the installed template serialize known calls; do not hand-count JSON."""
    base = args.base_url.rstrip("/")[:-3]
    case = json.loads((ROOT / "cases.json").read_text())["center"]
    counts = {}
    for format_name in FORMATS:
        local = copy.copy(args)
        local.format, local.seed, local.cache = format_name, None, "default"
        payload, _ = build_payload(local, case)
        # Text-only inspection excludes random media placeholder tokenization.
        payload["messages"][1]["content"] = args.prompt_file.read_text().strip()
        rendered = request_json(base + "/apply-template", payload)["prompt"]
        (output / f"{format_name}-prompt.txt").write_text(rendered)
        empty = copy.deepcopy(payload)
        empty["tools"] = []
        empty_rendered = request_json(base + "/apply-template", empty)["prompt"]
        counts[format_name] = {
            "text_prompt_tokens": count_tokens(base, rendered),
            "tool_declaration_increment_tokens": count_tokens(base, rendered) - count_tokens(base, empty_rendered),
            "reference_outputs": {},
        }
        for name, actions in {"one": ["forward"], "two": ["turn_left", "forward"],
                              "four": ["turn_left", "forward", "turn_right", "forward"]}.items():
            example = copy.deepcopy(payload)
            calls = encode_actions(actions, format_name)
            example["messages"].append({"role": "assistant", "content": "", "tool_calls": calls})
            # A trailing assistant message is treated as prefill by this server.
            # Supply dummy tool results for rendering, then cut before their content.
            example["messages"].extend({"role": "tool", "tool_call_id": call["id"], "content": "{}"}
                                       for call in calls)
            example["add_generation_prompt"] = False
            formatted = request_json(base + "/apply-template", example)["prompt"]
            if not formatted.startswith(rendered):
                raise ValueError("Unexpected template prefix: cannot isolate native output")
            native = formatted[len(rendered):].split("<|tool_response>", 1)[0] + "<|tool_response>"
            counts[format_name]["reference_outputs"][name] = {
                "actions": actions, "native_text": native, "tokens": count_tokens(base, native),
            }
    save(output / "encoding-counts.json", counts)


def aggregate(rows):
    result = {}
    for cache in ("cold", "warm"):
        result[cache] = {}
        for format_name in FORMATS:
            group = [row for row in rows if row["cache_mode"] == cache and row["format"] == format_name]
            if not group:
                continue
            metrics = {}
            getters = {
                "wall_s": lambda row: row["total_request_seconds"],
                "prompt_tokens": lambda row: row["usage"]["prompt_tokens"],
                "completion_tokens": lambda row: row["usage"]["completion_tokens"],
                "cached_tokens": lambda row: row["timings"]["cache_n"],
                "evaluated_prompt_tokens": lambda row: row["timings"]["prompt_n"],
                "prefill_ms": lambda row: row["timings"]["prompt_ms"],
                "decode_ms": lambda row: row["timings"]["predicted_ms"],
                "decode_tokens_s": lambda row: row["timings"]["predicted_per_second"],
                "reasoning_text_tokens": lambda row: row.get("reasoning_text_tokens", 0),
            }
            for name, getter in getters.items():
                values = [getter(row) for row in group if row.get("timings")]
                if values:
                    metrics[name] = {"median": statistics.median(values), "mean": statistics.mean(values),
                                     "min": min(values), "max": max(values)}
            result[cache][format_name] = {
                "n": len(group), "protocol_ok": sum(row.get("protocol_ok", False) for row in group),
                "only_tool_output": sum(row.get("only_tool_output", False) for row in group),
                "tool_only_answer": sum(row.get("tool_only_answer", row.get("only_tool_output", False)) for row in group),
                "successes": sum(successful(row) for row in group),
                "scenes": {case: {
                    "n": sum(row["case"] == case for row in group),
                    "successes": sum(row["case"] == case and successful(row)
                                     for row in group),
                } for case in ("center", "left", "right")},
                "metrics": metrics,
            }
    # Matched canonical sequences isolate cost from action omission/repetition.
    matched = {}
    for row in rows:
        if row.get("protocol_ok"):
            key = row["cache_mode"] + ":" + ",".join(row["actions"])
            matched.setdefault(key, {}).setdefault(row["format"], []).append(row)
    result["same_plan"] = {
        key: {fmt: {"n": len(group),
                    "median_wall_s": statistics.median(r["total_request_seconds"] for r in group),
                    "median_completion_tokens": statistics.median(r["usage"]["completion_tokens"] for r in group)}
              for fmt, group in groups.items()}
        for key, groups in matched.items() if len(groups) > 1
    }
    return result


def successful(row):
    return bool(row.get("tool_only_answer", row.get("only_tool_output", False))
                and row.get("thinking_compliant", True)
                and row.get("assessment", {}).get("qualitative_goal_match", False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument("--start-seed", type=int, default=101)
    parser.add_argument("--cache-modes", choices=("cold", "paired"), default="paired")
    args = parser.parse_args()
    if args.repeats < 1 or args.max_actions < 1 or not args.base_url.rstrip("/").endswith("/v1"):
        parser.error("Use positive counts and a base URL ending in /v1")
    output = ROOT / "experiments" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True)
    props = request_json(args.base_url.rstrip("/")[:-3] + "/props")
    save(output / "server-props.json", props)
    (output / "active-chat-template.jinja").write_text(props["chat_template"])
    sources = ["run.py", "tools.py", "evaluate_formats.py", "request-defaults.json", "cases.json",
               "FORMAT_HYPOTHESIS.md", "THINKING_HYPOTHESIS.md", "runner-defaults.json", "evaluation-sampling.json",
               "prompts/system.txt", "prompts/user.txt", "prompts/brief-thinking.txt"]
    for relative in sources:
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    save(output / "manifest.json", {
        "arguments": {key: str(value) if key == "prompt_file" else value for key, value in vars(args).items()},
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
        "scheduler_seed": 20260917, "sampling": evaluation_sampling(),
        "design": "Randomized format order; cold-only or paired cold/warm as specified; one model response each.",
    })
    inspect_encodings(args, output)
    cases = json.loads((ROOT / "cases.json").read_text())
    rng = random.Random(20260917)
    rows = []
    schedule = []
    blocks = [(seed, case) for seed in range(args.start_seed, args.start_seed + args.repeats) for case in cases]
    rng.shuffle(blocks)
    for seed, case_name in blocks:
        formats = list(FORMATS)
        rng.shuffle(formats)
        for format_name in formats:
            for cache_mode in (("cold", "warm") if args.cache_modes == "paired" else ("cold",)):
                schedule.append({"seed": seed, "case": case_name, "format": format_name, "cache_mode": cache_mode})
    save(output / "schedule.json", schedule)
    print(f"Experiment: {output}; {len(schedule)} requests", flush=True)
    for index, item in enumerate(schedule, 1):
        local = copy.copy(args)
        local.format, local.seed = item["format"], item["seed"]
        local.cache = "off" if item["cache_mode"] == "cold" else "on"
        run_dir = output / f'{index:03d}-{item["case"]}-{local.format}-{item["cache_mode"]}'
        run_dir.mkdir()
        try:
            row = run(local, run_dir, item["case"], cases[item["case"]], props=props, quiet=True,
                      overrides=evaluation_sampling())
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as error:
            row = {"error": str(error), "protocol_ok": False}
            save(run_dir / "error.json", row)
        row.update(item, run_dir=str(run_dir))
        rows.append(row)
        save(output / "trials.json", rows)
        save(output / "aggregate.json", aggregate(rows))
        print(json.dumps({"trial": index, "total": len(schedule), **item,
                          "actions": row.get("actions"), "success": row.get("assessment", {}).get("qualitative_goal_match"),
                          "seconds": round(row.get("total_request_seconds", 0), 3),
                          "tokens": row.get("usage", {}).get("completion_tokens"),
                          "error": row.get("error")}), flush=True)
    print(f"Saved experiment: {output}", flush=True)
    return int(any(row.get("error") for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
