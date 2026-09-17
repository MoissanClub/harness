#!/usr/bin/env python3
"""Run a one-response image/tool-call test against a local llama.cpp API (stdlib only)."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tools import FORMATS, STEP_METERS, TURN_DEGREES, record_batch, tool_schemas

ROOT = Path(__file__).resolve().parent
THINKING_MODES = ("off", "normal", "brief")


def runner_defaults():
    return json.loads((ROOT / "runner-defaults.json").read_text())


def evaluation_sampling():
    return json.loads((ROOT / "evaluation-sampling.json").read_text())


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def request_json(url: str, body=None, timeout=600):
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error


def png_dimensions(data: bytes) -> tuple:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("The image must be a PNG")
    return struct.unpack(">II", data[16:24])


def complete(base_url, payload, run_dir, label="turn-01"):
    save(run_dir / f"{label}-request.json", payload)
    started = time.monotonic()
    response = request_json(base_url + "/chat/completions", payload)
    seconds = time.monotonic() - started
    save(run_dir / f"{label}-response.json", response)
    return response, seconds


def assess(directions: list, expected_turn) -> dict:
    """Qualitative scene rubric only; never injected into model messages."""
    first_forward = directions.index("forward") if "forward" in directions else None
    turns = [direction for direction in directions if direction.startswith("turn_")]
    if expected_turn is None:
        correct_turn = not turns
    else:
        correct_turn = bool(
            first_forward is not None
            and expected_turn in directions[:first_forward]
            and all(turn == expected_turn for turn in turns)
        )
    one_forward = directions.count("forward") == 1
    no_extra_translation = all(
        direction == "forward" or direction.startswith("turn_") for direction in directions
    )
    forward_last = bool(directions and directions[-1] == "forward")
    return {
        "expected_turn": expected_turn,
        "correct_turn_before_forward": correct_turn,
        "one_forward_step": one_forward,
        "no_extra_translation": no_extra_translation,
        "forward_is_last_action": forward_last,
        "qualitative_goal_match": bool(
            correct_turn and one_forward and no_extra_translation and forward_last
        ),
        "scope": "Turn direction and action order only; no metric alignment or navigation claim.",
    }


def build_payload(args, case):
    image = (ROOT / case["image"]).resolve()
    image_data = image.read_bytes()
    width, height = png_dimensions(image_data)
    system = (ROOT / "prompts/system.txt").read_text().strip().format(
        max_actions=args.max_actions, step_m=STEP_METERS, turn_degrees=TURN_DEGREES)
    thinking = getattr(args, "thinking", None) or runner_defaults()["thinking"]
    if thinking not in THINKING_MODES:
        raise ValueError(f"Unknown thinking mode: {thinking}")
    if thinking == "brief":
        system += "\n" + (ROOT / "prompts/brief-thinking.txt").read_text().strip()
    payload = {
        **json.loads((ROOT / "request-defaults.json").read_text()),
        "chat_template_kwargs": {"enable_thinking": thinking != "off"},
        "model": args.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(image_data).decode()
                }},
                {"type": "text", "text": args.prompt_file.read_text().strip()},
            ]},
        ],
        "tools": tool_schemas(args.format, args.max_actions),
    }
    if args.seed is not None:
        payload["seed"] = args.seed
    if args.cache != "default":
        payload["cache_prompt"] = args.cache == "on"
    metadata = {
        "image": str(image), "width": width, "height": height,
        "sha256": hashlib.sha256(image_data).hexdigest(),
        "base_url": args.base_url, "model": args.model, "format": args.format,
        "thinking": thinking,
        "max_actions": args.max_actions,
        "rubric": {key: value for key, value in case.items() if key != "image"},
    }
    return payload, metadata


def evaluate_response(response, elapsed, format_name, max_actions):
    choice = response["choices"][0]
    message = choice["message"]
    calls = message.get("tool_calls") or []
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""
    summary = {
        "actions": [], "protocol_ok": False, "hardware_executed": False,
        "finish_reason": choice.get("finish_reason"), "call_count": len(calls),
        "content": content, "reasoning_characters": len(reasoning),
        "total_request_seconds": elapsed,
        "usage": response.get("usage", {}), "timings": response.get("timings", {}),
        "outcome": "protocol_error",
    }
    results = []
    if choice.get("finish_reason") == "length":
        summary.update(outcome="truncated", error="Incomplete generation; inspect response")
    elif not calls:
        summary["outcome"] = "abstained" if choice.get("finish_reason") == "stop" else "protocol_error"
    else:
        try:
            if choice.get("finish_reason") != "tool_calls":
                raise ValueError("Expected native calls with matching tool_calls finish reason")
            plan, results = record_batch(calls, [], max_actions, set(), format_name)
            summary.update(actions=plan, protocol_ok=True, outcome="recorded_plan")
        except (ValueError, TypeError) as error:
            summary["error"] = str(error)
    summary["tool_only_answer"] = summary["protocol_ok"] and not content.strip()
    # Retained for historical reports: stricter than tool-only final output.
    summary["only_tool_output"] = summary["tool_only_answer"] and not reasoning.strip()
    return summary, results


def run(args, run_dir, case_name, case, props=None, overrides=None, quiet=False):
    base_url = args.base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        raise ValueError("--base-url must end in /v1")
    if props is None:
        props = request_json(base_url[:-3] + "/props", timeout=15)
    save(run_dir / "server-props.json", props)
    if not props.get("modalities", {}).get("vision"):
        raise ValueError("Server does not report vision support; check mmproj loading")
    payload, metadata = build_payload(args, case)
    payload.update(overrides or {})
    save(run_dir / "input.json", {**metadata, "case": case_name})
    response, elapsed = complete(base_url, payload, run_dir)
    summary, results = evaluate_response(response, elapsed, args.format, args.max_actions)
    summary.update(case=case_name, format=args.format, seed=payload.get("seed"),
                   cache_prompt=payload.get("cache_prompt"), thinking=metadata["thinking"])
    reasoning = response["choices"][0]["message"].get("reasoning_content") or ""
    summary["reasoning_text_tokens"] = len(request_json(base_url[:-3] + "/tokenize", {
        "content": reasoning, "add_special": False, "parse_special": True,
    })["tokens"]) if reasoning else 0
    summary["thinking_compliant"] = metadata["thinking"] != "off" or not reasoning.strip()
    if "expected_turn" in case:
        summary["assessment"] = assess(summary["actions"], case["expected_turn"])
    save(run_dir / "turn-01-tool-results.json", results)
    save(run_dir / "summary.json", summary)
    if not quiet:
        print(json.dumps(summary, indent=2), flush=True)
        print(f"Saved run: {run_dir}", flush=True)
    # There is deliberately no second request or acknowledgement generation.
    return summary


def add_common_arguments(parser):
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="gemma4-e4b")
    parser.add_argument("--prompt-file", type=Path, default=ROOT / "prompts/user.txt")
    parser.add_argument("--max-actions", type=int, default=4)
    parser.add_argument("--thinking", choices=THINKING_MODES, default=runner_defaults()["thinking"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    cases = json.loads((ROOT / "cases.json").read_text())
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", choices=list(cases), default="center")
    selection.add_argument("--suite", action="store_true")
    selection.add_argument("--image", type=Path, help="Custom PNG; no scene rubric applied")
    parser.add_argument("--format", choices=FORMATS, default=runner_defaults()["format"])
    parser.add_argument("--seed", type=int)
    parser.add_argument("--cache", choices=("default", "on", "off"), default="default")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.max_actions < 1 or args.repeat < 1:
        parser.error("--max-actions and --repeat must be positive")
    selected = cases if args.suite else {args.case: cases[args.case]}
    if args.image:
        selected = {"custom": {"image": str(args.image.resolve())}}
    exit_code = 0
    for repetition in range(args.repeat):
        for case_name, case in selected.items():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            run_dir = ROOT / "runs" / f"{stamp}-{case_name}-{args.format}"
            run_dir.mkdir(parents=True)
            print(f"Scene {case_name}, format {args.format}, repetition {repetition + 1}/{args.repeat}", flush=True)
            try:
                summary = run(args, run_dir, case_name, case)
                exit_code |= int(not summary["tool_only_answer"] or not summary["thinking_compliant"] or not
                                summary.get("assessment", {}).get("qualitative_goal_match", True))
            except (OSError, URLError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as error:
                save(run_dir / "error.json", {"error": str(error)})
                print(f"Error: {error}\nSaved artifacts: {run_dir}", file=sys.stderr)
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
