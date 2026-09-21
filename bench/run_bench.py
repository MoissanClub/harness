#!/usr/bin/env python3
"""Latency/accuracy sweep over request variants on the labeled fridge image set (stdlib only).

Requests are strictly serial. Consecutive requests always carry different images, so with
--cache on the server can reuse only the static text prefix, as it could with a live camera.
"""

import argparse
from datetime import datetime, timezone
import fnmatch
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from client import get_json, image_part, timed_chat  # noqa: E402
from run import assess  # noqa: E402
from variants import PARSERS, VARIANTS  # noqa: E402

SAMPLING = {
    "eval": json.loads((ROOT / "evaluation-sampling.json").read_text()),
    "greedy": {"temperature": 0.0, "top_k": 1},
}
LABEL = {"turn_left": "left", None: "center", "turn_right": "right", "absent": "none"}


def scaled_image(path, size, jpeg=False):
    """Resize without cropping, so the labeled horizontal fractions stay valid."""
    if not size and not jpeg:
        return path
    size = size or (720, 480)
    out = ROOT / f"bench/images-{size[0]}x{size[1]}" / (path.stem + (".jpg" if jpeg else ".png"))
    if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
        out.parent.mkdir(parents=True, exist_ok=True)
        options = ["-s", "format", "jpeg", "-s", "formatOptions", "85"] if jpeg else []
        subprocess.run(["sips", "-z", str(size[1]), str(size[0]), *options, str(path), "--out", str(out)],
                       check=True, capture_output=True)
    return out


def image_tokens(size):
    """llama.cpp's Gemma 4 rule: one token per 48-px cell, never fewer than the 70-token floor
    (40 when the server runs with --image-min-tokens 40, the smallest frame used here)."""
    width, height = size or (720, 480)
    return max(40, round(width / 48) * round(height / 48))


def build_payload(variant, image, model, sampling, cache, seed):
    parts = [image_part(scaled_image(image, variant["image_size"], variant["jpeg"]))]
    if variant["user"]:
        parts.append({"type": "text", "text": variant["user"]})
    if variant["order"] == "text_first":
        parts.reverse()
    messages = [{"role": "user", "content": parts}]
    if variant["system"]:
        messages.insert(0, {"role": "system", "content": variant["system"]})
    if variant["prefill"]:
        messages.append({"role": "assistant", "content": variant["prefill"]})
    payload = {"model": model, "messages": messages, "cache_prompt": cache, "seed": seed,
               "chat_template_kwargs": {"enable_thinking": variant["thinking"]}, **SAMPLING[sampling]}
    if variant["tools"]:
        payload.update(tools=variant["tools"], tool_choice="auto", parallel_tool_calls=True)
    payload.update(variant["extra"])
    return payload


def merge(first, second):
    """Fold the first request's cost into the second so totals cover the whole exchange."""
    second["first_total_s"] = first["total_s"]
    second["first_content"] = first["content"]
    for key in ("total_s", "ttft_s", "first_call_s"):  # stream marks become relative to the first send
        if second[key] is not None:
            second[key] += first["total_s"]
    second["timings"] = {**second["timings"], **{
        key: first["timings"].get(key, 0) + second["timings"].get(key, 0)
        for key in ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms")},
        "cache_n": first["timings"].get("cache_n", 0), "second_cache_n": second["timings"].get("cache_n", 0),
        "first_prompt_n": first["timings"].get("prompt_n", 0)}
    return second


def run_variant(base_url, variant, payload):
    """One timed request, or two chained on the same KV when the variant has a gate or stage2."""
    if variant.get("gate"):
        question = payload["messages"][-1]["content"][-1]["text"]
        ask = json.loads(json.dumps(payload))
        ask["messages"][-1]["content"][-1]["text"] = variant["gate"]
        ask.update(grammar='root ::= "yes" | "no"', max_tokens=3)
        first = timed_chat(base_url, ask)
        if not first["content"].strip().lower().startswith("yes"):
            first["content"] = "none"
            return first
        follow = dict(payload)
        follow["messages"] = ask["messages"] + [{"role": "assistant", "content": "yes"},
                                                {"role": "user", "content": question}]
        return merge(first, timed_chat(base_url, follow))
    result = timed_chat(base_url, payload)
    if not variant["stage2"]:
        return result
    position = result["content"].strip()
    follow = {key: value for key, value in payload.items() if key not in ("grammar", "max_tokens")}
    follow["messages"] = payload["messages"] + [
        {"role": "assistant", "content": position},
        {"role": "user", "content": variant["stage2"]["user"].format(position=position)}]
    return merge(result, timed_chat(base_url, follow))


def grade(variant, result, expected_turn):
    record = {"parsed": None, "strict": False, "permissive": False, "position_ok": None, "error": None}
    try:
        if result["finish_reason"] == "length" and variant["extra"].get("max_tokens", 0) > 8:
            raise ValueError("truncated")
        parsed = PARSERS[variant["parse"]](result)
    except Exception as error:  # malformed output is a graded failure, not a crash
        record["error"] = f"{type(error).__name__}: {error}"
        return record
    if parsed.get("position") == "seen":  # presence-only variant: right whenever a fridge is in view
        record.update(parsed=parsed, strict=expected_turn != "absent", permissive=expected_turn != "absent",
                      position_ok=expected_turn != "absent")
        return record
    if expected_turn == "absent":  # no fridge in view: the only correct output is no motion
        record.update(parsed=parsed, strict=parsed["actions"] == [], permissive=parsed["actions"] == [])
    else:
        minimal = ([expected_turn] if expected_turn else []) + ["forward"]
        record.update(parsed=parsed, strict=parsed["actions"] == minimal,
                      permissive=assess(parsed["actions"], expected_turn)["qualitative_goal_match"])
    if parsed.get("position") is not None:
        record["position_ok"] = parsed["position"] == LABEL[expected_turn]
    return record


def pct(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p, d = k / n, 1 + z * z / n
    centre, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (centre - half, centre + half)


def summarize(name, rows):
    ok = [row for row in rows if row["total_s"] is not None and not row.get("image_cache_hit")]
    total = [row["total_s"] * 1000 for row in ok] or [float("nan")]
    timing = lambda key: statistics.median([row["timings"].get(key, 0) for row in ok] or [float("nan")])  # noqa: E731
    strict = sum(row["strict"] for row in rows)
    low, high = wilson(strict, len(rows))
    by_class = {}
    for label in ("left", "center", "right", "none"):
        members = [row for row in rows if LABEL[row["expected_turn"]] == label]
        by_class[label] = f"{sum(row['strict'] for row in members)}/{len(members)}"
    positions = [row["position_ok"] for row in rows if row["position_ok"] is not None]
    x_errors = [abs(row["parsed"]["x"] - row["fridge_center_fraction"]) for row in rows
                if row["parsed"] and row["parsed"].get("x") is not None and "fridge_center_fraction" in row]
    return {
        "variant": name, "n": len(rows), "strict": strict, "strict_rate": round(strict / len(rows), 3),
        "strict_ci95": [round(low, 3), round(high, 3)],  # assumes independent rows; crops of 3 scenes are not
        "permissive": sum(row["permissive"] for row in rows), "by_class": by_class,
        "position_ok": f"{sum(positions)}/{len(positions)}" if positions else None,
        "x_mae": round(statistics.mean(x_errors), 3) if x_errors else None,
        "errors": sum(row["error"] is not None for row in rows),
        "image_cache_hits_excluded_from_latency": sum(bool(row.get("image_cache_hit")) for row in rows),
        "total_ms": {"p50": round(statistics.median(total), 1), "p90": round(pct(total, 0.9), 1),
                     "max": round(max(total), 1)},
        "first_call_ms_p50": round(statistics.median(
            row["first_call_s"] * 1000 for row in ok if row["first_call_s"] is not None), 1)
        if any(row["first_call_s"] is not None for row in ok) else None,
        "prompt_n": timing("prompt_n"), "cache_n": timing("cache_n"),
        "prompt_ms": round(timing("prompt_ms"), 1), "predicted_n": timing("predicted_n"),
        "predicted_ms": round(timing("predicted_ms"), 1),
        "under_1s": sum(value < 1000 for value in total) / len(total),
    }


def line(summary):
    ms = summary["total_ms"]
    return (f"{summary['variant']:32s} strict {summary['strict']:3d}/{summary['n']:<3d} "
            f"({summary['strict_rate']:.0%}; L{summary['by_class']['left']} C{summary['by_class']['center']} "
            f"R{summary['by_class']['right']} N{summary['by_class']['none']}) pos {summary['position_ok'] or '-':>6s} "
            f"x_mae {summary['x_mae'] if summary['x_mae'] is not None else '-':>5} err {summary['errors']:2d} "
            f"hit {summary['image_cache_hits_excluded_from_latency']:2d} | "
            f"total p50 {ms['p50']:7.1f} p90 {ms['p90']:7.1f} max {ms['max']:7.1f} ms | "
            f"prompt {summary['prompt_n']:.0f}tok (cached {summary['cache_n']:.0f}) {summary['prompt_ms']:6.1f} ms | "
            f"out {summary['predicted_n']:.0f}tok {summary['predicted_ms']:6.1f} ms")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", default="*", help="comma-separated names or globs")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="gemma4-e2b")
    parser.add_argument("--sampling", choices=list(SAMPLING), default="greedy")
    parser.add_argument("--cache", choices=("on", "off"), default="on")
    parser.add_argument("--passes", type=int, default=1, help="passes over the image set, new seed each")
    parser.add_argument("--limit", type=int, help="use only the first N shuffled images")
    parser.add_argument("--dataset", choices=("present", "absent", "both"), default="present",
                        help="labeled fridge views, fridge-free views, or both")
    parser.add_argument("--tag", default="default", help="label for the server configuration under test")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    names = [name for name in VARIANTS
             if any(fnmatch.fnmatch(name, pattern) for pattern in args.variants.split(","))]
    if args.list or not names:
        print("\n".join(VARIANTS))
        return 0
    dataset = []
    if args.dataset in ("present", "both"):
        dataset += json.loads((ROOT / "bench/dataset.json").read_text())
    if args.dataset in ("absent", "both"):
        dataset += [{**entry, "expected_turn": "absent"}
                    for entry in json.loads((ROOT / "bench/absent.json").read_text())]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out_dir = ROOT / "experiments" / f"{stamp}-latency-{args.tag}"
    out_dir.mkdir(parents=True)
    props = get_json(args.base_url, "/props")
    (out_dir / "server-props.json").write_text(json.dumps(props, indent=2) + "\n")
    launch = Path(os.environ.get("BENCH_LOG_DIR", "/tmp/harness-bench-logs")) / "current-launch.txt"
    (out_dir / "manifest.json").write_text(json.dumps({
        **vars(args), "variants": names, "images": len(dataset), "build": props.get("build_info"),
        "server_launch": launch.read_text().strip() if launch.exists() else "unknown (not started by bench/serve.sh)",
    }, indent=2) + "\n")
    summaries = []
    with (out_dir / "requests.jsonl").open("w") as log:
        for name in names:
            variant, rows = VARIANTS[name], []
            for index in range(args.passes):
                order = list(dataset)
                random.Random(1000 + index).shuffle(order)
                order = order[:args.limit] if args.limit else order
                # Untimed warm-up on an image that is not next in line: primes the text prefix only.
                try:
                    run_variant(args.base_url, variant, build_payload(
                        variant, ROOT / order[-1]["image"], args.model, args.sampling, args.cache == "on", 0))
                except Exception as error:  # a rejected variant must not abort the rest of the sweep
                    print(f"{name}: warm-up failed: {error}", file=sys.stderr, flush=True)
                for position, entry in enumerate(order):
                    # llama.cpp re-seeds per request, so every request needs its own seed to be an
                    # independent draw when sampling with temperature.
                    payload = build_payload(variant, ROOT / entry["image"], args.model, args.sampling,
                                            args.cache == "on", 500 + 1000 * index + position)
                    row = {"variant": name, "pass": index, **entry}
                    try:
                        result = run_variant(args.base_url, variant, payload)
                    except Exception as error:
                        result = {"content": "", "reasoning": "", "tool_calls": [], "finish_reason": "error",
                                  "usage": {}, "timings": {}, "total_s": None, "ttft_s": None,
                                  "first_call_s": None}
                        row["request_error"] = str(error)
                    row.update(result, **grade(variant, result, entry["expected_turn"]))
                    # A live camera never repeats a frame: fewer fresh tokens than the image holds
                    # means the server reused a cached copy of this exact image.
                    fresh = result["timings"].get("first_prompt_n", result["timings"].get("prompt_n"))
                    row["image_cache_hit"] = bool(
                        fresh is not None and fresh < 0.9 * image_tokens(variant["image_size"]))
                    row["reasoning"] = row["reasoning"][-400:]
                    rows.append(row)
                    log.write(json.dumps(row) + "\n")
                    log.flush()
            summary = summarize(name, rows)
            summaries.append(summary)
            print(line(summary), flush=True)
            (out_dir / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print(f"Saved: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
