"""Desk gate (DEV_WORKFLOW S1, no robot, about a minute): compile, the geometry and motion tests, the reach replay, calib freshness,
then mock runs that would have caught each V2_REVIEW blocker:
  kill   the mock kill test: --probe with no hidden error gives the hand constant K (as the owner-approved pose will on the robot)
  servo  an order with a hidden error the model alone misses (true palm 3.6 cm behind the model, 1 cm high) and K: >= 1 servo correction,
         the first close a grasp, the approach closing on a measured gap under 1 cm with no abort, success
  model  the same order without K: the first close is NOT a grasp (the model alone misses)
  contact the open hand meets the can 1 cm before the closure pose: the approach aborts and the hand does not close there (the
         2d4f1ca rule turned that abort into the closure trigger)
  abort  the 'a' key during the approach: the hand goes up and back (retreat-up, retreat-back) before any home or park, the descent
         retraces the raise (never further ahead at the table-top height than the raise), parks at home
  dry    --dry: the arm is never enabled, no park, no home
  block  --air with a box at chest height: refused before any motion
  air    --air: sag baselines at the raise and the high waypoint, the corrected pre-grasp within 6 mm, five steps, slide end within 1 cm
Run: ~/miniforge3/envs/brain/bin/python -B check.py   (exit 1 on any failure)."""
import glob, json, os, re, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); PY = sys.executable; ok = True; TMP = tempfile.mkdtemp(prefix="brain-check-")
MOCK = {"BRAIN_MOCK_SCENE": "mid", "BRAIN_MOCK_ORDERS": "silver", "BRAIN_MOCK_SLEEP": "0.05"}
BASE = [PY, "-B", "brain.py", "--mock", "--mock-gemma", "--no-preflight", "--orders", "1", "--pause", "0.3", "--release-after", "4", "--accept-calib"]


def report(name, good, t0, detail=""):
    global ok
    ok = ok and good; print("%-34s %s %5.1fs %s" % (name, "ok " if good else "FAIL", time.time() - t0, detail), flush=True)


def run(name, cmd, timeout=300):
    t0 = time.time(); r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout)
    report(name, r.returncode == 0, t0)
    if r.returncode != 0: print((r.stdout + r.stderr)[-3000:])
    return r


def start(case, args, env):
    runs = os.path.join(TMP, case); log = open(os.path.join(TMP, case + ".log"), "w")
    full = dict(os.environ); full.update(MOCK); full.update(env)
    p = subprocess.Popen(BASE + args + ["--runs", runs], cwd=HERE, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=full)
    return {"case": case, "p": p, "runs": runs, "log": os.path.join(TMP, case + ".log"), "t0": time.time()}


def finish(job, timeout=600):
    job["p"].wait(timeout=timeout); out = open(job["log"]).read()
    files = sorted(glob.glob(os.path.join(job["runs"], "2*", "order_01.jsonl")))
    ev = [json.loads(l) for l in open(files[-1])] if files else []
    return out, ev


def result(ev): return next((e.get("result") for e in ev if e.get("ev") == "result"), None)
def first(ev, kind, **kw): return next((e for e in ev if e.get("ev") == kind and all(e.get(k) == v for k, v in kw.items())), None)


run("compile", [PY, "-B", "-m", "py_compile", "brain.py", "geom.py", "gemma.py", "motion.py", "calib.py", "mock_robot.py", "preflight.py", "brainview.py", "replay_reach.py", "test_geom.py", "test_motion.py"])
run("test_geom", [PY, "-B", "test_geom.py"])
run("test_motion (blocker 1)", [PY, "-B", "test_motion.py"])
run("replay_reach", [PY, "-B", "replay_reach.py"])
run("calib", [PY, "-B", "calib.py"])

# the mock kill test: no hidden error, the probe's `off` is K
t0 = time.time(); out, ev = finish(start("kill", ["--probe"], {"BRAIN_MOCK_ERR": "0.096", "BRAIN_MOCK_ERRK": "0", "BRAIN_MOCK_ERRZ": "0"}))
probe = (first(ev, "result") or {}).get("probe") or {}; K = probe.get("off")
report("kill test (K from the probe)", result(ev) == "probe" and K is not None and probe.get("n_blob", 0) > 300, t0, "K %s, %s hand points" % (K, probe.get("n_blob")))
if K is None: print(out[-2500:]); print("CHECK: FAIL"); sys.exit(1)

hidden = {"BRAIN_MOCK_ERR": "0.06", "BRAIN_MOCK_ERRK": "0", "BRAIN_MOCK_ERRZ": "0.01"}
jobs = [start("servo", ["--K"] + ["%.4f" % v for v in K], hidden), start("model", [], hidden),
        start("contact", ["--K"] + ["%.4f" % v for v in K], {"BRAIN_MOCK_CONTACT": "0.02"}),
        start("abort", [], {"BRAIN_MOCK_ABORT_AT": "APPROACH"}), start("dry", ["--dry"], {}),
        start("block", ["--air", "--air-can", "0.38", "0.15", "--air-table", "0.075"], {"BRAIN_MOCK_SCENE": "none", "BRAIN_MOCK_OBSTACLE": "1"}),
        start("air", ["--air", "--air-can", "0.38", "0.15", "--air-table", "0.075"], {"BRAIN_MOCK_SCENE": "none"})]
res = {j["case"]: (j,) + finish(j) for j in jobs}

j, out, ev = res["servo"]
stalls = [e for e in ev if e.get("ev") == "stall"]; ap = first(ev, "approach"); servo = (first(ev, "result") or {}).get("servo") or {}
good = result(ev) == "success" and servo.get("corrections", 0) >= 1 and bool(stalls) and stalls[0].get("pattern") == "grasped" and ap is not None and ap.get("result") == "ok" and not ap.get("why") and ap.get("gap", 1) < 0.01
report("servo: hidden error with K", good, j["t0"], "servo corrections %s, first close %s, approach %s gap %s" % (servo.get("corrections"), stalls[0].get("pattern") if stalls else None, ap and ap.get("result"), ap and ap.get("gap")))
if not good: print(out[-3000:])

j, out, ev = res["model"]
stalls = [e for e in ev if e.get("ev") == "stall"]
good = bool(stalls) and stalls[0].get("pattern") != "grasped"
report("model alone misses (no K)", good, j["t0"], "first close %s, result %s" % (stalls[0].get("pattern") if stalls else None, result(ev)))
if not good: print(out[-3000:])

j, out, ev = res["contact"]
i_ap = next((i for i, e in enumerate(ev) if e.get("ev") == "approach"), None); i_close = next((i for i, e in enumerate(ev) if e.get("ev") == "hand"), None)
i_ret = next((i for i, e in enumerate(ev) if e.get("ev") == "move" and e.get("label") == "retreat-up"), None)
good = i_ap is not None and ev[i_ap].get("result") == "aborted" and (i_close is None or (i_ret is not None and i_ret < i_close))
report("contact before closure: no close", good, j["t0"], "first approach %s (%s), first close after the retreat: %s" % (i_ap is not None and ev[i_ap].get("result"), i_ap is not None and ev[i_ap].get("why"), i_close is None or (i_ret is not None and i_ret < i_close)))
if not good: print(out[-3000:])

j, out, ev = res["abort"]
labels = [(i, e.get("ev"), e.get("label")) for i, e in enumerate(ev) if e.get("ev") in ("move", "home", "park")]
i_up = next((i for i, k, l in labels if l == "retreat-up"), None); i_back = next((i for i, k, l in labels if l == "retreat-back"), None)
i_home = next((i for i, k, l in labels if k in ("home", "park")), None); park = first(ev, "park"); home = first(ev, "home")
keep = {e["label"].split(" ")[0]: e["reach_x"] for e in ev if e.get("ev") == "keepout"}
good = (result(ev) == "aborted" and None not in (i_up, i_back, i_home) and i_up < i_back < i_home and park is not None and park.get("pose") == "home" and park["palm"][0] < 0.25
        and home is not None and home.get("how") == "the raise retraced" and keep.get("home", 9) <= keep.get("up", -9) + 0.01)
report("abort beside the can (blocker 2)", good, j["t0"], "retreat-up %s, retreat-back %s, first home/park %s, park %s, home %s (low reach %s vs raise %s)" % (i_up, i_back, i_home, park and park.get("palm"), home and home.get("how"), keep.get("home"), keep.get("up")))
if not good: print(out[-3000:])

j, out, ev = res["dry"]
good = result(ev) == "dry" and "arm streamer enabled" not in out and "Parking." not in out and "SAY: Home." not in out
report("--dry never moves (blocker 3)", good, j["t0"], "result %s" % result(ev))
if not good: print(out[-3000:])

j, out, ev = res["block"]
good = result(ev) == "blocked" and "Raising." not in out and "arm streamer enabled" not in out.split("left arm parked")[-1]
report("air test 0.30 m rule (blocker 5)", good, j["t0"], "result %s" % result(ev))
if not good: print(out[-3000:])

j, out, ev = res["air"]
o = (first(ev, "result") or {}).get("air") or {}; sag = o.get("sag") or {}; moved = re.findall(r"air\d: moved ([0-9.\-]+)", out)
good = result(ev) == "air" and 0.02 <= sag.get("up", 0) <= 0.05 and 0.02 <= sag.get("high", 0) <= 0.06 and (o.get("pre_err") or 1) < 0.006 and len(moved) == 5 and (o.get("slide_err") or 1) < 0.01
report("air test (blocker 4 data)", good, j["t0"], "sag up %s high %s, pre err %s, moved %s, slide-end err %s" % (sag.get("up"), sag.get("high"), o.get("pre_err"), moved, o.get("slide_err")))
if not good: print(out[-3000:])

print("CHECK:", "PASS" if ok else "FAIL", "(logs in %s)" % TMP); sys.exit(0 if ok else 1)
