#!/usr/bin/env python3
"""Offline boundary checks. Run with python3 -B harness/check.py."""

import ast
import json
from types import SimpleNamespace

from run import ROOT, THINKING_MODES, assess, build_payload, evaluate_response, png_dimensions
from tools import DIRECTIONS, FORMATS, encode_actions, record_batch


def call(direction, ident="a"):
    return {"id": ident, "type": "function", "function": {
        "name": "move", "arguments": json.dumps({"direction": direction}),
    }}


def main():
    for path in [*ROOT.glob("*.py"), *ROOT.glob("bench/*.py")]:
        ast.parse(path.read_text())

    original = []
    plan, results = record_batch([call("turn_left"), call("forward", "b")], original, 4, set())
    assert original == [] and plan == ["turn_left", "forward"]
    assert results[0]["requested_turn_degrees"] == 30
    assert results[1]["requested_step_m"] == 0.25
    assert results[0]["planned_actions"] == ["turn_left"]
    assert results[1]["planned_actions"] == plan
    assert all(result["executed"] is False for result in results)

    for format_name in FORMATS:
        for action in DIRECTIONS:
            decoded, _ = record_batch(encode_actions([action], format_name), [], 4, set(), format_name)
            assert decoded == [action]
        calls = encode_actions(["turn_left", "forward"], format_name)
        decoded, _ = record_batch(calls, [], 4, set(), format_name)
        assert decoded == ["turn_left", "forward"]
        response = {"choices": [{"finish_reason": "tool_calls", "message": {
            "tool_calls": calls, "content": "", "reasoning_content": "",
        }}]}
        summary, _ = evaluate_response(response, 1.0, format_name, 4)
        assert summary["only_tool_output"] and summary["actions"] == decoded
        response["choices"][0]["message"]["reasoning_content"] = "Brief reasoning."
        summary, _ = evaluate_response(response, 1.0, format_name, 4)
        assert summary["tool_only_answer"] and not summary["only_tool_output"]
        response["choices"][0]["message"]["content"] = "I will do that."
        summary, _ = evaluate_response(response, 1.0, format_name, 4)
        assert not summary["tool_only_answer"]
        response["choices"][0]["finish_reason"] = "length"
        summary, _ = evaluate_response(response, 1.0, format_name, 4)
        assert not summary["protocol_ok"] and summary["outcome"] == "truncated"
        try:
            record_batch(calls, [], 1, set(), format_name)
        except ValueError:
            pass
        else:
            raise AssertionError("Action limit must count actions, not tool calls")

    for format_name, bad in [
        ("atomic", {"name": "move_left", "arguments": '{"direction":"left"}'}),
        ("split", {"name": "move", "arguments": '{"direction":"turn_left"}'}),
        ("split", {"name": "turn", "arguments": '{"direction":"forward"}'}),
        ("plan", {"name": "plan", "arguments": '{"actions":[]}'}),
        ("plan", {"name": "plan", "arguments": '{"actions":["fly"]}'}),
        ("plan", {"name": "plan", "arguments": '{"actions":"forward"}'}),
    ]:
        try:
            record_batch([{"id": "a", "type": "function", "function": bad}], [], 4, set(), format_name)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Should reject {bad}")

    malformed = call("forward")
    malformed["function"]["arguments"] = "{"
    extra = call("forward")
    extra["function"]["arguments"] = '{"direction":"forward","extra":1}'
    unknown = call("forward")
    unknown["function"]["name"] = "other"
    for calls, existing, limit, seen in [
        ([call("turn_up")], [], 4, set()),
        ([call("forward"), call("turn_right", "b")], ["turn_right"], 2, set()),
        ([call("forward"), call("forward")], [], 4, set()),
        ([call("forward")], [], 4, {"a"}),
        ([malformed], [], 4, set()),
        ([extra], [], 4, set()),
        ([unknown], [], 4, set()),
    ]:
        snapshot = list(existing)
        try:
            record_batch(calls, existing, limit, seen)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Should reject {calls}")
        assert existing == snapshot

    for actions, expected, passes in [
        (["turn_left", "forward"], "turn_left", True),
        (["turn_right", "forward"], "turn_right", True),
        (["forward"], None, True),
        (["forward", "turn_right"], "turn_right", False),
        (["turn_left", "forward"], "turn_right", False),
        (["turn_right", "forward", "forward"], "turn_right", False),
    ]:
        assert assess(actions, expected)["qualitative_goal_match"] is passes
    for image in ROOT.glob("assets/*720x480.png"):
        assert png_dimensions(image.read_bytes()) == (720, 480)
    base_prompts = []
    case = json.loads((ROOT / "cases.json").read_text())["left"]
    for mode in THINKING_MODES:
        args = SimpleNamespace(thinking=mode, model="test", format="plan", max_actions=4,
                               prompt_file=ROOT / "prompts/user.txt", seed=None, cache="off", base_url="http://test/v1")
        payload, metadata = build_payload(args, case)
        assert payload["chat_template_kwargs"]["enable_thinking"] == (mode != "off")
        assert metadata["thinking"] == mode
        base_prompts.append(payload["messages"][0]["content"])
    assert base_prompts[0] == base_prompts[1]
    assert base_prompts[2] == base_prompts[0] + "\n" + (ROOT / "prompts/brief-thinking.txt").read_text().strip()
    print("Syntax, mock ordering, rejection, rubric, and image dimensions passed.")


if __name__ == "__main__":
    main()
