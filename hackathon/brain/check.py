"""Desk gate (DEV_WORKFLOW S1, no robot, about two minutes): compile, the geometry and motion tests, the reach replay, calib freshness,
the CLI refusals, then mock runs. Every mock run that moves the arm also checks that no joint changed by more than joint_step x speed in
one streamed target (V2_REVIEW round 2 blocker 1), from the mock's `[mock] stats` line.
Round 1 (V2_REVIEW blockers 1-6): kill (K from the mock kill test), servo (a hidden error the model misses: corrected, grasped), model
(the same with --model-grasp and no K: the first close is not a grasp), contact (the hand meets the can 1 cm early: no close), abort
('a' at the approach: up, back, the raise retraced), dry (the arm never enabled), block (a box at chest height: the air test refuses),
air (the sag baselines, the corrected pre-grasp, five steps).
Round 2 blockers, each on a path other than the one the verifiers used (V2_REVIEW_round2.json):
  speed      1: a whole order at --speed 0.5 (raise, high, pre, servo, approach, lift, offer, retreat): no joint step over 0.01 rad
  raisefail  2: a g1-fetch failure at z 0.20 of the raise in an order: the way home retraces the sent part (no joint-space sweep)
  descent    2: 'a' 7 cm down the retraced descent of the air test at (0.35, 0.00), half speed: holds; h + y retrace from there home
  walk       3: 'a' at the approach, 'a' again during the retreat back: holds; h + y go back and down, never further out or up
  quit2      3: 'q' while lowering to the pre-grasp, 'q' again during the shutdown's retreat: holds, never released away from home
  sigint2    3: the same with Ctrl-C: the second one stops the arm (c39a468 ignored it and kept moving)
  table      4: the depth plane 20 mm low (the hand meets the real table) in an order: no command under the floor, push under 3 cm
  fwd39 fwd54  5: forward hidden errors of 3.9 and 5.4 cm with K: the servo reads and corrects them, the first close is a grasp
Must-fix cases: nerr (a 2 cm error along the palm normal: no close), gemma (Gemma's hand box 15 cm off the hand: no approach), noK (no K, no
flag: no grasp, nothing moves), zero and minrange (no valid depth; a box inside the D435i's minimum range: refused), tape and tape8 (the tape
3 cm high, 8 cm low against the depth plane: refused), assist (a box appears after the miss: the retry's locate refuses, no assist).
Run: ~/miniforge3/envs/brain/bin/python -B check.py [--cases a,b,..]   (exit 1 on any failure)
CHECK_TREE=/path/to/other/hackathon/brain runs the mock cases on that brain version with THIS mock (copied in), dropping the flags it
lacks, and its own kill test for K: how the round-2 cases were shown to fail on c39a468."""
import glob, json, os, re, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); PY = sys.executable; ok = True; TMP = tempfile.mkdtemp(prefix="brain-check-")
TREE = os.environ.get("CHECK_TREE"); RUN_DIR = TREE or HERE; MAXJ = int(os.environ.get("CHECK_JOBS", "8"))
MOCK = {"BRAIN_MOCK_SCENE": "mid", "BRAIN_MOCK_ORDERS": "silver", "BRAIN_MOCK_SLEEP": "0.05"}
BASE = [PY, "-B", "brain.py", "--mock", "--mock-gemma", "--no-preflight", "--orders", "1", "--pause", "0.3", "--release-after", "4", "--accept-calib", "--table-edge", "0.34"]
NEW_FLAGS = {"--table-edge": 1, "--expect-calib": 1, "--model-grasp": 0, "--pre-offset": 1, "--pre-stop": 1, "--stuck-reminder": 1}   # not in c39a468
TABLE_Z, HALF_H, MARGIN, JOINT_STEP = 0.075, 0.045, 0.005, 0.02
want = None
if "--cases" in sys.argv: want = set(sys.argv[sys.argv.index("--cases") + 1].split(","))


def report(name, good, t0, detail=""):
    global ok
    ok = ok and good; print("%-38s %s %5.1fs %s" % (name, "ok " if good else "FAIL", time.time() - t0, detail), flush=True)


def run(name, cmd, timeout=300, expect=0):
    t0 = time.time(); r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout)
    report(name, r.returncode == expect, t0)
    if r.returncode != expect: print((r.stdout + r.stderr)[-3000:])
    return r


def args_for_tree(args):
    if not TREE: return args
    out, i = [], 0
    while i < len(args):
        if args[i] in NEW_FLAGS: i += 1 + NEW_FLAGS[args[i]]; continue
        out.append(args[i]); i += 1
    return out


def start(case, args, env):
    runs = os.path.join(TMP, case); log = open(os.path.join(TMP, case + ".log"), "w")
    full = dict(os.environ); full.update(MOCK); full.update(env)
    p = subprocess.Popen(args_for_tree(BASE + args + ["--runs", runs]), cwd=RUN_DIR, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=full)
    return {"case": case, "p": p, "runs": runs, "log": os.path.join(TMP, case + ".log"), "t0": time.time()}


def finish(job, timeout=900):
    try: job["p"].wait(timeout=timeout)
    except subprocess.TimeoutExpired: job["p"].kill(); job["p"].wait()
    out = open(job["log"]).read()
    files = sorted(glob.glob(os.path.join(job["runs"], "2*", "order_01.jsonl")))
    ev = [json.loads(l) for l in open(files[-1])] if files else []
    m = re.findall(r"\[mock\] stats (\{.*\})", out); stats = json.loads(m[-1]) if m else {}
    return out, ev, stats


def result(ev): return next((e.get("result") for e in ev if e.get("ev") == "result"), None)
def first(ev, kind, **kw): return next((e for e in ev if e.get("ev") == kind and all(e.get(k) == v for k, v in kw.items())), None)
def idx(ev, pred): return next((i for i, e in enumerate(ev) if pred(e)), None)
def speed_of(args): return float(args[args.index("--speed") + 1]) if "--speed" in args else 1.0


def joint_step_ok(stats, args):
    """Round 2 blocker 1 on every run that moved the arm: no joint changes by more than joint_step x speed in one target."""
    if not stats or not stats.get("targets"): return True, ""
    cap = JOINT_STEP * speed_of(args) + 1e-4; m = stats.get("max_dq", 0.0)
    return m <= cap, "max joint step %.3f rad (cap %.3f, joint %s after '%s')" % (m, cap, stats.get("max_dq_joint"), (stats.get("max_dq_after") or "")[:24])


# --- the cases: name -> (args, env, check(out, ev, stats) -> (good, detail)) -----------------------------------------------------------
HIDDEN = {"BRAIN_MOCK_ERR": "0.06", "BRAIN_MOCK_ERRK": "0", "BRAIN_MOCK_ERRZ": "0.01"}
NOERR = {"BRAIN_MOCK_ERR": "0.096", "BRAIN_MOCK_ERRK": "0", "BRAIN_MOCK_ERRZ": "0"}


def c_servo(out, ev, st):
    stalls = [e for e in ev if e.get("ev") == "stall"]; ap = first(ev, "approach"); servo = (first(ev, "result") or {}).get("servo") or {}
    good = result(ev) == "success" and servo.get("corrections", 0) >= 1 and bool(stalls) and stalls[0].get("pattern") == "grasped" and ap is not None and ap.get("result") == "ok" and not ap.get("why") and (ap.get("gap") if ap.get("gap") is not None else 1) < 0.01
    return good, "servo corrections %s, first close %s, approach %s gap %s (model %s, visual %s)" % (servo.get("corrections"), stalls[0].get("pattern") if stalls else None, ap and ap.get("result"), ap and ap.get("gap"), ap and ap.get("gap_model"), ap and ap.get("gap_visual"))


def c_model(out, ev, st):
    stalls = [e for e in ev if e.get("ev") == "stall"]
    return bool(stalls) and stalls[0].get("pattern") != "grasped", "first close %s, result %s" % (stalls[0].get("pattern") if stalls else None, result(ev))


def c_contact(out, ev, st):
    i_ap = idx(ev, lambda e: e.get("ev") == "approach"); i_close = idx(ev, lambda e: e.get("ev") == "hand"); i_ret = idx(ev, lambda e: e.get("label") == "retreat-up")
    good = i_ap is not None and ev[i_ap].get("result") == "aborted" and (i_close is None or (i_ret is not None and i_ret < i_close))
    return good, "first approach %s (%s), no close before the retreat: %s" % (i_ap is not None and ev[i_ap].get("result"), i_ap is not None and ev[i_ap].get("why"), i_close is None or (i_ret is not None and i_ret < i_close))


def c_abort(out, ev, st):
    labels = [(i, e.get("ev"), e.get("label")) for i, e in enumerate(ev) if e.get("ev") in ("move", "home", "park")]
    i_up = next((i for i, k, l in labels if l == "retreat-up"), None); i_back = next((i for i, k, l in labels if l == "retreat-back"), None)
    i_home = next((i for i, k, l in labels if k in ("home", "park")), None); home = first(ev, "home")
    keep = {e["label"].split(" ")[0]: e["reach_x"] for e in ev if e.get("ev") == "keepout"}
    good = (result(ev) == "aborted" and None not in (i_up, i_back, i_home) and i_up < i_back < i_home and home is not None and home.get("how") == "the raise retraced"
            and keep.get("home", 9) <= keep.get("up", -9) + 0.01 and not st.get("disable_away"))
    return good, "retreat-up %s, retreat-back %s, home %s (%s), low reach home %s vs raise %s" % (i_up, i_back, i_home, home and home.get("how"), keep.get("home"), keep.get("up"))


def c_dry(out, ev, st):
    return result(ev) == "dry" and "arm streamer enabled" not in out and not st.get("targets") and not st.get("disables"), "result %s, targets %s, releases %s" % (result(ev), st.get("targets"), st.get("disables"))


def c_block(out, ev, st):
    return result(ev) == "blocked" and "Raising." not in out and not st.get("targets"), "result %s, targets %s" % (result(ev), st.get("targets"))


def c_air(out, ev, st):
    o = (first(ev, "result") or {}).get("air") or {}; sag = o.get("sag") or {}; moved = re.findall(r"air\d: moved ([0-9.\-]+)", out)
    good = result(ev) == "air" and 0 < sag.get("up", 0) <= 0.07 and 0 < sag.get("high", 0) <= 0.07 and (o.get("pre_err") or 1) < 0.006 and len(moved) == 5 and (o.get("slide_err") or 1) < 0.01
    return good, "sag up %s high %s, pre err %s, moved %s, slide-end err %s" % (sag.get("up"), sag.get("high"), o.get("pre_err"), moved, o.get("slide_err"))


def c_speed(out, ev, st):
    return st.get("targets", 0) > 300 and result(ev) is not None, "result %s, %s targets streamed" % (result(ev), st.get("targets"))


def stop_reach(st, i=0):
    s = (st.get("stops") or [{}])[i] if len(st.get("stops") or []) > i else {}
    return s, s.get("after_low_reach", 9), st.get("raise_low_reach", -9)


def c_raisefail(out, ev, st):
    s, after, rz = stop_reach(st); home = first(ev, "home")
    good = bool(s) and after <= rz + 0.01 and home is not None and home.get("how") == "the raise retraced" and not st.get("disable_away")
    return good, "stopped at %s; after it the hand below the table top + 3 cm reached x %s (the raise %s); home %s; releases away %s" % (s.get("palm"), after, rz, home and home.get("how"), st.get("disable_away"))


def c_descent(out, ev, st):
    s, after, rz = stop_reach(st)
    good = bool(s) and after <= rz + 0.01 and not st.get("disable_away") and st.get("end_home_dist", 9) < 0.03
    return good, "stopped at %s; after it x %s (the raise %s); ended %s from home; way out %s; releases away %s" % (s.get("palm"), after, rz, st.get("end_home_dist"), re.findall(r"way out: ([^;\n]*)", out), st.get("disable_away"))


def c_walk(out, ev, st):
    s, after, rz = stop_reach(st)
    good = bool(s) and s.get("out_y", 9) <= 0.01 and s.get("out_x", 9) <= 0.01 and s.get("up_z", 9) <= 0.01 and not st.get("disable_away")
    return good, "after the stop at %s the palm went out y %s x %s, up %s; releases away %s" % (s.get("palm"), s.get("out_y"), s.get("out_x"), s.get("up_z"), st.get("disable_away"))


def c_quit2(out, ev, st):
    s, after, rz = stop_reach(st, 1)
    good = bool(s) and s.get("after_targets", 9) <= 1 and not st.get("disable_away")
    return good, "second stop at %s, %s targets after it; releases away from home %s" % (s.get("palm"), s.get("after_targets"), st.get("disable_away"))


def c_table(out, ev, st):
    floor = TABLE_Z - 0.02 + HALF_H + MARGIN; low = st.get("min_cmd_z", 0) or 0
    good = low >= floor - 0.002 and st.get("push", 9) <= 0.03 and result(ev) != "success"
    return good, "lowest command z %.3f (floor %.3f), push into the table %.3f, %s contacts, result %s" % (low, floor, st.get("push", -1), st.get("table_contacts"), result(ev))


def c_fwd(err):
    def c(out, ev, st):
        stalls = [e for e in ev if e.get("ev") == "stall"]; servo = (first(ev, "result") or {}).get("servo") or {}
        m0 = next((e for e in ev if e.get("ev") == "measure" and e.get("label") == "servo0"), {}); e0 = (m0.get("err") or [None])[0]
        good = servo.get("corrections", 0) >= 1 and bool(stalls) and stalls[0].get("pattern") == "grasped"
        return good, "true forward error %.3f: servo0 e_d %s, corrections %s, first close %s, result %s" % (err, e0, servo.get("corrections"), stalls[0].get("pattern") if stalls else None, result(ev))
    return c


def c_nerr(out, ev, st):
    ap = first(ev, "approach"); i_close = idx(ev, lambda e: e.get("ev") == "hand"); i_ret = idx(ev, lambda e: e.get("label") == "retreat-up")
    good = ap is not None and ap.get("result") == "aborted" and (i_close is None or (i_ret is not None and i_ret < i_close))
    return good, "approach %s (%s), no close before the retreat %s" % (ap and ap.get("result"), ap and ap.get("why"), i_close is None or (i_ret is not None and i_ret < i_close))


def c_gemma(out, ev, st):
    r = result(ev) or ""
    return r.startswith("skill_failed") and "Gemma" in r and first(ev, "approach") is None, "result %s, approach %s" % (r[:70], first(ev, "approach"))


def c_noK(out, ev, st): return result(ev) == "no_K" and not st.get("targets"), "result %s, targets %s" % (result(ev), st.get("targets"))
def c_refused(res):
    def c(out, ev, st): return result(ev) == res and not st.get("targets"), "result %s, targets %s" % (result(ev), st.get("targets"))
    return c


def c_assist(out, ev, st):
    a = [e for e in ev if (e.get("label") or "").startswith("assist")]; locs = out.count("== LOCATE")
    return locs >= 2 and result(ev) in ("blocked", "no_can", "lost", "at_edge", "no_depth") and not a and "== RECOVER assist" not in out, "locates %d, result %s, assist moves %s" % (locs, result(ev), len(a))


AIR = ["--air", "--air-can", "0.38", "0.15", "--air-table", "0.075"]
STOP = "BRAIN_MOCK_STOP"
CASES = {   # name: (args, env, check, needs K)
    "servo": ([], HIDDEN, c_servo, True), "model": (["--model-grasp"], HIDDEN, c_model, False), "contact": ([], {"BRAIN_MOCK_CONTACT": "0.02"}, c_contact, True),
    "abort": ([], {"BRAIN_MOCK_ABORT_AT": "APPROACH"}, c_abort, True), "dry": (["--dry"], {}, c_dry, False),
    "block": (AIR, {"BRAIN_MOCK_SCENE": "none", "BRAIN_MOCK_OBSTACLE": "1"}, c_block, False), "air": (AIR, {"BRAIN_MOCK_SCENE": "none"}, c_air, False),
    "speed": (["--speed", "0.5"], HIDDEN, c_speed, True),
    "raisefail": ([], {STOP: "Raising.;fail;z>0.20"}, c_raisefail, True),
    "descent": (["--air", "--air-can", "0.35", "0.00", "--air-table", "0.075", "--speed", "0.5"], {"BRAIN_MOCK_SCENE": "none", STOP: "Home.;abort;z<0.20", "BRAIN_MOCK_KEYS": "h,y"}, c_descent, False),
    "walk": ([], {"BRAIN_MOCK_ABORT_AT": "APPROACH", STOP: "Order cancelled.;abort;x<0.32", "BRAIN_MOCK_KEYS": "h,y"}, c_walk, True),
    "quit2": ([], {STOP: "Lowering beside the can.;quit;30,Moving my arm back before I stop.;quit;30"}, c_quit2, True),
    "sigint2": ([], {STOP: "Lowering beside the can.;sigint;30,Moving my arm back before I stop.;sigint;30"}, c_quit2, True),
    "table": ([], dict(HIDDEN, BRAIN_MOCK_TABLE_BIAS="0.02"), c_table, True),
    "fwd39": ([], dict(NOERR, BRAIN_MOCK_ERR="0.135"), c_fwd(0.039), True), "fwd54": ([], dict(NOERR, BRAIN_MOCK_ERR="0.15"), c_fwd(0.054), True),
    "nerr": ([], dict(NOERR, BRAIN_MOCK_ERRY="0.02"), c_nerr, True), "gemma": ([], dict(HIDDEN, BRAIN_MOCK_GEMMA_OFF="0.15"), c_gemma, True),
    "noK": ([], HIDDEN, c_noK, False),
    "zero": (AIR, {"BRAIN_MOCK_SCENE": "none", "BRAIN_MOCK_DEPTH": "zero"}, c_refused("blocked"), False),
    "minrange": (AIR, {"BRAIN_MOCK_SCENE": "none", "BRAIN_MOCK_OBSTACLE": "1", "BRAIN_MOCK_MIN_RANGE": "0.28"}, c_refused("blocked"), False),
    "tape": (["--air", "--air-can", "0.38", "0.15", "--air-table", "0.105"], {"BRAIN_MOCK_SCENE": "none"}, c_refused("air_table_mismatch"), False),
    "tape8": (["--air", "--air-can", "0.38", "0.15", "--air-table", "-0.005"], {"BRAIN_MOCK_SCENE": "none"}, c_refused("air_table_mismatch"), False),   # the tape 8 cm LOW: the palm would go into the table
    "assist": ([], dict(HIDDEN, BRAIN_MOCK_HAND="miss,miss,miss,miss", BRAIN_MOCK_OBSTACLE="after:Missed."), c_assist, True),
}

if not TREE:
    run("compile", [PY, "-B", "-m", "py_compile", "brain.py", "geom.py", "gemma.py", "motion.py", "calib.py", "mock_robot.py", "preflight.py", "brainview.py", "replay_reach.py", "test_geom.py", "test_motion.py"])
    run("test_geom", [PY, "-B", "test_geom.py"])
    run("test_motion (blockers 1, 4)", [PY, "-B", "test_motion.py"])
    run("replay_reach", [PY, "-B", "replay_reach.py"])
    run("calib", [PY, "-B", "calib.py"])
    for name, extra, code in (("--speed 5 refused", ["--speed", "5"], 2), ("--speed 0 refused", ["--speed", "0"], 2), ("--expect-calib mismatch refused", ["--expect-calib", "0000000000000000", "--dry"], 1)):
        run(name, [PY, "-B", "brain.py", "--mock", "--mock-gemma", "--no-preflight", "--accept-calib"] + extra, expect=code, timeout=60)
else:
    shutil.copy(os.path.join(HERE, "mock_robot.py"), os.path.join(TREE, "mock_robot.py")); print("running on %s with this mock (flags it lacks dropped)" % TREE, flush=True)

# the mock kill test: no hidden error, the probe's `off` is K
t0 = time.time(); out, ev, st = finish(start("kill", ["--probe"], NOERR))
probe = (first(ev, "result") or {}).get("probe") or {}; K = probe.get("off")
report("kill test (K from the probe)", result(ev) == "probe" and K is not None and probe.get("n_blob", 0) > 300 and "AT THE" not in out, t0, "K %s, %s hand points" % (K, probe.get("n_blob")))
if K is None: print(out[-2500:]); print("CHECK: FAIL"); sys.exit(1)

todo = [(n, c) for n, c in CASES.items() if want is None or n in want]; jobs, done = [], []
while todo or jobs:
    while todo and len(jobs) < MAXJ:
        name, (args, env, check, needs_k) = todo.pop(0)
        jobs.append((name, args, check, start(name, args + (["--K"] + ["%.4f" % v for v in K] if needs_k else []), env)))
    for item in list(jobs):
        if item[3]["p"].poll() is not None: jobs.remove(item); done.append(item)
    time.sleep(0.2)
for name, args, check, job in sorted(done, key=lambda d: list(CASES).index(d[0])):
    out, ev, st = finish(job)
    good, detail = check(out, ev, st); jgood, jdetail = joint_step_ok(st, args)
    report(name, good and jgood, job["t0"], detail + ("" if not jdetail else "; " + jdetail))
    if not (good and jgood): print("   log: %s" % job["log"])

print("CHECK:", "PASS" if ok else "FAIL", "(logs in %s)" % TMP); sys.exit(0 if ok else 1)
