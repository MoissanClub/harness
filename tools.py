"""Equivalent tool encodings for pure mock actions; no hardware integration."""

import json

DIRECTIONS = ("left", "right", "forward", "backward", "turn_left", "turn_right")
FORMATS = ("combined", "split", "atomic", "plan")
STEP_METERS = 0.25
TURN_DEGREES = 30


def function(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False},
    }}


def enum(values):
    return {"type": "string", "enum": list(values)}


def tool_schemas(format_name, max_actions=4):
    motion = "left/right strafe; forward/backward translate; turn_left/turn_right rotate."
    if format_name == "combined":
        return [function("move", "One action: " + motion,
                         {"direction": enum(DIRECTIONS)}, ["direction"])]
    if format_name == "split":
        return [
            function("move", "Translate one step; left/right strafe without turning.",
                     {"direction": enum(DIRECTIONS[:4])}, ["direction"]),
            function("turn", "Rotate in place toward the given side.",
                     {"direction": enum(("left", "right"))}, ["direction"]),
        ]
    if format_name == "atomic":
        descriptions = (
            "Strafe left without turning.", "Strafe right without turning.",
            "Translate forward.", "Translate backward.",
            "Rotate left in place.", "Rotate right in place.",
        )
        return [function(action if action.startswith("turn_") else "move_" + action,
                         description, {}, [])
                for action, description in zip(DIRECTIONS, descriptions)]
    if format_name == "plan":
        return [function("plan", "Ordered actions: " + motion, {
            "actions": {"type": "array", "items": enum(DIRECTIONS),
                        "minItems": 1, "maxItems": max_actions},
        }, ["actions"])]
    raise ValueError(f"Unknown format: {format_name}")


def encode_actions(actions, format_name):
    """Reference encodings for tests/token counts, never shown as vision answers."""
    if format_name not in FORMATS or any(action not in DIRECTIONS for action in actions):
        raise ValueError("Unknown format or action")
    functions = []
    for action in actions:
        if format_name == "combined":
            name, arguments = "move", {"direction": action}
        elif format_name == "split":
            name, arguments = (("turn", {"direction": action[5:]}) if action.startswith("turn_")
                               else ("move", {"direction": action}))
        elif format_name == "atomic":
            name, arguments = action if action.startswith("turn_") else "move_" + action, {}
        else:
            break
        functions.append((name, arguments))
    if format_name == "plan":
        functions = [("plan", {"actions": actions})]
    return [{"id": f"ref_{i}", "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments),
    }} for i, (name, arguments) in enumerate(functions)]


def decode_call(call, format_name):
    if not isinstance(call, dict) or call.get("type") != "function":
        raise ValueError("Expected a function tool call")
    fn = call.get("function", {})
    if not isinstance(fn, dict):
        raise ValueError("Malformed function")
    name, arguments = fn.get("name"), fn.get("arguments")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    schemas = {tool["function"]["name"]: tool["function"]["parameters"]
               for tool in tool_schemas(format_name)}
    if not isinstance(name, str) or name not in schemas:
        raise ValueError(f"Unknown {format_name} tool: {name}")
    properties = schemas[name]["properties"]
    if not isinstance(arguments, dict) or set(arguments) != set(properties):
        raise ValueError(f"{name} requires exactly these arguments: {list(properties)}")
    if format_name == "atomic":
        return [name if name.startswith("turn_") else name[5:]]
    if format_name == "plan":
        actions = arguments["actions"]
        if not isinstance(actions, list) or not actions:
            raise ValueError("actions must be a nonempty array")
        if any(not isinstance(action, str) or action not in DIRECTIONS for action in actions):
            raise ValueError("Invalid action")
        return actions
    direction = arguments["direction"]
    if not isinstance(direction, str) or direction not in properties["direction"]["enum"]:
        raise ValueError("Invalid direction")
    return ["turn_" + direction if name == "turn" else direction]


def record_batch(calls, plan, max_actions, seen_ids, format_name="combined"):
    """Validate the entire batch before recording; returned array order is plan order."""
    if not isinstance(calls, list) or not calls:
        raise ValueError("Expected a nonempty tool call array")
    decoded = [decode_call(call, format_name) for call in calls]
    if len(plan) + sum(map(len, decoded)) > max_actions:
        raise ValueError(f"Plan exceeds the {max_actions}-action limit; batch rejected")
    ids = [call.get("id") for call in calls]
    if any(not isinstance(ident, str) or not ident for ident in ids):
        raise ValueError("Every call requires a nonempty string id")
    if len(set(ids)) != len(ids) or seen_ids.intersection(ids):
        raise ValueError("Tool call ids must be unique")
    updated_plan = list(plan)
    results = []
    for actions in decoded:
        for action in actions:
            updated_plan.append(action)
            result = {"direction": action, "executed": False,
                      "plan_index": len(updated_plan), "planned_actions": list(updated_plan)}
            if action.startswith("turn_"):
                result["requested_turn_degrees"] = TURN_DEGREES
            else:
                result["requested_step_m"] = STEP_METERS
            results.append(result)
    return updated_plan, results
