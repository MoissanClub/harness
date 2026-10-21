"""calib.json: every measured number the brain uses, with provenance (value, unit, frame, method, date, pose, can, n, log), per
DEV_WORKFLOW.md and V2_STRATEGY.md rule 1. brain.py loads it, prints the table at start, logs its sha256 and the git SHA into every
order, logs each CLI override as a `deviation` event and refuses entries older than their validity window unless --accept-calib.
Usage as a script: python calib.py  (prints the table and checks freshness)."""
import hashlib, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "calib.json")


def load(path=PATH):
    with open(path) as f: raw = f.read()
    data = json.loads(raw); data["_sha256"] = hashlib.sha256(raw.encode()).hexdigest()[:16]; data["_path"] = path
    return data


def value(cal, key):
    return cal["entries"][key]["value"]


def git_sha(cwd=HERE):
    try: return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip() or "?"
    except Exception: return "?"


def git_dirty(cwd=HERE):
    try: return bool(subprocess.run(["git", "status", "--porcelain", "--", HERE], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip())
    except Exception: return True


def stale(cal, now=None):
    """Entries past their validity window (days since `date` > `valid_days`)."""
    now = time.time() if now is None else now; out = []
    for k, e in cal["entries"].items():
        if "valid_days" not in e or "date" not in e: continue
        age = (now - time.mktime(time.strptime(e["date"], "%Y-%m-%d"))) / 86400.0
        if age > float(e["valid_days"]): out.append((k, round(age, 1), e["valid_days"]))
    return out


def table(cal):
    rows = ["%-22s %10s %-6s %-14s %-10s n=%-3s %s" % (k, e["value"] if not isinstance(e["value"], list) else "[%s]" % ", ".join(str(v) for v in e["value"]), e.get("unit", ""), e.get("frame", ""), e.get("date", ""), e.get("n", "-"), e.get("method", "")[:70]) for k, e in cal["entries"].items()]
    return "calib %s sha %s git %s%s\n" % (os.path.basename(cal["_path"]), cal["_sha256"], git_sha(), " (dirty)" if git_dirty() else "") + "\n".join(rows)


def deviations(cal, args, mapping):
    """CLI values that differ from the calibration: [(key, calib value, cli value)]. mapping: {arg name: calib key}."""
    out = []
    for arg, key in mapping.items():
        if key not in cal["entries"]: continue
        v = getattr(args, arg, None); c = cal["entries"][key]["value"]
        if v is None: continue
        if c is None: same = False                                               # the calibration has no value yet: any CLI value is a deviation
        elif isinstance(c, list): same = isinstance(v, (list, tuple)) and len(v) == len(c) and all(abs(float(a) - float(b)) < 1e-9 for a, b in zip(v, c))
        else: same = not isinstance(v, (list, tuple)) and abs(float(v) - float(c)) < 1e-9
        if not same: out.append((key, c, list(v) if isinstance(v, tuple) else v))
    return out


if __name__ == "__main__":
    cal = load(); print(table(cal))
    st = stale(cal)
    print("stale:", st if st else "none")
    sys.exit(1 if st else 0)
