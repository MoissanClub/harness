#!/usr/bin/env python3
"""Inspect a saved run using llama.cpp formatting/tokenization; no inference."""

import argparse
import copy
import json
from pathlib import Path

from run import ROOT, request_json, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    request = json.loads((args.run_dir / "turn-01-request.json").read_text())
    response = json.loads((args.run_dir / "turn-01-response.json").read_text())
    message = response["choices"][0]["message"]
    props = request_json(base + "/props", timeout=15)
    output = ROOT / "protocol" / args.run_dir.name
    output.mkdir(parents=True, exist_ok=True)
    (output / "active-chat-template.jinja").write_text(props["chat_template"])
    rendered = request_json(base + "/apply-template", request, timeout=30)
    (output / "rendered-prompt.txt").write_text(rendered["prompt"])

    # Use the actual template to serialize every call, including arrays/empty args.
    # Remove images in this auxiliary rendering so media placeholders are stable.
    example = copy.deepcopy(request)
    for msg in example["messages"]:
        if isinstance(msg.get("content"), list):
            msg["content"] = "\n".join(part["text"] for part in msg["content"] if part["type"] == "text")
    prefix = request_json(base + "/apply-template", example)["prompt"]
    calls = message.get("tool_calls") or []
    if calls:
        example["messages"].append({"role": "assistant", "content": "", "tool_calls": calls})
        example["messages"].extend({"role": "tool", "tool_call_id": call["id"], "content": "{}"} for call in calls)
        example["add_generation_prompt"] = False
        rendered_calls = request_json(base + "/apply-template", example)["prompt"]
        if not rendered_calls.startswith(prefix):
            raise ValueError("Unexpected template prefix")
        native = rendered_calls[len(prefix):].split("<|tool_response>", 1)[0] + "<|tool_response>"
    else:
        native = ""
    (output / "native-tool-output.txt").write_text(native)
    samples = {"reasoning_text": message.get("reasoning_content") or "", "native_tool_output": native}
    counts = {}
    for name, content in samples.items():
        tokens = request_json(base + "/tokenize", {
            "content": content, "add_special": False, "parse_special": True,
        }, timeout=15)
        counts[name] = len(tokens["tokens"])
    counts.update(
        reported_completion_tokens=response["usage"]["completion_tokens"],
        note="Pieces retokenized separately; channel/stop tokens and boundaries can affect totals.",
        server_build=props["build_info"],
        source_run=str(args.run_dir.resolve()),
    )
    save(output / "token-counts.json", counts)
    print(json.dumps(counts, indent=2))
    print(f"Saved protocol inspection to {output}")


if __name__ == "__main__":
    main()
