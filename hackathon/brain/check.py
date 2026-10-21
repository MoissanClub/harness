"""Desk gate (DEV_WORKFLOW S1, no robot, a few minutes): compile, the geometry and motion tests, the reach replay, calib freshness, the
CLI refusals, then mock runs (8 at a time). Every mock run that moves the arm also checks that no joint changed by more than
joint_step x speed in one streamed target, from the mock's `[mock] stats` line. The mock's scripted operator types BRAIN_MOCK_KEYS one
key each time the brain waits for y; with none left it types quit! (the owner's L2+B, then quit!).
The stop model under test (V2_REVIEW round 4): q, a and Ctrl-C freeze the arm at its next target in every state and it holds; the brain
says the way home and runs it only on y; the program ends only with the arm at home, where it is released; quit! exits holding and never
moves or releases; a refusal or a failure with the arm out holds the same way; the probe ends holding.
Order and air runs: servo (a hidden error the model misses: corrected, grasped), model (--model-grasp, no K: the first close is not a
grasp), contact (the hand meets the can 1 cm early: no close), abort ('a' at the approach, then y: up, back, the raise retraced), dry
(nothing enabled; the safety line prints the largest blind region), block (a box at chest height: the air test refuses), air (the sag
baselines, the corrected pre-grasp, five steps), speed (a whole order at --speed 0.5), raisefail (a g1-fetch failure at z 0.20 of the
raise, then y: the raise retraced), descent ('a' 7 cm down the air test's retraced descent, then y: retraced from there), walk ('a' at
the approach, 'a' again 3 targets into the way home: the new way home ends its retreat where the first one did), quit2 / sigint2 (q /
Ctrl-C while lowering and again on the way home: no target between a stop and the next y), table (the depth plane 15 mm low: the floor
on the tape, no contact), fwd39 / fwd54 (forward errors 3.9 / 5.4 cm: corrected, grasped), nerr (2 cm along the palm normal: no close), gemma
(Gemma's box 15 cm off: no approach), noK, zero, minrange, tape, tape8 (refused before any motion), assist (a box after the miss: the
retry's locate refuses), released (the probe from a pose a release left), nearhand / nearhand50 (a hand 10 cm from the chest inside the
D435i's minimum range, --dry: refused at the default --blind-max 0.08; with --blind-max 0.5 it passes and the value is logged),
secondq (two q at once while lowering: one hold, nothing before y), wayfail (a failure on the confirmed way home: holds again, nothing
before the next y), killtable (the kill probe at the purple can's slot, --floor-margin 0.02, tape and plane both 15 mm low, the hand 2 cm
low: the final line stops at the target where the hand falls 6 mm behind, push under 8 mm), planetape (the tape 3 cm below the plane in a probe: no motion), servoblock (--probe-servo --pre-offset 0.025 at the slot
with K from a margin-0.02 probe there: each correction only after its y, the residual under 1 cm, no table contact), servoobst (a box
in the zone's right half after the probe's result: the re-check before the servo nudge holds), armhand (a hand 10 cm from the chest after "Raising.": the blind
rule with the arm out refuses before high), armclear (the same minimum range, no hand: the raised arm's own silhouette does not refuse),
camfail (the head camera fails after "Reaching.": holds), reach (air (0.35, 0.00): under the table top the commanded 12.5 cm hand
stays 2 cm behind the edge), lateobst / lateobst2 (a box after "Reaching." / "Approaching.": holds, no lowering / no step), gemmanone (no
Gemma box: no approach), nograsp, air2, air3, airfloor (the plan's air commands at half speed; airfloor with --air-margin 0 and
--floor-margin 0.02), air140.
The dry raise line against the moving run (round 4 item 1): dryprobe vs the kill test at --fingertip 0.125, dryair125 vs air and
dryair140 vs air140: the "dry raise from home" line must equal the moving run's up-low and up keep-out lines within 5 mm.
The key table (round 4 item 2), one row per key and state the plan reaches: raise + q / a / Ctrl-C / quit! / y / Enter / p, the
lowering + a, the pre-grasp pause + q, held + q / quit! / Enter, the way home + Ctrl-C, the air slide + q, the normal retreat + a,
idle + q, idle + p, y and Enter, a failure then y / quit!, the servo's y wait + q, LOOK + q. For every stop key at most one target streams before the next y; every run ends at
home and released there, except quit!, which exits holding with nothing released.
Run: ~/miniforge3/envs/brain/bin/python -B check.py [--cases a,b,..]   (exit 1 on any failure)
CHECK_TREE=/path/to/other/hackathon/brain runs the mock cases on that brain version with THIS mock (copied in), dropping the flags it
lacks, and its own kill tests for K: how each round's gate cases were shown to fail on the previous commit."""
import glob, json, os, re, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); PY = sys.executable; ok = True; TMP = tempfile.mkdtemp(prefix="brain-check-")
TREE = os.environ.get("CHECK_TREE"); RUN_DIR = TREE or HERE; MAXJ = int(os.environ.get("CHECK_JOBS", "8"))
MOCK = {"BRAIN_MOCK_SCENE": "mid", "BRAIN_MOCK_ORDERS": "silver", "BRAIN_MOCK_SLEEP": "0.05"}
BASE = [PY, "-B", "brain.py", "--mock", "--mock-gemma", "--no-preflight", "--orders", "1", "--pause", "0.3", "--release-after", "4", "--accept-calib", "--table-edge", "0.34",
        "--fingertip", "0.125", "--table-z", "0.075"]                  # the keep-out and the floor model the mock's 12.5 cm hand; the taped table in every mode
NEW_FLAGS = {"--table-edge": 1, "--expect-calib": 1, "--model-grasp": 0, "--pre-offset": 1, "--pre-stop": 1, "--wait-reminder": 1,            # not in c39a468
             "--fingertip": 1, "--palm-half-height": 1, "--floor-margin": 1, "--air-margin": 1, "--no-grasp": 0, "--blind-max": 1, "--table-z": 1}   # not in 8e226e9
TABLE_Z, HALF_H, MARGIN, JOINT_STEP = 0.075, 0.045, 0.005, 0.02
TIMEOUT = int(os.environ.get("CHECK_TIMEOUT", "600"))             # seconds per mock run; a run still going is killed and fails
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
    old = open(os.path.join(TREE, "brain.py")).read()
    out, i = [], 0
    while i < len(args):
        if args[i] in NEW_FLAGS and '"%s"' % args[i] not in old: i += 1 + NEW_FLAGS[args[i]]; continue
        out.append(args[i]); i += 1
    return out


def start(case, args, env):
    runs = os.path.join(TMP, case); log = open(os.path.join(TMP, case + ".log"), "w")
    full = dict(os.environ); full.update(MOCK); full.update(env)
    p = subprocess.Popen(args_for_tree(BASE + args + ["--runs", runs]), cwd=RUN_DIR, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=full)
    return {"case": case, "p": p, "runs": runs, "log": os.path.join(TMP, case + ".log"), "t0": time.time()}


def finish(job, timeout=0.1):
    try: job["p"].wait(timeout=max(timeout, TIMEOUT - (time.time() - job["t0"])))
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


STOPKEYS = ("q", "a", "ctrl-c", "quit!")


def key_gaps(st):
    """For each stop key the operator typed (the mock's key log): the targets streamed from it to the next y, or to the end."""
    ks = st.get("keys") or []; out = []
    for i, (k, t) in enumerate(ks):
        if k in STOPKEYS: out.append((k, next((t2 for k2, t2 in ks[i + 1:] if k2 == "y"), st.get("targets", 0)) - t))
    return out


def still_until_y(st):
    """Nothing moves between a stop (a key, or an injected g1-fetch failure) and the operator's next y."""
    fails = [r.get("moved_before_y", 9) for r in st.get("stops") or [] if r.get("kind") == "fail"]
    return all(g <= 1 for _, g in key_gaps(st)) and all(m <= 1 for m in fails), "targets from each stop to the next y %s, after failures %s" % (key_gaps(st), fails)


def c_home_at_end(out, ev, st):
    """The arm ends at home and is released only there."""
    return st.get("end_home_dist", 9) < 0.03 and not st.get("disable_away") and "exiting WITHOUT moving" not in out


def ends(st, out): return "ended %s from home, releases %s (away %s)%s" % (st.get("end_home_dist"), st.get("disables"), st.get("disable_away"), ", EXITED HOLDING" if "exiting WITHOUT moving" in out else "")


def c_abort(out, ev, st):
    labels = [(i, e.get("ev"), e.get("label")) for i, e in enumerate(ev) if e.get("ev") in ("move", "home", "park")]
    i_up = next((i for i, k, l in labels if l == "retreat-up"), None); i_back = next((i for i, k, l in labels if l == "retreat-back"), None)
    i_home = next((i for i, k, l in labels if k in ("home", "park")), None); home = first(ev, "home")
    keep = {e["label"].split(" ")[0]: e["reach_x"] for e in ev if e.get("ev") == "keepout"}; still, sd = still_until_y(st)
    i_y, i_mv = out.find("[y] running the way home"), out.find("SAY: Up and back.")
    y_first = i_y != -1 and (i_mv == -1 or i_y < i_mv)                     # the retreat waits for y (13bff01 retreated by itself)
    good = (result(ev) == "stopped" and None not in (i_up, i_back, i_home) and i_up < i_back < i_home and home is not None and home.get("how") == "the raise retraced"
            and keep.get("home", 9) <= keep.get("up", -9) + 0.01 and still and y_first and c_home_at_end(out, ev, st))
    return good, "result %s; the retreat after y %s; retreat-up %s, retreat-back %s, home %s (%s), low reach home %s vs raise %s; %s; %s" % (
        result(ev), y_first, i_up, i_back, i_home, home and home.get("how"), keep.get("home"), keep.get("up"), sd, ends(st, out))


def c_dry(out, ev, st):
    return (result(ev) == "dry" and "arm streamer enabled" not in out and not st.get("targets") and not st.get("disables") and "largest blind region" in out,
            "result %s, targets %s, releases %s, blind region printed %s" % (result(ev), st.get("targets"), st.get("disables"), "largest blind region" in out))


def c_block(out, ev, st):
    return result(ev) == "blocked" and "Raising." not in out and not st.get("targets"), "result %s, targets %s" % (result(ev), st.get("targets"))


def c_air(out, ev, st):
    o = (first(ev, "result") or {}).get("air") or {}; sag = o.get("sag") or {}; moved = re.findall(r"air\d: moved ([0-9.\-]+)", out)
    good = result(ev) == "air" and 0 < sag.get("up", 0) <= 0.07 and 0 < sag.get("high", 0) <= 0.07 and (o.get("pre_err") or 1) < 0.006 and len(moved) == 5 and (o.get("slide_err") or 1) < 0.01 and c_home_at_end(out, ev, st)
    return good, "sag up %s high %s, pre err %s, moved %s, slide-end err %s; %s" % (sag.get("up"), sag.get("high"), o.get("pre_err"), moved, o.get("slide_err"), ends(st, out))


def c_speed(out, ev, st):
    return st.get("targets", 0) > 300 and result(ev) is not None, "result %s, %s targets streamed" % (result(ev), st.get("targets"))


def stop_reach(st, i=0):
    s = (st.get("stops") or [{}])[i] if len(st.get("stops") or []) > i else {}
    return s, s.get("after_low_reach", 9), st.get("raise_low_reach", -9)


def c_raisefail(out, ev, st):
    s, after, rz = stop_reach(st); home = first(ev, "home"); still, sd = still_until_y(st)
    good = bool(s) and after <= rz + 0.01 and home is not None and home.get("how") == "the raise retraced" and still and c_home_at_end(out, ev, st)
    return good, "stopped at %s; after it the hand below the table top + 3 cm reached x %s (the raise %s); home %s; %s; %s" % (s.get("palm"), after, rz, home and home.get("how"), sd, ends(st, out))


def c_descent(out, ev, st):
    s, after, rz = stop_reach(st); still, sd = still_until_y(st)
    good = bool(s) and after <= rz + 0.01 and still and c_home_at_end(out, ev, st)
    return good, "stopped at %s; after it x %s (the raise %s); %s; %s" % (s.get("palm"), after, rz, sd, ends(st, out))


def c_walk(out, ev, st):
    s, after, rz = stop_reach(st); still, sd = still_until_y(st)
    ways = [e.get("ends") for e in ev if e.get("ev") == "way_home" and e.get("ok") and e.get("ends")]
    d = None if len(ways) < 2 else max(abs(a - b) for a, b in zip(ways[0][0], ways[1][0]))
    good = bool(s) and d is not None and d <= 0.01 and s.get("out_x", 9) <= 0.01 and after <= rz + 0.01 and still and c_home_at_end(out, ev, st)
    return good, "after the second stop at %s: the new way home's retreat ends %s from the first's (%d way-home plans), out x %s, low reach %s (raise %s); %s; %s" % (
        s.get("palm"), d, len(ways), s.get("out_x"), after, rz, sd, ends(st, out))


def c_quit2(out, ev, st):
    still, sd = still_until_y(st); n = len(st.get("stops") or [])
    good = n == 2 and all(r.get("moved_before_y", 9) <= 1 for r in st["stops"]) and still and c_home_at_end(out, ev, st)
    return good, "%d stops, targets before the next y %s; %s; %s" % (n, [r.get("moved_before_y") for r in st.get("stops") or []], sd, ends(st, out))


def c_table(out, ev, st):
    floor = re.findall(r"table floor: the open hand's lowest point stays above z ([0-9.\-]+)", out)
    good = not st.get("table_contacts") and st.get("push", 9) <= 0.005 and bool(floor) and abs(float(floor[0]) - (TABLE_Z + MARGIN)) < 0.001
    return good, "push into the table %.3f, %s contacts, table floor %s (the tape 0.075 + 0.005; the plane 0.060), result %s" % (st.get("push", -1), st.get("table_contacts"), floor[:1], (result(ev) or "")[:40])


def c_released(out, ev, st):
    return result(ev) == "probe" and "park refused" not in out and c_home_at_end(out, ev, st), "result %s; %s; %s" % (result(ev), (re.findall(r"start pose: [^\n]*", out) or ["no start pose line"])[0][:150], ends(st, out))


def c_nearhand(out, ev, st):
    return result(ev) == "blocked" and not st.get("targets"), "result %s; %s" % (result(ev), (re.findall(r"safety \(locate\): [^\n]*", out) or [""])[0][:120])


def c_nearhand50(out, ev, st):
    dev = [e for e in ev if e.get("ev") == "deviation" and e.get("key") == "blind_max"]
    return result(ev) == "dry" and bool(dev) and not st.get("targets"), "result %s, blind_max deviation logged %s; %s" % (result(ev), bool(dev), (re.findall(r"safety \(locate\): [^\n]*", out) or [""])[0][:120])


def c_secondq(out, ev, st):
    s = (st.get("stops") or [{}])[0]; still, sd = still_until_y(st)
    good = bool(s) and s.get("moved_before_y", 9) <= 1 and still and c_home_at_end(out, ev, st)
    return good, "after the two q: %s targets before y; %s; %s" % (s.get("moved_before_y"), sd, ends(st, out))


def c_wayfail(out, ev, st):
    s = next((r for r in st.get("stops") or [] if r.get("kind") == "fail"), {}); still, sd = still_until_y(st)
    good = bool(s) and s.get("way_out_said") and s.get("moved_before_y", 9) <= 1 and still and c_home_at_end(out, ev, st)
    return good, "after the failure on the way home: %s targets before the next y, the way home said again %s; %s" % (s.get("moved_before_y"), s.get("way_out_said"), ends(st, out))


def c_killtable(out, ev, st):
    good = st.get("push", 9) <= 0.008 and "the hand stopped following" in out and c_home_at_end(out, ev, st)
    return good, "push into the table %.4f, %s contacts, %s; result %s; %s" % (st.get("push", -1), st.get("table_contacts"), (re.findall(r"final line near the table floor: [^\n]*", out) or ["no final-line watch"])[0][:80], (result(ev) or "")[:40], ends(st, out))


def c_servoblock(out, ev, st):
    sv = (first(ev, "result") or {}).get("servo") or {}; err = sv.get("err") or [9, 9, 9]; gated, last, n = True, "", 0
    for line in out.splitlines():
        if line.startswith("[y] running the correction"): last = "y"
        elif line.startswith("SAY: Correcting."): gated, last, n = gated and last == "y", "", n + 1
    good = not st.get("table_contacts") and n >= 1 and gated and sv.get("converged") and abs(err[0]) < 0.01 and abs(err[2]) < 0.01 and c_home_at_end(out, ev, st)
    return good, "%s table contacts, push %.4f, %d corrections each after its y %s, residual %s (converged %s); %s" % (st.get("table_contacts"), st.get("push", -1), n, gated, err, sv.get("converged"), ends(st, out))


def c_servoobst(out, ev, st):
    good = "SAY: Correcting." not in out and "HOLD: the 0.30 m rule before servo 0" in out and c_home_at_end(out, ev, st)
    return good, "nudged %s, held before the nudge %s; %s" % ("SAY: Correcting." in out, "HOLD: the 0.30 m rule before servo 0" in out, ends(st, out))


def c_armhand(out, ev, st):
    good = "HOLD: the 0.30 m rule before high" in out and "SAY: Reaching." not in out and c_home_at_end(out, ev, st)
    return good, "held before high %s, reached %s; %s; %s" % ("HOLD: the 0.30 m rule before high" in out, "SAY: Reaching." in out, (re.findall(r"safety \(high\): [^\n]*", out) or [""])[0][:110], ends(st, out))


def c_armclear(out, ev, st):
    good = result(ev) == "probe" and "HOLD: the 0.30 m rule" not in out and c_home_at_end(out, ev, st)
    return good, "result %s, refused %s; %s; %s" % (result(ev), "HOLD: the 0.30 m rule" in out, (re.findall(r"safety \(pre\): [^\n]*", out) or [""])[0][:110], ends(st, out))


def c_camfail(out, ev, st):
    good = "the head camera failed" in out and "SAY: Lowering beside the can." not in out and c_home_at_end(out, ev, st)
    return good, "camera failure seen %s, lowered %s; %s" % ("the head camera failed" in out, "SAY: Lowering beside the can." in out, ends(st, out))


def c_reach(out, ev, st):
    cmd, true = st.get("raise_cmd_hand_under_table_x", 9), st.get("raise_tip_under_table_x", 9)
    return result(ev) == "air" and cmd <= 0.34 - 0.02, "under the table top the commanded 12.5 cm hand reached x %s during the raise (the sagged mock hand %s; edge 0.34); result %s" % (cmd, true, result(ev))


def c_lateobst(out, ev, st):
    good = "Lowering beside the can." not in out and "Sliding." not in out and c_home_at_end(out, ev, st)
    return good, "lowered %s, slid %s, result %s; %s" % ("Lowering beside the can." in out, "Sliding." in out, result(ev), ends(st, out))


def c_lateobst2(out, ev, st):
    steps = [e for e in ev if e.get("ev") == "ap_step"]
    return not steps and c_home_at_end(out, ev, st), "approach steps %d, result %s; %s" % (len(steps), (result(ev) or "")[:60], ends(st, out))


def c_gemmanone(out, ev, st):
    r = result(ev) or ""
    return r.startswith("skill_failed") and "Gemma" in r and first(ev, "approach") is None and c_home_at_end(out, ev, st), "result %s, approach %s; %s" % (r[:70], first(ev, "approach") is not None, ends(st, out))


def c_nograsp(out, ev, st): return result(ev) == "no_grasp" and not st.get("targets"), "result %s, targets %s" % (result(ev), st.get("targets"))
def c_airplan(out, ev, st):
    o = (first(ev, "result") or {}).get("air") or {}
    return result(ev) == "air" and c_home_at_end(out, ev, st), "result %s, pre err %s, slide err %s; %s" % (result(ev), o.get("pre_err"), o.get("slide_err"), ends(st, out))


def c_dryline(out, ev, st):
    return result(ev) == "dry" and not st.get("targets") and raise_line(out) is not None, "result %s, targets %s, dry raise line %s" % (result(ev), st.get("targets"), raise_line(out))


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
    return r.startswith("skill_failed") and "Gemma" in r and first(ev, "approach") is None and c_home_at_end(out, ev, st), "result %s, approach %s; %s" % (r[:70], first(ev, "approach"), ends(st, out))


def c_noK(out, ev, st): return result(ev) == "no_K" and not st.get("targets"), "result %s, targets %s" % (result(ev), st.get("targets"))
def c_refused(res):
    def c(out, ev, st): return result(ev) == res and not st.get("targets"), "result %s, targets %s" % (result(ev), st.get("targets"))
    return c


def c_assist(out, ev, st):
    a = [e for e in ev if (e.get("label") or "").startswith("assist")]; locs = out.count("== LOCATE")
    return locs >= 2 and result(ev) in ("blocked", "no_can", "lost", "at_edge", "no_depth") and not a and "== RECOVER assist" not in out, "locates %d, result %s, assist moves %s" % (locs, result(ev), len(a))


def c_key(expect, said=None, res=None):
    """The key table's check: every stop key stops the arm within one target and nothing moves before the next y; the run ends at home
    and is released there ("home"), or exits holding with nothing released after quit! ("holding")."""
    def c(out, ev, st):
        still, sd = still_until_y(st); r = result(ev) or ""
        if expect == "holding": end = "exiting WITHOUT moving or releasing" in out and not st.get("disables") and not st.get("disable_away")
        else: end = c_home_at_end(out, ev, st) and st.get("disables", 0) >= 1
        good = still and end and (said is None or said in out) and (res is None or r.startswith(res))
        return good, "%s; %s; result %s%s" % (sd, ends(st, out), r[:40], "" if said is None else "; %r printed %s" % (said, said in out))
    return c


def raise_line(out):
    """The raise as planned: (z, up-low reach, up reach) from the dry line, or (13bff01) its single straight-raise reach twice."""
    m = re.search(r"dry raise from home \(candidate y [0-9.\-]+\): up-low below z ([0-9.\-]+) stays behind x ([0-9.\-]+), up behind x ([0-9.\-]+)", out)
    if m: return tuple(float(v) for v in m.groups())
    m = re.search(r"dry raise from home: below z ([0-9.\-]+) the hand stays behind x ([0-9.\-]+)", out)
    return (float(m.group(1)), float(m.group(2)), float(m.group(2))) if m else None


def moving_raise(out):
    """The moving run's raise: the up-low and up keep-out lines of the candidate it ran (the last before its `raise:` line), or, in
    13bff01's log, the first two (planned as it moved)."""
    lines = re.findall(r"^  (up-low|up) path: below z ([0-9.\-]+) the hand stays behind x ([0-9.\-]+)", out.split("  raise: up-low")[0], re.M)
    if "  raise: up-low" not in out: lines = lines[:2]
    d = {}
    for label, z, x in lines: d[label] = (float(z), float(x))
    return (d["up-low"][0], d["up-low"][1], d["up"][1]) if "up-low" in d and "up" in d else None


AIR = ["--air", "--air-can", "0.38", "0.15", "--air-table", "0.075"]
AIR35 = ["--air", "--air-can", "0.35", "0.00", "--air-table", "0.075", "--speed", "0.5"]
STOP, KEYS, SAYKEYS, TIMEKEYS = "BRAIN_MOCK_STOP", "BRAIN_MOCK_KEYS", "BRAIN_MOCK_SAYKEYS", "BRAIN_MOCK_TIMEKEYS"
SLOT09, SLOT12 = dict(NOERR, BRAIN_MOCK_SCENE="slot09", BRAIN_MOCK_ORDERS="purple"), dict(NOERR, BRAIN_MOCK_SCENE="slot12", BRAIN_MOCK_ORDERS="purple")
PROBE, SERVO = ["--probe"], ["--probe", "--probe-servo", "--pre-offset", "0.025"]
CASES = {   # name: (args, env, check, K: False / True = the kill test's / "slot" = the margin-0.02 probe at slot09)
    "servo": ([], HIDDEN, c_servo, True), "model": (["--model-grasp"], HIDDEN, c_model, False), "contact": ([], {"BRAIN_MOCK_CONTACT": "0.02"}, c_contact, True),
    "abort": ([], {"BRAIN_MOCK_ABORT_AT": "APPROACH", KEYS: "y"}, c_abort, True), "dry": (["--dry"], {}, c_dry, False),
    "block": (AIR, {"BRAIN_MOCK_SCENE": "none", "BRAIN_MOCK_OBSTACLE": "1"}, c_block, False), "air": (AIR, {"BRAIN_MOCK_SCENE": "none"}, c_air, False),
    "speed": (["--speed", "0.5"], HIDDEN, c_speed, True),
    "raisefail": ([], {STOP: "Raising.;fail;z>0.20", KEYS: "y"}, c_raisefail, True),
    "descent": (AIR35, {"BRAIN_MOCK_SCENE": "none", STOP: "Home.;abort;z<0.20", KEYS: "y"}, c_descent, False),
    "walk": ([], {"BRAIN_MOCK_ABORT_AT": "APPROACH", STOP: "Up and back.;abort;3", KEYS: "y,y"}, c_walk, True),
    "quit2": ([], {STOP: "Lowering beside the can.;quit;30,Up and back.;quit;5", KEYS: "y,y"}, c_quit2, True),
    "sigint2": ([], {STOP: "Lowering beside the can.;sigint;30,Up and back.;sigint;5", KEYS: "y,y"}, c_quit2, True),
    "table": ([], dict(HIDDEN, BRAIN_MOCK_TABLE_BIAS="0.015", BRAIN_MOCK_KEYS="y"), c_table, True),
    "fwd39": ([], dict(NOERR, BRAIN_MOCK_ERR="0.135"), c_fwd(0.039), True), "fwd54": ([], dict(NOERR, BRAIN_MOCK_ERR="0.15"), c_fwd(0.054), True),
    "nerr": ([], dict(NOERR, BRAIN_MOCK_ERRY="0.02"), c_nerr, True), "gemma": ([], dict(HIDDEN, BRAIN_MOCK_GEMMA_OFF="0.15", BRAIN_MOCK_KEYS="y"), c_gemma, True),
    "noK": ([], HIDDEN, c_noK, False),
    "zero": (AIR, {"BRAIN_MOCK_SCENE": "none", "BRAIN_MOCK_DEPTH": "zero"}, c_refused("blocked"), False),
    "minrange": (AIR, {"BRAIN_MOCK_SCENE": "none", "BRAIN_MOCK_OBSTACLE": "1", "BRAIN_MOCK_MIN_RANGE": "0.28"}, c_refused("blocked"), False),
    "tape": (["--air", "--air-can", "0.38", "0.15", "--air-table", "0.105"], {"BRAIN_MOCK_SCENE": "none"}, c_refused("air_table_mismatch"), False),
    "tape8": (["--air", "--air-can", "0.38", "0.15", "--air-table", "-0.005"], {"BRAIN_MOCK_SCENE": "none"}, c_refused("air_table_mismatch"), False),   # the tape 8 cm LOW: the palm would go into the table
    "assist": ([], dict(HIDDEN, BRAIN_MOCK_HAND="miss,miss,miss,miss", BRAIN_MOCK_OBSTACLE="after:Missed."), c_assist, True),
    "released": (PROBE, dict(SLOT09, BRAIN_MOCK_START_Q="0.06,0.18,0.06,1.12,0.10", BRAIN_MOCK_KEYS="y"), c_released, False),
    "nearhand": (["--dry"], {"BRAIN_MOCK_NEAR_HAND": "1", "BRAIN_MOCK_MIN_RANGE": "0.28"}, c_nearhand, False),
    "nearhand50": (["--dry", "--blind-max", "0.5"], {"BRAIN_MOCK_NEAR_HAND": "1", "BRAIN_MOCK_MIN_RANGE": "0.28"}, c_nearhand50, False),
    "secondq": ([], {STOP: "Lowering beside the can.;keys:q+q;20", KEYS: "y"}, c_secondq, True),
    "wayfail": ([], {"BRAIN_MOCK_ABORT_AT": "APPROACH", STOP: "Up and back.;fail;5", KEYS: "y,y"}, c_wayfail, True),
    "killtable": (PROBE + ["--floor-margin", "0.02", "--table-z", "0.06"], dict(SLOT12, BRAIN_MOCK_TABLE_BIAS="0.015", BRAIN_MOCK_ERRZ="-0.02", BRAIN_MOCK_KEYS="y"), c_killtable, False),
    "planetape": (PROBE + ["--table-z", "0.045"], NOERR, c_refused("table_mismatch"), False),
    "servoblock": (SERVO + ["--floor-margin", "0.02"], dict(SLOT09, BRAIN_MOCK_KEYS="y,y,y,y,y"), c_servoblock, "slot"),
    "servoobst": (SERVO, dict(NOERR, BRAIN_MOCK_OBSTACLE="after:Measured.", BRAIN_MOCK_OBSBOX="0.15,0.25,-0.11,-0.05,0.25,0.45", BRAIN_MOCK_KEYS="y,y"), c_servoobst, True),
    "armhand": (PROBE, dict(NOERR, BRAIN_MOCK_NEAR_HAND="after:Raising.", BRAIN_MOCK_MIN_RANGE="0.28", BRAIN_MOCK_KEYS="y"), c_armhand, False),
    "armclear": (PROBE, dict(NOERR, BRAIN_MOCK_MIN_RANGE="0.28", BRAIN_MOCK_KEYS="y"), c_armclear, False),
    "camfail": (PROBE, dict(NOERR, BRAIN_MOCK_CAMFAIL="after:Reaching.", BRAIN_MOCK_KEYS="y"), c_camfail, False),
    "reach": (AIR35, {"BRAIN_MOCK_SCENE": "none"}, c_reach, False),
    "lateobst": (AIR, {"BRAIN_MOCK_SCENE": "none", "BRAIN_MOCK_OBSTACLE": "after:Reaching.", KEYS: "y"}, c_lateobst, False),
    "lateobst2": ([], dict(HIDDEN, BRAIN_MOCK_OBSTACLE="after:Approaching.", BRAIN_MOCK_KEYS="y"), c_lateobst2, True),
    "gemmanone": ([], dict(HIDDEN, BRAIN_MOCK_GEMMA_BOX="none", BRAIN_MOCK_KEYS="y"), c_gemmanone, True),
    "nograsp": (["--no-grasp"], HIDDEN, c_nograsp, True),
    "air2": (AIR35, {"BRAIN_MOCK_SCENE": "none"}, c_airplan, False),
    "air3": (["--air", "--air-can", "0.40", "-0.08", "--air-table", "0.075", "--speed", "0.5"], {"BRAIN_MOCK_SCENE": "none"}, c_airplan, False),
    "airfloor": (AIR + ["--speed", "0.5", "--air-margin", "0", "--floor-margin", "0.02"], {"BRAIN_MOCK_SCENE": "none"}, c_airplan, False),
    "air140": (AIR + ["--fingertip", "0.14"], {"BRAIN_MOCK_SCENE": "none"}, c_airplan, False),
    "dryprobe": (PROBE + ["--dry"], NOERR, c_dryline, False),
    "dryair125": (AIR + ["--dry"], {"BRAIN_MOCK_SCENE": "none"}, c_dryline, False),
    "dryair140": (AIR + ["--dry", "--fingertip", "0.14"], {"BRAIN_MOCK_SCENE": "none"}, c_dryline, False),
}
PAIRS = [("dryprobe", "kill"), ("dryair125", "air"), ("dryair140", "air140")]     # (the dry line, the moving run it must match)
KEYTABLE = [   # (state + key, args, env, expect, printed, result): one row per key and state the plan reaches
    ("raise+q", PROBE, {STOP: "Raising.;keys:q;10", KEYS: "y"}, "home", None, "stopped"),
    ("raise+a", PROBE, {STOP: "Raising.;keys:a;10", KEYS: "y"}, "home", None, "stopped"),
    ("raise+ctrl-c", PROBE, {STOP: "Raising.;sigint;10", KEYS: "y"}, "home", None, "stopped"),
    ("raise+quit!", PROBE, {STOP: "Raising.;keys:quit!;10"}, "holding", None, "stopped"),
    ("raise+y", PROBE, {STOP: "Raising.;keys:y;10", KEYS: "y"}, "home", "[y] ignored", "probe"),
    ("raise+enter", PROBE, {STOP: "Raising.;keys:enter;10", KEYS: "y"}, "home", "[enter] ignored", "probe"),
    ("raise+p", PROBE, {STOP: "Raising.;keys:p;10", KEYS: "y"}, "home", "[p] not a key", "probe"),
    ("lower+a", PROBE, {STOP: "Lowering beside the can.;keys:a;10", KEYS: "y"}, "home", None, "stopped"),
    ("pause+q", PROBE, {SAYKEYS: "Measuring.:q", KEYS: "y"}, "home", None, "stopped"),
    ("held+q", PROBE, {KEYS: "q,y"}, "home", "stop typed while waiting", "probe"),
    ("held+quit!", PROBE, {KEYS: "quit!"}, "holding", None, "probe"),
    ("held+enter", PROBE, {KEYS: "enter,p,y"}, "home", "[enter] ignored", "probe"),
    ("wayhome+ctrl-c", PROBE, {STOP: "Up and back.;sigint;3", KEYS: "y,y"}, "home", None, "probe"),
    ("slide+q", AIR, {"BRAIN_MOCK_SCENE": "none", STOP: "Sliding.;keys:q;2", KEYS: "y"}, "home", None, "stopped"),
    ("retreat+a", AIR, {"BRAIN_MOCK_SCENE": "none", STOP: "Up and back.;keys:a;3", KEYS: "y"}, "home", None, "held"),
    ("idle+q", PROBE, {"BRAIN_MOCK_ENTER": "1", TIMEKEYS: "8:q"}, "home", None, None),
    ("idle+p,y,enter", PROBE, {"BRAIN_MOCK_ENTER": "1", TIMEKEYS: "8:p+y+enter,25:enter", KEYS: "y"}, "home", "[p] not a key", "probe"),
    ("fail+y", PROBE, {STOP: "Raising.;fail;10", KEYS: "y"}, "home", None, "skill_failed"),
    ("fail+quit!", PROBE, {STOP: "Raising.;fail;10", KEYS: "quit!"}, "holding", None, "skill_failed"),
    ("servo-wait+q", SERVO, {KEYS: "q,y"}, "home", "is not run", "stopped"),
    ("look+q", ["--no-grasp"], {SAYKEYS: "Tell me which one you'd like.:q"}, "home", None, "stopped"),
]
for _name, _args, _env, _expect, _said, _res in KEYTABLE:
    CASES["key " + _name] = (_args, dict(NOERR, **_env), c_key(_expect, _said, _res), _name.startswith("servo"))

if not TREE:
    run("compile", [PY, "-B", "-m", "py_compile", "brain.py", "geom.py", "gemma.py", "motion.py", "calib.py", "mock_robot.py", "preflight.py", "brainview.py", "replay_reach.py", "test_geom.py", "test_motion.py"])
    run("test_geom", [PY, "-B", "test_geom.py"])
    run("test_motion (blockers 1, 4)", [PY, "-B", "test_motion.py"])
    run("replay_reach", [PY, "-B", "replay_reach.py"])
    run("calib", [PY, "-B", "calib.py"])
    for name, extra, code in (("--speed 5 refused", ["--speed", "5"], 2), ("--speed 0 refused", ["--speed", "0"], 2), ("--fingertip 1.25 refused", ["--fingertip", "1.25"], 2),
                              ("--table-z 7.5 refused", ["--table-z", "7.5"], 2), ("--expect-calib mismatch refused", ["--expect-calib", "0000000000000000", "--dry"], 1)):
        run(name, [PY, "-B", "brain.py", "--mock", "--mock-gemma", "--no-preflight", "--accept-calib"] + extra, expect=code, timeout=60)
else:
    shutil.copy(os.path.join(HERE, "mock_robot.py"), os.path.join(TREE, "mock_robot.py")); print("running on %s with this mock (flags it lacks dropped)" % TREE, flush=True)

# the mock kill tests: no hidden error, the probe's `off` is K (the order cases: the mid scene; the servo block: slot09 at --floor-margin 0.02)
t0 = time.time(); kills = {"kill": start("kill", PROBE, dict(NOERR, BRAIN_MOCK_KEYS="y")), "killslot": start("killslot", PROBE + ["--floor-margin", "0.02"], dict(SLOT09, BRAIN_MOCK_KEYS="y"))}
Ks, outs = {}, {}
for name, job in kills.items():
    out, ev, st = finish(job); probe = (first(ev, "result") or {}).get("probe") or {}; Ks[name] = probe.get("off"); outs[name] = out
    report("%s test (K from the probe)" % name, result(ev) == "probe" and Ks[name] is not None and probe.get("n_blob", 0) > 300 and "AT THE" not in out and c_home_at_end(out, ev, st), t0,
           "K %s, %s hand points; %s" % (Ks[name], probe.get("n_blob"), ends(st, out)))
K = Ks["kill"]
if K is None: print(outs["kill"][-2500:]); print("CHECK: FAIL"); sys.exit(1)

def k_args(needs): return ["--K"] + ["%.4f" % v for v in {True: K, "slot": Ks["killslot"]}[needs]] if needs else []


todo = [(n, c) for n, c in CASES.items() if (want is None or n in want or n.split(" ")[0] in want) and not (c[3] == "slot" and Ks["killslot"] is None)]; jobs, done = [], []
if Ks["killslot"] is None: report("servoblock", False, time.time(), "no K from the slot09 probe")
while todo or jobs:
    while todo and len(jobs) < MAXJ:
        name, (args, env, check, needs_k) = todo.pop(0)
        jobs.append((name, args, check, start(re.sub(r"[^A-Za-z0-9-]", "_", name), args + k_args(needs_k), env)))
    for item in list(jobs):
        if item[3]["p"].poll() is not None or time.time() - item[3]["t0"] > TIMEOUT: jobs.remove(item); done.append(item)   # finish() kills one past TIMEOUT
    time.sleep(0.2)
for name, args, check, job in sorted(done, key=lambda d: list(CASES).index(d[0])):
    out, ev, st = finish(job); outs[name] = out
    good, detail = check(out, ev, st); jgood, jdetail = joint_step_ok(st, args)
    report(name, good and jgood, job["t0"], detail + ("" if not jdetail else "; " + jdetail))
    if not (good and jgood): print("   log: %s" % job["log"])
for dry, moving in PAIRS:
    if dry not in outs or moving not in outs: continue
    a, b = raise_line(outs[dry]), moving_raise(outs[moving]); t0 = time.time()
    good = a is not None and b is not None and abs(a[0] - b[0]) <= 0.001 and abs(a[1] - b[1]) <= 0.005 and abs(a[2] - b[2]) <= 0.005
    report("dry line = moving raise: %s / %s" % (dry, moving), good, t0, "dry (z, up-low x, up x) %s, moving %s" % (a, b))

print("CHECK:", "PASS" if ok else "FAIL", "(logs in %s)" % TMP); sys.exit(0 if ok else 1)
