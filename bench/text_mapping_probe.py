#!/usr/bin/env python3
"""Text-only control: given the percept in words, does thinking-off E2B emit the right plan call?

No image is sent. Compare with the image variants, where the same mapping fails (stdlib only).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from client import timed_chat  # noqa: E402
from tools import tool_schemas  # noqa: E402
from variants import CODEX_SYSTEM, FILL, LOCATE_SYSTEM, POLICY, RULE_SYSTEM  # noqa: E402

SYSTEMS = {"codex": CODEX_SYSTEM, "locate": LOCATE_SYSTEM, "rule": RULE_SYSTEM, "none": None}
USERS = {
    "face+step": "The fridge is in the {p} third of the camera image. Face the fridge and take one step toward it.",
    "turn-then-step": "The fridge is in the {p} third of the camera image. First turn to face the fridge if "
                      "needed, then step forward.",
}


def main():
    table = []
    for system_name, system in SYSTEMS.items():
        for user_name, user in USERS.items():
            outputs = {}
            for position in ("left", "center", "right"):
                messages = [{"role": "user", "content": user.format(p=position)}]
                if system:
                    messages.insert(0, {"role": "system", "content": system.format(**FILL)})
                result = timed_chat("http://127.0.0.1:8080/v1", {
                    "model": "gemma4-e2b", "messages": messages, "tools": tool_schemas("plan", 4),
                    "tool_choice": "auto", "temperature": 0, "top_k": 1, "max_tokens": 64,
                    "chat_template_kwargs": {"enable_thinking": False}})
                outputs[position] = (json.loads(result["tool_calls"][0]["arguments"]).get("actions")
                                     if result["tool_calls"] else result["content"][:40])
            correct = sum(outputs[position] == POLICY[position] for position in outputs)
            table.append({"system": system_name, "user": user_name, "correct": correct, "outputs": outputs})
            print(f"system={system_name:7s} user={user_name:15s} {correct}/3 {outputs}", flush=True)
    out_dir = ROOT / "experiments" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}-text-mapping"
    out_dir.mkdir(parents=True)
    (out_dir / "table.json").write_text(json.dumps(table, indent=2) + "\n")
    print(f"Saved: {out_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
