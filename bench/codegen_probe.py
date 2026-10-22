#!/usr/bin/env python3
"""Can the model write code for a task it has never seen, and does that code run? (stdlib only)

The model gets a small robot API (look, pick, give, place, say, listen, wave) and one task in plain words,
and must answer with `def task(robot):`. The code then runs in a separate `python3 -I` process against
two or three different table layouts; a task passes only if every layout ends in the right state, so code
that hard-codes one table fails. Model-written code runs on the machine running this script, never on PC2:
point --base-url at the robot through an ssh tunnel (ssh -N -L 18080:127.0.0.1:8080 g1).
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
from client import get_json, timed_chat  # noqa: E402

API = """You write Python for a humanoid drinks robot standing at a table of drink cans.
Reply with one Python code block that defines `def task(robot):` and nothing else. No imports are needed.
Keep the code short: no comments, and speak only when the task asks for it.

The robot API (all you may use, besides Python built-ins):
- robot.look() -> list of dicts, one per can still on the table: {"id": int, "colour": str, "label": str, "x": float, "y": float}
  x is centimetres to the robot's left (negative = right of the robot), y is centimetres ahead.
- robot.pick(can_id) -> bool. Picks that can up. The robot holds at most one can; pick fails while holding one.
- robot.give() -> bool. Hands the held can to the guest.
- robot.place(spot) -> bool. Puts the held can down at spot, "tray" or "table".
- robot.say(text) -> None. Speaks to the guest.
- robot.listen() -> str. Waits for the guest to speak and returns what they said, in English.
- robot.wave() -> None. Waves at the guest."""

# Each task: words for the model, the worlds it runs in, and a check on the final state of each world.
# A world is a list of cans (colour, label, x, y) plus what the guest says when listened to.
W = {
    "mix": [("red", "Coca-Cola", 20, 35), ("green", "Sprite", 5, 36), ("blue", "Pepsi", -12, 34), ("red", "Fanta Cherry", -25, 38)],
    "mix2": [("blue", "Pepsi", 22, 33), ("silver", "Diet Coke", 8, 37), ("red", "Coca-Cola", -6, 35), ("green", "Sprite", -21, 36),
             ("green", "Sprite", 30, 40)],
    "two": [("green", "Sprite", -10, 34), ("red", "Coca-Cola", 15, 36)],
    "reds": [("red", "Coca-Cola", 18, 35), ("red", "Dr Pepper", -2, 34), ("blue", "Pepsi", -20, 37)],
    "blues": [("blue", "Pepsi", 18, 35), ("red", "Coca-Cola", -2, 34), ("blue", "Pepsi Max", -20, 37), ("blue", "Bud Light", 4, 30)],
}


def cans(name):
    return [{"id": 10 + i, "colour": c, "label": l, "x": float(x), "y": float(y)} for i, (c, l, x, y) in enumerate(W[name])]


def num_said(said, n):
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    text = " ".join(said).lower()
    return bool(re.search(r"\b%d\b" % n, text) or re.search(r"\b%s\b" % words[n], text))


def ids(world, pred):
    return sorted(c["id"] for c in world if pred(c))


TASKS = [
    {"name": "not-red", "task": "Hand the guest every can that is not red, one at a time.",
     "worlds": ["mix", "mix2", "reds"],
     "check": lambda w, s: sorted(s["given"]) == ids(w, lambda c: c["colour"] != "red") and not s["held"]},
    {"name": "count", "task": "Tell the guest how many cans are on the table.",
     "worlds": ["mix", "mix2", "two"],
     "check": lambda w, s: num_said(s["said"], len(w)) and not s["given"] and not s["tray"]},
    {"name": "leftmost", "task": "Give the guest the can that is furthest to the robot's left.",
     "worlds": ["mix", "mix2", "two"],
     "check": lambda w, s: s["given"] == [max(w, key=lambda c: c["x"])["id"]]},
    {"name": "greens-tray-wave", "task": "Put every green can on the tray, then wave once at the end.",
     "worlds": ["mix", "mix2", "reds"],
     "check": lambda w, s: sorted(s["tray"]) == ids(w, lambda c: c["colour"] == "green") and not s["given"]
              and s["log"][-1:] == ["wave"] and s["log"].count("wave") == 1},
    {"name": "ask-colour", "task": "Ask the guest which colour they would like and give them a can of that colour. "
                                   "If there is no can of that colour, say sorry and give nothing.",
     "worlds": [("mix", "Blue, please."), ("mix2", "I'd like a purple one."), ("two", "green")],
     "check": lambda w, s: (s["given"] and len(s["given"]) == 1
                            and next(c for c in w if c["id"] == s["given"][0])["colour"] == s["want"])
              if any(c["colour"] == s["want"] for c in w)
              else (not s["given"] and any("sorry" in t.lower() for t in s["said"]))},
    {"name": "right-to-left", "task": "Move all the cans onto the tray, starting with the one furthest to the robot's right "
                                      "and working towards its left.",
     "worlds": ["mix", "mix2", "two"],
     "check": lambda w, s: s["tray"] == [c["id"] for c in sorted(w, key=lambda c: c["x"])]},
    {"name": "majority", "task": "If there are more red cans than blue cans, give the guest one red can; otherwise give them one blue can.",
     "worlds": ["reds", "blues", "mix"],
     "check": lambda w, s: len(s["given"]) == 1 and next(c for c in w if c["id"] == s["given"][0])["colour"]
              == ("red" if sum(c["colour"] == "red" for c in w) > sum(c["colour"] == "blue" for c in w) else "blue")},
    {"name": "two-colours", "task": "Give the guest two cans of different colours.",
     "worlds": ["mix", "mix2", "blues"],
     "check": lambda w, s: len(s["given"]) == 2
              and len({next(c for c in w if c["id"] == i)["colour"] for i in s["given"]}) == 2},
    {"name": "closest-label", "task": "The guest wants a Sprite. Give them the Sprite can closest to the robot, "
                                      "or tell them there is none.",
     "worlds": ["mix", "mix2", "reds"],
     "check": lambda w, s: (s["given"] == [min((c for c in w if c["label"] == "Sprite"),
                                                key=lambda c: (c["x"] ** 2 + c["y"] ** 2))["id"]])
              if any(c["label"] == "Sprite" for c in w) else (not s["given"] and bool(s["said"]))},
]



def dist(c):
    return (c["x"] ** 2 + c["y"] ** 2) ** 0.5


def colour_of(w, i):
    return next(c for c in w if c["id"] == i)["colour"]


def most_common(w):
    colours = [c["colour"] for c in w]
    return max(set(colours), key=colours.count)


# Harder: number words, retries, relative position, grouping. A world spec may carry (name, heard, slips).
HARD = [
    {"name": "middle", "task": "Give the guest the middle can of the row, counting from left to right. If the number of cans "
                               "is even there is no middle can: say so and give nothing.",
     "worlds": ["mix", "mix2", "reds"],
     "check": lambda w, s: (s["given"] == [sorted(w, key=lambda c: c["x"])[len(w) // 2]["id"]]) if len(w) % 2
              else (not s["given"] and bool(s["said"]))},
    {"name": "retry-slip", "task": "Give the guest the can furthest to the robot's left. Cans can slip, so pick may fail: "
                                   "try again, at most three tries in total. If all three tries fail, say sorry and give nothing.",
     "worlds": [("mix", "", {10: 2}), ("mix2", "", {14: 3}), ("two", "", {})],
     "check": lambda w, s: s["log"].count("pick") <= 3 and (
         (s["given"] == [max(w, key=lambda c: c["x"])["id"]]) if s["slips"].get(str(max(w, key=lambda c: c["x"])["id"]), 0) < 3
         else (not s["given"] and any("sorry" in t.lower() for t in s["said"])))},
    {"name": "right-of-pepsi", "task": "Give the guest the can immediately to the robot's right of the Pepsi can (the closest "
                                       "one on that side). If no can is to the Pepsi's right, say so and give nothing.",
     "worlds": ["mix", "mix2", "reds"],
     "check": lambda w, s: (lambda p: (lambda right: (s["given"] == [max(right, key=lambda c: c["x"])["id"]]) if right
                                       else (not s["given"] and bool(s["said"])))([c for c in w if c["x"] < p["x"]]))(
         next(c for c in w if c["label"] == "Pepsi"))},
    {"name": "how-many", "task": "Ask the guest how many cans they want and give them that many, closest to the robot first. "
                                 "If they want more than there are, give them all and tell them that is all there is.",
     "worlds": [("mix", "Two, please."), ("two", "Three cans, please."), ("mix2", "Just one.")],
     "check": lambda w, s: (lambda n: s["given"] == [c["id"] for c in sorted(w, key=dist)][:n] and (
         n <= len(w) or any(k in t.lower() for t in s["said"] for k in ("all", "only", "no more"))))(
         {"Two, please.": 2, "Three cans, please.": 3, "Just one.": 1}[s["heard"]])},
    {"name": "common-first", "task": "Put all the cans on the tray, starting with every can of the most common colour, "
                                     "then the rest in any order.",
     "worlds": ["mix", "mix2", "blues"],
     "check": lambda w, s: sorted(s["tray"]) == ids(w, lambda c: True) and all(
         colour_of(w, i) == most_common(w) for i in s["tray"][:sum(c["colour"] == most_common(w) for c in w)])},
    {"name": "one-per-colour", "task": "Leave exactly one can of each colour on the table and put every other can on the tray.",
     "worlds": ["mix", "mix2", "blues"],
     "check": lambda w, s: sorted(c["colour"] for c in s["table"]) == sorted({c["colour"] for c in w})
              and sorted(s["tray"] + [c["id"] for c in s["table"]]) == ids(w, lambda c: True) and not s["given"]},
]
SETS = {"basic": TASKS, "hard": HARD, "all": TASKS + HARD}

# Runs inside the child process: the mock robot, the model's code, and a JSON report of the final state.
RUNNER = r'''
import json, sys
world = json.loads(sys.argv[2]); heard = sys.argv[3]; slips = json.loads(sys.argv[4])
class Robot:
    def __init__(self):
        self.table = [dict(c) for c in world]; self.held = None
        self.s = {"given": [], "tray": [], "said": [], "log": [], "held": None, "errors": []}
    def look(self):
        self.s["log"].append("look"); return [dict(c) for c in self.table]
    def pick(self, can_id):
        self.s["log"].append("pick")
        c = next((c for c in self.table if c["id"] == can_id), None)
        if self.held is not None or c is None:
            self.s["errors"].append("pick(%r) refused" % (can_id,)); return False
        if slips.get(str(can_id), 0) > 0:
            slips[str(can_id)] -= 1; return False
        self.table.remove(c); self.held = c["id"]; self.s["held"] = self.held; return True
    def give(self):
        self.s["log"].append("give")
        if self.held is None: self.s["errors"].append("give with empty hand"); return False
        self.s["given"].append(self.held); self.held = None; self.s["held"] = None; return True
    def place(self, spot):
        self.s["log"].append("place")
        if self.held is None or spot not in ("tray", "table"):
            self.s["errors"].append("place(%r) refused" % (spot,)); return False
        if spot == "tray": self.s["tray"].append(self.held)
        else: c = next(c for c in world if c["id"] == self.held); self.table.append(dict(c))
        self.held = None; self.s["held"] = None; return True
    def say(self, text):
        self.s["log"].append("say"); self.s["said"].append(str(text))
    def listen(self):
        self.s["log"].append("listen"); return heard
    def wave(self):
        self.s["log"].append("wave")
robot = Robot(); ns = {}
try:
    exec(compile(open(sys.argv[1]).read(), "model_code", "exec"), ns)
    ns["task"](robot)
except BaseException as e:
    robot.s["errors"].append("%s: %s" % (type(e).__name__, e))
robot.s["table"] = robot.table
print(json.dumps(robot.s))
'''


def extract_code(text):
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)(?:```|$)", text, re.S)  # an unclosed block was cut by max_tokens
    code = max(blocks, key=len) if blocks else text
    return code if "def task" in code else None


UNSAFE = re.compile(r"\b(os|sys|subprocess|shutil|socket|pathlib|ctypes)\b|\bopen\(|__import__|\beval\(|\bexec\(")


def run_code(code, task, tmp):
    src, runner = Path(tmp) / "model_code.py", Path(tmp) / "runner.py"
    if UNSAFE.search(code):
        return [{"world": "-", "ok": False, "errors": ["refused: code reaches for the OS"]}]
    src.write_text(code)
    runner.write_text(RUNNER)
    results = []
    for spec in task["worlds"]:
        name, heard, slips = (tuple(spec) + ("", {})[len(spec) - 1:])[:3] if isinstance(spec, tuple) else (spec, "", {})
        slips = {str(k): v for k, v in slips.items()}
        world = cans(name)
        try:
            out = subprocess.run([sys.executable, "-I", str(runner), str(src), json.dumps(world), heard, json.dumps(slips)],
                                 capture_output=True, text=True, timeout=5, cwd=tmp)
            state = json.loads(out.stdout.strip().splitlines()[-1])
        except Exception as error:  # timeout, crash before the report, or garbage output
            results.append({"world": name, "ok": False, "errors": [f"runner: {type(error).__name__}: {error}"]})
            continue
        want = next((c for c in ("red", "green", "blue", "silver", "purple") if c in heard.lower()), None)
        try:
            ok = bool(task["check"](world, {**state, "want": want, "heard": heard, "slips": slips}))
        except Exception as error:
            ok, state["errors"] = False, state["errors"] + [f"check: {error}"]
        crashed = any(not e.startswith(("pick(", "place(", "give with")) for e in state["errors"])
        results.append({"world": name, "ok": ok and not state["errors"], "lenient": ok and not crashed, "errors": state["errors"],
                        "given": state["given"], "tray": state["tray"], "said": state["said"][:3]})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="gemma4")
    parser.add_argument("--tag", default="default", help="label for the model and server under test")
    parser.add_argument("--thinking", action="store_true", help="let the model think before the code")
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--set", choices=list(SETS), default="basic", help="basic: 9 one-step tasks; hard: 6 harder ones")
    parser.add_argument("--tasks", default="", help="comma-separated task names within the set (default: all)")
    args = parser.parse_args()
    tasks = [t for t in SETS[args.set] if not args.tasks or t["name"] in args.tasks.split(",")]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out_dir = ROOT / "experiments" / f"{stamp}-codegen-{args.set}-{args.tag}"
    out_dir.mkdir(parents=True)
    props = get_json(args.base_url, "/props")
    (out_dir / "manifest.json").write_text(json.dumps({**vars(args), "build": props.get("build_info"),
                                                       "model_path": props.get("model_path"),
                                                       "tasks": [t["name"] for t in tasks]}, indent=2) + "\n")
    base = {"model": args.model, "cache_prompt": True, "temperature": 0.0, "top_k": 1, "seed": 0,
            "max_tokens": args.max_tokens, "chat_template_kwargs": {"enable_thinking": args.thinking}}
    # Untimed warm-up primes the system prefix, as a robot that writes code repeatedly would have it.
    timed_chat(args.base_url, {**base, "max_tokens": 4, "messages": [
        {"role": "system", "content": API}, {"role": "user", "content": "Task: say hello."}]})
    rows = []
    with (out_dir / "requests.jsonl").open("w") as log, tempfile.TemporaryDirectory() as tmp:
        for task in tasks:
            result = timed_chat(args.base_url, {**base, "messages": [
                {"role": "system", "content": API}, {"role": "user", "content": "Task: " + task["task"]}]})
            code = extract_code(result["content"])
            worlds = run_code(code, task, tmp) if code else []
            t = result["timings"]
            row = {"task": task["name"], "pass": bool(worlds) and all(w["ok"] for w in worlds),
                   "lenient_pass": bool(worlds) and all(w.get("lenient") for w in worlds),
                   "worlds_ok": sum(w["ok"] for w in worlds), "worlds": len(task["worlds"]),
                   "total_s": round(result["total_s"], 2), "prompt_n": t.get("prompt_n"), "prompt_ms": t.get("prompt_ms"),
                   "predicted_n": t.get("predicted_n"), "predicted_ms": t.get("predicted_ms"),
                   "draft_n": t.get("draft_n"), "draft_n_accepted": t.get("draft_n_accepted"),
                   "finish_reason": result["finish_reason"], "reasoning_chars": len(result["reasoning"]),
                   "code": code, "content": None if code else result["content"], "results": worlds}
            rows.append(row)
            log.write(json.dumps(row) + "\n")
            log.flush()
            errors = sorted({e for w in worlds for e in w["errors"]})[:2]
            print(f"{task['name']:18} {'PASS' if row['pass'] else 'lenient' if row['lenient_pass'] else 'fail'} "
                  f"{row['worlds_ok']}/{row['worlds']} worlds  "
                  f"{row['total_s']:6.2f} s  {row['predicted_n']} tok  {errors if errors else ''}"
                  f"{'' if code else ' (no code block)'}", flush=True)
    decode = [r["predicted_ms"] / r["predicted_n"] for r in rows if r["predicted_n"]]
    summary = {"tag": args.tag, "thinking": args.thinking, "passed": sum(r["pass"] for r in rows),
               "lenient_passed": sum(r["lenient_pass"] for r in rows), "n": len(rows),
               "total_s_p50": statistics.median(r["total_s"] for r in rows),
               "total_s_max": max(r["total_s"] for r in rows),
               "output_tokens_p50": statistics.median(r["predicted_n"] or 0 for r in rows),
               "ms_per_output_token_p50": round(statistics.median(decode), 1) if decode else None}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    print(f"Saved: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
