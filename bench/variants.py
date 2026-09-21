"""Request variants for the latency/accuracy sweep.

Each variant is a dict:
  system, user      prompt text ({step_m}/{turn_degrees}/{max_actions} are filled in)
  order             "image_first" (harness default) or "text_first"
  thinking          native enable_thinking flag
  tools             list of tool schemas, or None for plain-content variants
  extra             request fields merged last (max_tokens, grammar, response_format, ...)
  parse             name of a parser in PARSERS -> {"actions": [...], "position": ..., "x": ...}
  image_size        optional (width, height) client-side resize before sending; multiples of 48
                    inside the 70-token minimum (e.g. 480x336) skip the server's own resize
  jpeg              send the (resized) frame as JPEG quality 85 instead of PNG
  prefill           optional assistant-turn prefix the model continues (costs prefill, not decode)
  gate              optional yes/no presence question asked first; only on "yes" is the variant's own
                    question sent as a follow-up turn on the same KV (image tokens are not re-processed)
  stage2            optional follow-up request reusing the first turn's KV: the perception answer
                    is appended and the model then makes the tool call
"""

import json
import re

from tools import DIRECTIONS, STEP_METERS, TURN_DEGREES, decode_call, tool_schemas

FILL = {"step_m": STEP_METERS, "turn_degrees": TURN_DEGREES, "max_actions": 4}
LEFT_EDGE, RIGHT_EDGE = 0.38, 0.62  # midpoints of the dataset's label gaps
POLICY = {"left": ["turn_left", "forward"], "center": ["forward"], "right": ["turn_right", "forward"],
          "none": []}  # target not in view: no motion here; a real controller would search

# ---- prompts ---------------------------------------------------------------------------------
CODEX_SYSTEM = (
    "Plan from the robot's forward-facing camera: image left/right are robot left/right; centered is "
    "straight ahead. Translation steps are {step_m} m; turns are {turn_degrees} degrees in place. Later "
    "actions use the heading after earlier turns. Return the complete ordered plan using at most "
    "{max_actions} actions, as few as needed. Outside the thought channel, output only tool calls. "
    "This is an unexecuted mock plan.")
BRIEF = "\nUse brief, efficient reasoning. Avoid repetition and unnecessary elaboration."
CODEX_USER = "Face the fridge and take one step toward it. What tool calls would you run?"

LOCATE_SYSTEM = (
    "You steer a robot from its forward-facing camera. Image left/right are robot left/right. "
    "First locate the target in the image: left third, center third, or right third. "
    "If it is in the left third, turn_left first; in the right third, turn_right first; in the center "
    "third, do not turn. Turns are {turn_degrees} degrees in place; forward is one {step_m} m step. "
    "Reply with exactly one tool call and nothing else.")
LOCATE_USER = "Face the fridge and take one step toward it."

LOCATE_X_SYSTEM = (
    "You steer a robot from its forward-facing camera. Image left/right are robot left/right. "
    "First estimate the target centre's horizontal position as a percentage of image width "
    "(0 left edge, 50 middle, 100 right edge). If it is below 38, turn_left first; above 62, turn_right "
    "first; otherwise do not turn. Turns are {turn_degrees} degrees in place; forward is one {step_m} m "
    "step. Reply with exactly one tool call and nothing else.")
APPROACH_SYSTEM = (
    "You steer a robot from its forward-facing camera. Image left/right are robot left/right. "
    "Reply with exactly one tool call and nothing else.")

JSON_X_SYSTEM = (
    "You steer a robot from its forward-facing camera. Image left/right are robot left/right. "
    "First estimate the target centre's horizontal position x as a percentage of image width "
    "(0 left edge, 50 middle, 100 right edge). If x is below 38, turn_left first; above 62, turn_right "
    "first; otherwise do not turn. Turns are {turn_degrees} degrees in place; forward is one {step_m} m "
    "step. Allowed actions: left, right, forward, backward (translate), turn_left, turn_right (rotate). "
    'Reply with JSON only: {{"x": 0-100, "actions": [...]}}')

JSON_SYSTEM = (
    "You steer a robot from its forward-facing camera. Image left/right are robot left/right. "
    "First locate the target in the image: left third, center third, or right third. "
    "If it is in the left third, turn_left first; in the right third, turn_right first; in the center "
    "third, do not turn. Turns are {turn_degrees} degrees in place; forward is one {step_m} m step. "
    "Allowed actions: left, right, forward, backward (translate), turn_left, turn_right (rotate). "
    'Reply with JSON only: {{"target": "left|center|right", "actions": [...]}}')

WHERE_SYSTEM = "You are a robot's vision module. Image left/right are robot left/right."
WHERE_USER = "Is the fridge in the left third, center third, or right third of the image? Answer with one word: left, center, or right."

X_SYSTEM = WHERE_SYSTEM
X_USER = ("Give the horizontal position of the center of the fridge as an integer percentage of the "
          "image width: 0 is the left edge, 50 the middle, 100 the right edge. Answer with the number only.")

BOX_USER = ('Detect the fridge. Output only JSON: [{"box_2d": [ymin, xmin, ymax, xmax], "label": "fridge"}] '
            "with coordinates normalized to 0-1000.")

WHERE_SYS_SYSTEM = (WHERE_SYSTEM + " For each camera image, answer with one word: is the fridge in the "
                    "left third, center third, or right third of the image? Answer left, center, or right.")
X_SYS_SYSTEM = (WHERE_SYSTEM + " For each camera image, give the horizontal position of the center of the "
                "fridge as an integer percentage of the image width: 0 is the left edge, 50 the middle, "
                "100 the right edge. Answer with the number only.")
BOX_PREFILL = '```json\n[\n  {"box_2d": ['

NEXT_SYSTEM = (
    "You steer a robot toward the fridge from its forward-facing camera, one action per image. "
    "Image left/right are robot left/right. If the fridge is in the left third of the image choose "
    "turn_left; in the right third choose turn_right; in the center third choose forward.")
NEXT_USER = "Choose the next action."
STAGE2_USER = "The fridge is in the {position} third of the image. Face the fridge and take one step toward it."

RULE_SYSTEM = (
    "You steer a robot from its forward-facing camera. Image left/right are robot left/right. "
    "Rule: target in the left third of the image -> plan [turn_left, forward]; right third -> "
    "[turn_right, forward]; center third -> [forward]. Turns are {turn_degrees} degrees in place; "
    "forward is one {step_m} m step.")
FACE_USER = ("Is the fridge in the left third, center third, or right third of the image? "
             "Call face_target with that position.")
APPROACH_USER = ("Find the horizontal position of the center of the fridge as an integer percentage of the "
                 "image width: 0 is the left edge, 50 the middle, 100 the right edge. Call approach with that number.")

DSL_SYSTEM = (
    "You steer a robot from its forward-facing camera. Image left/right are robot left/right. "
    "Reply with the target's image position, then the actions, e.g. `left: turn_left forward`, "
    "`center: forward`, `right: turn_right forward`. Turn toward the target only if it is outside the "
    "center third. Turns are {turn_degrees} degrees in place; forward is one {step_m} m step.")

# ---- tools -----------------------------------------------------------------------------------
ACTIONS = {"type": "array", "items": {"type": "string", "enum": list(DIRECTIONS)},
           "minItems": 1, "maxItems": 4}
MOTION = "left/right strafe; forward/backward translate; turn_left/turn_right rotate."


def fn(name, description, properties, required):
    return [{"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required,
                       "additionalProperties": False}}}]


ACT_TOOL = fn("act", "Report where the target is in the image, then the ordered actions: " + MOTION, {
    "target": {"type": "string", "enum": ["left", "center", "right"],
               "description": "Third of the image containing the target."},
    "actions": ACTIONS}, ["target", "actions"])
ACT_X_TOOL = fn("act", "Report the target's horizontal image position, then the ordered actions: " + MOTION, {
    "target_x": {"type": "integer", "minimum": 0, "maximum": 100,
                 "description": "Target centre as % of image width; 0 left edge, 50 middle, 100 right edge."},
    "actions": ACTIONS}, ["target_x", "actions"])

# Gemma 4's chat template sorts schema properties (dictsort), and the model emits arguments in that
# alphabetical order ("actions" before "target"), so the perception field only precedes the
# decision when its name sorts first: look < move.
LOOK_TOOL = fn("act", "Report where the target is in the image, then the ordered moves: " + MOTION, {
    "look": {"type": "string", "enum": ["left", "center", "right"],
             "description": "Third of the image containing the target."},
    "move": ACTIONS}, ["look", "move"])
LOOK_X_TOOL = fn("act", "Report the target's horizontal image position, then the ordered moves: " + MOTION, {
    "look_x": {"type": "integer", "minimum": 0, "maximum": 100,
               "description": "Target centre as % of image width; 0 left edge, 50 middle, 100 right edge."},
    "move": ACTIONS}, ["look_x", "move"])
APPROACH_TOOL = fn("approach", "Turn to face the target and take one step toward it.", {
    "target_x": {"type": "integer", "minimum": 0, "maximum": 100,
                 "description": "Target centre as % of image width; 0 left edge, 50 middle, 100 right edge."}},
    ["target_x"])

FACE_TOOL = fn("face_target", "Turn to face the target, then take one step toward it.", {
    "position": {"type": "string", "enum": ["left", "center", "right"],
                 "description": "Third of the image containing the target."}}, ["position"])
NEXT3 = ["turn_left", "forward", "turn_right"]
NEXT_TOOL = fn("move", "Execute one action: turn_left/turn_right rotate 30 degrees in place; forward steps 0.25 m.",
               {"direction": {"type": "string", "enum": NEXT3}}, ["direction"])
NEXT_ATOMIC = (fn("turn_left", "Rotate 30 degrees left in place.", {}, [])
               + fn("forward", "Step 0.25 m forward.", {}, [])
               + fn("turn_right", "Rotate 30 degrees right in place.", {}, []))
NEXT_GRAMMAR = 'root ::= "turn_left" | "forward" | "turn_right"'

# ---- grammars / schemas ----------------------------------------------------------------------
WHERE_GRAMMAR = 'root ::= "left" | "center" | "right"'
X_GRAMMAR = 'root ::= "100" | [1-9] [0-9] | [0-9]'
DSL_GRAMMAR = ('root ::= pos ": " act (" " act)? (" " act)? (" " act)?\n'
               'pos ::= "left" | "center" | "right"\n'
               'act ::= "turn_left" | "turn_right" | "forward" | "backward" | "left" | "right"')
JSON_X_SCHEMA = {"type": "object", "properties": {
    "x": {"type": "integer", "minimum": 0, "maximum": 100}, "actions": ACTIONS},
    "required": ["x", "actions"], "additionalProperties": False}
JSON_SCHEMA = {"type": "object", "properties": {
    "target": {"type": "string", "enum": ["left", "center", "right"]}, "actions": ACTIONS},
    "required": ["target", "actions"], "additionalProperties": False}


# ---- parsers ---------------------------------------------------------------------------------
def parse_plan_tool(result):
    calls = [{"id": f"c{i}", "type": "function", "function": call}
             for i, call in enumerate(result["tool_calls"])]
    actions = []
    for call in calls:
        actions += decode_call(call, "plan")
    return {"actions": actions}


def parse_act_tool(result):
    call = result["tool_calls"][0]
    args = json.loads(call["arguments"])
    out = {"actions": list(args["actions"]), "arg_order": list(args)}
    if "target" in args:
        out["position"] = args["target"]
    if "target_x" in args:
        out["x"] = float(args["target_x"]) / 100
    return out


def parse_look_tool(result):
    args = json.loads(result["tool_calls"][0]["arguments"])
    out = {"actions": list(args["move"]), "arg_order": list(args)}
    if "look" in args:
        out["position"] = args["look"]
    if "look_x" in args:
        out["x"] = float(args["look_x"]) / 100
        out["position"] = position_from_x(out["x"])
    return out


def parse_approach_tool(result):
    call = result["tool_calls"][0]
    if call["name"] != "approach":
        raise ValueError(f"unexpected tool {call['name']}")
    x = float(json.loads(call["arguments"])["target_x"]) / 100
    if not 0 <= x <= 1:  # the native tool grammar does not enforce the schema's range
        raise ValueError(f"target_x out of range: {x * 100:.0f}")
    return {"actions": POLICY[position_from_x(x)], "position": position_from_x(x), "x": x}


def parse_json(result):
    args = json.loads(result["content"])
    out = {"actions": list(args["actions"]), "position": args.get("target")}
    if "x" in args:
        out["x"] = float(args["x"]) / 100
        out["position"] = position_from_x(out["x"])
    return out


def parse_present(result):
    """Presence only: graded on the absent set as none, on present images as 'seen' (no position)."""
    seen = result["content"].strip().lower().startswith("yes")
    return {"actions": [] if not seen else ["seen"], "position": "seen" if seen else "none"}


def parse_where(result):
    word = result["content"].strip().lower().strip(".")
    return {"actions": POLICY[word], "position": word}


def position_from_x(x):
    return "left" if x < LEFT_EDGE else "right" if x > RIGHT_EDGE else "center"


def parse_x(result):
    x = float(re.search(r"\d+", result["content"]).group()) / 100
    return {"actions": POLICY[position_from_x(x)], "position": position_from_x(x), "x": x}


def parse_box(result):
    text = result["content"]
    boxes = json.loads(text[text.index("["):text.rindex("]") + 1])
    if not boxes:
        return {"actions": POLICY["none"], "position": "none"}
    box = boxes[0]["box_2d"]
    x = (box[1] + box[3]) / 2000
    return {"actions": POLICY[position_from_x(x)], "position": position_from_x(x), "x": x, "box": box}


def parse_box_prefill(result):
    text = result["content"]
    numbers = [int(n) for n in re.findall(r"\d+", text[text.rindex("[") + 1:])][:4]
    x = (numbers[1] + numbers[3]) / 2000
    return {"actions": POLICY[position_from_x(x)], "position": position_from_x(x), "x": x, "box": numbers}


def parse_face_tool(result):
    call = result["tool_calls"][0]
    if call["name"] != "face_target":
        raise ValueError(f"unexpected tool {call['name']}")
    position = json.loads(call["arguments"])["position"]
    return {"actions": POLICY[position], "position": position}


def next_plan(action):
    if action not in NEXT3:
        raise ValueError(f"unexpected action {action}")
    position = {"turn_left": "left", "forward": "center", "turn_right": "right"}[action]
    return {"actions": POLICY[position], "position": position, "next_action": action}


def parse_next_tool(result):
    call = result["tool_calls"][0]
    return next_plan(json.loads(call["arguments"])["direction"] if call["name"] == "move" else call["name"])


def parse_next_word(result):
    return next_plan(result["content"].strip())


def parse_dsl(result):
    position, _, actions = result["content"].strip().partition(":")
    return {"actions": actions.split(), "position": position.strip()}


PARSERS = {"present": parse_present, "plan_tool": parse_plan_tool, "act_tool": parse_act_tool, "look_tool": parse_look_tool,
           "approach_tool": parse_approach_tool, "box_prefill": parse_box_prefill, "face_tool": parse_face_tool,
           "next_tool": parse_next_tool, "next_word": parse_next_word, "json": parse_json,
           "where": parse_where, "x": parse_x, "box": parse_box, "dsl": parse_dsl}

# ---- variants --------------------------------------------------------------------------------
PLAN_TOOL = tool_schemas("plan", 4)


def v(system, user, parse, tools=None, thinking=False, order="image_first", extra=None, image_size=None,
      prefill=None, stage2=None, jpeg=False, gate=None):
    return {"system": system.format(**FILL) if system else None, "user": user, "parse": parse,
            "tools": tools, "thinking": thinking, "order": order, "extra": extra or {},
            "image_size": image_size, "prefill": prefill, "stage2": stage2, "jpeg": jpeg, "gate": gate}


VARIANTS = {
    # A. codex baselines (unchanged prompts and plan tool)
    "codex-off": v(CODEX_SYSTEM, CODEX_USER, "plan_tool", PLAN_TOOL),
    "codex-brief": v(CODEX_SYSTEM + BRIEF, CODEX_USER, "plan_tool", PLAN_TOOL, thinking=True),
    # B. hard reasoning budgets on the brief-thinking baseline
    **{f"codex-brief-budget{n}": v(CODEX_SYSTEM + BRIEF, CODEX_USER, "plan_tool", PLAN_TOOL, thinking=True,
                                   extra={"reasoning_budget_tokens": n, "max_tokens": n + 64})
       for n in (16, 32, 64, 128)},
    # C. perceive-then-act inside the tool call, thinking off
    "locate-plan-off": v(LOCATE_SYSTEM, LOCATE_USER, "plan_tool", PLAN_TOOL),
    "act-target-off": v(LOCATE_SYSTEM, LOCATE_USER, "act_tool", ACT_TOOL),
    "act-x-off": v(LOCATE_SYSTEM, LOCATE_USER, "act_tool", ACT_X_TOOL),
    "look-move-off": v(LOCATE_SYSTEM, LOCATE_USER, "look_tool", LOOK_TOOL),
    "lookx-move-off": v(LOCATE_X_SYSTEM, LOCATE_USER, "look_tool", LOOK_X_TOOL),
    "approach-x-off": v(APPROACH_SYSTEM, LOCATE_USER, "approach_tool", APPROACH_TOOL),
    "act-target-brief": v(LOCATE_SYSTEM + BRIEF, LOCATE_USER, "act_tool", ACT_TOOL, thinking=True),
    "act-target-budget32": v(LOCATE_SYSTEM + BRIEF, LOCATE_USER, "act_tool", ACT_TOOL, thinking=True,
                             extra={"reasoning_budget_tokens": 32, "max_tokens": 96}),
    # D. no tool call: constrained plain content
    "json-schema-off": v(JSON_SYSTEM, LOCATE_USER, "json", extra={
        "max_tokens": 48, "response_format": {"type": "json_schema", "json_schema": {
            "name": "act", "strict": True, "schema": JSON_SCHEMA}}}),
    "json-x-schema-off": v(JSON_X_SYSTEM, LOCATE_USER, "json", extra={
        "max_tokens": 48, "response_format": {"type": "json_schema", "json_schema": {
            "name": "act", "strict": True, "schema": JSON_X_SCHEMA}}}),
    "dsl-grammar-off": v(DSL_SYSTEM, LOCATE_USER, "dsl", extra={"max_tokens": 24, "grammar": DSL_GRAMMAR}),
    "where-grammar-off": v(WHERE_SYSTEM, WHERE_USER, "where", extra={"max_tokens": 4, "grammar": WHERE_GRAMMAR}),
    "where-free-off": v(WHERE_SYSTEM, WHERE_USER, "where", extra={"max_tokens": 4}),
    "x-grammar-off": v(X_SYSTEM, X_USER, "x", extra={"max_tokens": 4, "grammar": X_GRAMMAR}),
    "box-off": v(None, BOX_USER, "box", extra={"max_tokens": 64}),
}
# E. prompt order: static text before the image so the whole prefix is cacheable
for name in ("approach-x-off", "where-grammar-off", "x-grammar-off", "json-x-schema-off", "box-off"):
    VARIANTS[name + "-textfirst"] = {**VARIANTS[name], "order": "text_first"}
# F. client-side image downscale (fewer vision patches and image tokens). 480x320 and 360x240 fall
#    below llama.cpp's 70-token floor and are resized again by the server; 480x336 is exactly 70 tokens.
for name in ("approach-x-off", "where-grammar-off", "x-grammar-off", "box-off"):
    for size in ((480, 320), (360, 240)):
        VARIANTS[f"{name}-w{size[0]}"] = {**VARIANTS[name], "image_size": size}

# G. static question in the system turn (cacheable); the user turn is the image alone
VARIANTS.update({
    "where-sys": v(WHERE_SYS_SYSTEM, None, "where", extra={"max_tokens": 4, "grammar": WHERE_GRAMMAR}),
    "x-sys": v(X_SYS_SYSTEM, None, "x", extra={"max_tokens": 4, "grammar": X_GRAMMAR}),
    # H. detection with the fixed JSON preamble moved into an assistant prefill
    "box-prefill": v(None, BOX_USER, "box_prefill", prefill=BOX_PREFILL, extra={"max_tokens": 24, "stop": ["]"]}),
    # I. one action per frame (closed loop) instead of a multi-action plan
    "next-tool": v(NEXT_SYSTEM, NEXT_USER, "next_tool", NEXT_TOOL),
    "next-atomic": v(NEXT_SYSTEM, NEXT_USER, "next_tool", NEXT_ATOMIC),
    "next-grammar": v(NEXT_SYSTEM, NEXT_USER, "next_word", extra={"max_tokens": 6, "grammar": NEXT_GRAMMAR}),
    "next-grammar-sys": v(NEXT_SYSTEM + " Answer with the action only.", None, "next_word",
                          extra={"max_tokens": 6, "grammar": NEXT_GRAMMAR}),
    # J. two requests on one KV: perceive (2 tokens), then a native plan tool call given that percept
    #    (tools are declared in both requests so the prompt prefix, image included, is shared)
    "where-then-plan": v(RULE_SYSTEM, WHERE_USER, "plan_tool", PLAN_TOOL, extra={"max_tokens": 4},
                         stage2={"user": STAGE2_USER}),
    # K. tool call whose argument is the grounded percept; the robot-side tool does the geometry
    "face-tool": v(WHERE_SYSTEM, FACE_USER, "face_tool", FACE_TOOL),
    "approach-x-ask": v(WHERE_SYSTEM, APPROACH_USER, "approach_tool", APPROACH_TOOL),
})
for name in ("where-sys", "x-sys", "box-prefill", "where-then-plan", "face-tool", "approach-x-ask",
             "where-grammar-off", "x-grammar-off"):
    VARIANTS[name + "-480x336"] = {**VARIANTS[name], "image_size": (480, 336)}
VARIANTS["where-free-off-480x336"] = {**VARIANTS["where-free-off"], "image_size": (480, 336)}
# L. finalists as JPEG, and at 384x240 = 40 tokens (needs the server started with --image-min-tokens 40)
for name in ("where-grammar-off", "face-tool", "box-prefill"):
    VARIANTS[name + "-480x336-jpeg"] = {**VARIANTS[name], "image_size": (480, 336), "jpeg": True}
    VARIANTS[name + "-384x240"] = {**VARIANTS[name], "image_size": (384, 240)}
# M. target may be absent: a fourth answer instead of a forced left/center/right guess
WHERE4_USER = ("Is the fridge in the left third, center third, or right third of the image, or not visible? "
               "Answer with one word: left, center, right, or none.")
FACE4_USER = ("Is the fridge in the left third, center third, or right third of the image, or not visible? "
              "Call face_target with that position, using none if no fridge is visible.")
FACE4_TOOL = fn("face_target", "Turn to face the target, then take one step toward it.", {
    "position": {"type": "string", "enum": ["left", "center", "right", "none"],
                 "description": "Third of the image containing the target, or none if it is not visible."}},
    ["position"])
VARIANTS.update({
    "where4-grammar-480x336": v(WHERE_SYSTEM, WHERE4_USER, "where", image_size=(480, 336), extra={
        "max_tokens": 4, "grammar": 'root ::= "left" | "center" | "right" | "none"'}),
    "face4-tool-480x336": v(WHERE_SYSTEM, FACE4_USER, "face_tool", FACE4_TOOL, image_size=(480, 336)),
    "box-off-480x336": {**VARIANTS["box-off"], "image_size": (480, 336)},
})
# N. presence gate: "is it there?" first, then "where?" as a second turn that reuses the image KV
GATE_USER = "Is a refrigerator visible in this image? Answer with one word: yes or no."
VARIANTS.update({
    "present-only-480x336": v(WHERE_SYSTEM, GATE_USER, "present", image_size=(480, 336),
                              extra={"max_tokens": 3, "grammar": 'root ::= "yes" | "no"'}),
    "gate-where-480x336": v(WHERE_SYSTEM, WHERE_USER, "where", image_size=(480, 336), gate=GATE_USER,
                            extra={"max_tokens": 4, "grammar": WHERE_GRAMMAR}),
})
