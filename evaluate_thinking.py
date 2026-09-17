#!/usr/bin/env python3
"""Compare off/normal/brief reasoning with a fixed plan tool. See THINKING_HYPOTHESIS.md."""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import random
import statistics

from evaluate_formats import aggregate, successful
from run import ROOT, THINKING_MODES, add_common_arguments, evaluation_sampling, request_json, run, save


def summarize(rows):
    result = {}
    for mode in THINKING_MODES:
        group = [row for row in rows if row["thinking"] == mode]
        if not group:
            continue
        item = aggregate(group)["cold"]["plan"]
        correct = [row["total_request_seconds"] for row in group if successful(row)]
        item["successful_plan_median_s"] = statistics.median(correct) if correct else None
        result[mode] = item
    return result


def select_mode(aggregates):
    def rank(mode):
        row = aggregates[mode]
        latency = row["successful_plan_median_s"]
        if latency is None:
            latency = row["metrics"]["wall_s"]["median"]
        return -row["successes"], latency
    return min(aggregates, key=rank)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--start-seed", type=int, default=301)
    args = parser.parse_args()
    if args.repeats < 1 or args.max_actions < 1 or not args.base_url.rstrip("/").endswith("/v1"):
        parser.error("Use positive counts and a base URL ending in /v1")
    base = args.base_url.rstrip("/")[:-3]
    output = ROOT / "experiments" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-thinking")
    output.mkdir(parents=True)
    props = request_json(base + "/props")
    save(output / "server-props.json", props)
    (output / "active-chat-template.jinja").write_text(props["chat_template"])
    sources = ["run.py", "tools.py", "evaluate_formats.py", "evaluate_thinking.py", "request-defaults.json",
               "runner-defaults.json", "evaluation-sampling.json", "cases.json", "THINKING_HYPOTHESIS.md",
               "prompts/system.txt", "prompts/user.txt", "prompts/brief-thinking.txt"]
    for relative in sources:
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    save(output / "manifest.json", {
        "arguments": {key: str(value) if key == "prompt_file" else value for key, value in vars(args).items()},
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
        "template_sha256": hashlib.sha256(props["chat_template"].encode()).hexdigest(),
        "sampling": evaluation_sampling(), "scheduler_seed": 20260918,
        "selection_rule": "Maximum successes; ties lowest median wall latency on successes, or all trials if none succeed.",
    })
    cases = json.loads((ROOT / "cases.json").read_text())
    blocks = [(seed, case) for seed in range(args.start_seed, args.start_seed + args.repeats) for case in cases]
    rng = random.Random(20260918)
    rng.shuffle(blocks)
    schedule = []
    for seed, case in blocks:
        modes = list(THINKING_MODES)
        rng.shuffle(modes)
        schedule.extend({"seed": seed, "case": case, "thinking": mode, "format": "plan", "cache_mode": "cold"}
                        for mode in modes)
    save(output / "schedule.json", schedule)
    rows = []
    print(f"Experiment: {output}; {len(schedule)} requests", flush=True)
    for index, item in enumerate(schedule, 1):
        local = copy.copy(args)
        local.format, local.seed, local.thinking, local.cache = "plan", item["seed"], item["thinking"], "off"
        run_dir = output / f'{index:03d}-{item["case"]}-{item["thinking"]}'
        run_dir.mkdir()
        try:
            row = run(local, run_dir, item["case"], cases[item["case"]], props=props,
                      overrides=evaluation_sampling(), quiet=True)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as error:
            row = {"error": str(error), "protocol_ok": False}
            save(run_dir / "error.json", row)
        row.update(item, run_dir=str(run_dir))
        rows.append(row)
        save(output / "trials.json", rows)
        save(output / "aggregate.json", summarize(rows))
        print(json.dumps({"trial": index, "total": len(schedule), **item,
                          "actions": row.get("actions"), "success": successful(row),
                          "seconds": round(row.get("total_request_seconds", 0), 3),
                          "tokens": row.get("usage", {}).get("completion_tokens"),
                          "reasoning_tokens": row.get("reasoning_text_tokens"), "error": row.get("error")}), flush=True)
    final_props = request_json(base + "/props")
    template_same = final_props["chat_template"] == props["chat_template"]
    errors = any(row.get("error") for row in rows)
    if errors or not template_same:
        save(output / "selection.json", {"selected": None, "errors": errors, "template_unchanged": template_same})
        return 1
    selected = select_mode(summarize(rows))
    save(output / "selection.json", {"selected": selected, "template_unchanged": True,
                                      "note": "Provisional mode selection on these three images with the plan schema."})
    print(f"Selected mode: {selected}; results: {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
