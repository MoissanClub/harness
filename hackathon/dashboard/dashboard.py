"""Judges' dashboard for brain v2: one page, served from PC2, that shows Gemma's inference, the boxed head-camera frames, the can the
guest chose and every movement step, live. Stdlib only (Python 3.8+).

It only READS what brain.py already writes: runs/live/status.json and frame.jpg (state, spoken sentence, live frame), and per order
runs/<session>/order_NN.jsonl plus the order_NN/ folder (frames, frame bundles, audio clips). Nothing in hackathon/brain changes, so
the brain tree stays clean for --expect-calib; that is also why this lives outside hackathon/brain.

  python3 dashboard.py                                  # PC2, next to the brain: http://10.42.0.1:8000 over the robot's AP
  python3 dashboard.py --replay RUNS_OR_SESSION [...]   # recorded sessions with their own timing; the page says REPLAY
"""
import argparse, bisect, json, os, re, statistics, subprocess, sys, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_RE, ORDER_RE = re.compile(r"^\d{8}T\d{6}$"), re.compile(r"^order_(\d+)\.jsonl$")
MOTION = ("PICK", "SERVO", "APPROACH", "VERIFY", "LIFT", "CHECK", "HANDOVER", "RECOVER")
MOVES = {"up-low": "up behind the table edge", "up": "up beside the body", "high": "forward, high over the table", "pre": "down beside the can",
         "lift": "lift", "offer": "out to the guest", "home": "home", "assist-up": "back and up, hand open", "assist-offer": "out to the guest, hand open",
         "retreat-up": "up, away from the can", "retreat-back": "back over the table edge", "bridge": "joint-space path to the raise"}


def move_name(label):
    if label in MOVES: return MOVES[label]
    for pre, name in (("fix-", "correction after an '%s' grasp"), ("servo", "servo correction %s"), ("back", "back step %s"), ("ap", "approach step %s")):
        if label.startswith(pre): return name % label[len(pre):]
    return label.replace("-", " ")


FILES = {".jpg": "image/jpeg", ".png": "image/png", ".wav": "audio/wav"}
CAM3 = {"pregrasp": "side camera: hand beside the can", "slide": "side camera: after the approach", "closed": "side camera: hand closed",
        "lifted": "side camera: can lifted"}
RELEASE = {"voice": "heard the guest say take it", "vision": "saw the guest's hand (Gemma confirmed)", "taken": "felt the guest pull the can",
           "operator": "operator key", "timer": "rehearsal timer"}


def parse():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000); ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--runs", default=os.path.normpath(os.path.join(HERE, "..", "brain", "runs")), help="the brain's runs folder (brain.py --runs)")
    ap.add_argument("--server", default="http://127.0.0.1:8080", help="llama-server, for the health line")
    ap.add_argument("--replay", nargs="+", metavar="DIR", help="recorded session folders, or folders of them, played with their own timing")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed")
    ap.add_argument("--max-gap", type=float, default=4.0, help="replay: a pause longer than this many seconds is shortened to it")
    ap.add_argument("--loop", action="store_true", help="replay: start again after the last session")
    ap.add_argument("--hours", type=float, default=14.0, help="the tally counts the sessions started in the last HOURS")
    return ap.parse_args()


A = parse()


# --- reading the brain's files ------------------------------------------------------------------------------------------------
class Jsonl:
    """Incremental JSON-lines reader: only complete lines are parsed; a file that shrinks is read again. Each record gets _t, its
    numeric time (records whose t is a string, like `result`, inherit the one before)."""
    def __init__(self, path): self.path, self.pos, self.size, self.buf, self.recs = path, 0, -1, b"", []

    def poll(self):
        try: size = os.path.getsize(self.path)
        except OSError: return False
        if size == self.size: return False
        if size < self.pos: self.pos, self.buf, self.recs = 0, b"", []
        with open(self.path, "rb") as f:
            f.seek(self.pos); data = self.buf + f.read(size - self.pos)
        self.pos = self.size = size; lines = data.split(b"\n"); self.buf = lines.pop(); last = self.recs[-1]["_t"] if self.recs else 0.0
        for line in lines:
            try: r = json.loads(line)
            except ValueError: continue
            if not isinstance(r, dict): continue
            t = r.get("t"); r["_t"] = last = float(t) if isinstance(t, (int, float)) else last
            self.recs.append(r)
        return True


FILES_CACHE = {}
def jsonl(path):
    j = FILES_CACHE.get(path)
    if j is None: j = FILES_CACHE[path] = Jsonl(path)
    j.poll(); return j


def read_json(path):
    try:
        with open(path) as f: return json.load(f)
    except (OSError, ValueError): return None


def mtime(path):
    try: return os.stat(path).st_mtime
    except OSError: return 0.0


def session_time(name):
    try: return time.mktime(time.strptime(name, "%Y%m%dT%H%M%S"))
    except ValueError: return 0.0


def orders_in(sdir):
    try: names = os.listdir(sdir)
    except OSError: return []
    return sorted((int(m.group(1)), os.path.join(sdir, n)) for n, m in ((n, ORDER_RE.match(n)) for n in names) if m)


def sessions_in(root):
    try: return sorted(os.path.join(root, n) for n in os.listdir(root) if SESSION_RE.match(n) and os.path.isdir(os.path.join(root, n)))
    except OSError: return []


SESSIONS = {}                                    # session name -> folder, the only folders the file route serves
def register(sdir):
    SESSIONS[os.path.basename(sdir.rstrip("/"))] = os.path.realpath(sdir); return os.path.basename(sdir.rstrip("/"))


# --- one order -> what the page shows ---------------------------------------------------------------------------------------
def mm(v): return None if v is None else int(round(float(v) * 1000))


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]); inter = max(0, x2 - x1) * max(0, y2 - y1)
    return inter / float((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def file_ref(base, path, names):
    """A path the brain logged (absolute, on PC2) -> the page's URL, if that file is in the order folder."""
    if not isinstance(path, str): return None
    n = os.path.basename(path); return base + "/" + n if n in names else None


def choice_index(ans, n):
    m = re.search(r"\d+", ans or ""); i = int(m.group()) - 1 if m else None
    return i if i is not None and 0 <= i < n else None


def frames_of(odir, base, cutoff, recs, names, scene, chosen):
    """The order's frames, oldest first: raw bundles get boxes drawn on the page (overlay), the brain's own annotated frames are shown as
    they are; of the handover frames only the latest."""
    try: ents = [(e.name, e.stat().st_mtime) for e in os.scandir(odir) if e.is_file()]
    except OSError: return []
    target = next((r for r in reversed(recs) if r.get("ev") == "target"), None)
    loc_det = next((r for r in reversed(recs) if r.get("ev") == "detect" and r.get("stage") == "LOCATE"), None)
    out, hold = [], None
    for n, mt in ents:
        if cutoff is not None and mt > cutoff + 0.5: continue
        stem, ext = os.path.splitext(n)
        if ext != ".jpg": continue
        f = {"url": base + "/" + n, "t": mt, "cam": "head", "overlay": None}
        if n == "bundle_look_color.jpg":
            f.update(label="LOOK: the cans Gemma described", overlay={"kind": "look", "boxes": [
                {"box": c.get("box"), "label": "%d  %s" % (c.get("i", 0) + 1, c.get("desc", "")), "chosen": c.get("i") == chosen} for c in scene]})
        elif n == "look.jpg" and "bundle_look_color.jpg" not in names: f["label"] = "LOOK: the cans Gemma described"
        elif n == "bundle_locate_color.jpg":
            boxes = []
            if target and target.get("box"):
                p = target.get("p") or [0, 0, 0]
                boxes.append({"box": target["box"], "label": "target  %.2f m ahead, %.2f m left, %d mm" % (p[0], p[1], mm(target.get("diam")) or 0), "chosen": True})
            for b in (loc_det or {}).get("boxes") or []:
                if not (target and target.get("box") and iou(b, target["box"]) > 0.6): boxes.append({"box": b, "label": "", "chosen": False})
            f.update(label="LOCATE: the chosen can, measured in depth", overlay={"kind": "locate", "boxes": boxes})
        elif n == "locate.jpg" and "bundle_locate_color.jpg" not in names: f["label"] = "LOCATE: the chosen can, measured in depth"
        elif stem.startswith("measure_"): f["label"] = "hand check (%s): red = hand from depth, yellow = Gemma's box of the hand" % stem[8:]
        elif stem.startswith("cam3_"): f.update(cam="cam3", label=CAM3.get(stem[5:], "side camera: " + stem[5:]))
        elif n == "bundle_lift_color.jpg": f["label"] = "head camera after the lift"
        elif n == "bundle_offer_color.jpg": f["label"] = "head camera at the offer"
        elif stem.startswith("hold_"):
            f["label"] = "handover: watching for the guest's hand"
            if hold is None or mt > hold["t"]: hold = f
            continue
        else: continue
        out.append(f)
    if hold: out.append(hold)
    return sorted(out, key=lambda f: f["t"])


class Steps:
    """The movement-and-planning timeline. A spoken sentence from PICK on starts a step (the brain announces every move); moves,
    approach steps, checks and Gemma calls during motion attach to the step they happen in."""
    def __init__(self): self.out = []; self.cur = None; self.plane = None

    def add(self, r, title, tag=None, kind="ok", **kw):
        s = {"t": r["_t"], "stage": r.get("stage"), "title": title, "tag": tag or r.get("tag"), "kind": kind, "det": [], "sub": [], "n": 1}
        s.update(kw); self.out.append(s); self.cur = s; return s

    def det(self, r, text, kind=None):
        if self.cur is None: self.add(r, (r.get("stage") or "").title() or "Step")
        if text and text not in self.cur["det"]: self.cur["det"].append(text)
        if kind == "warn" and self.cur["kind"] == "ok": self.cur["kind"] = "warn"

    def servo_step(self, r):
        if self.cur is None or self.cur.get("key") != "servo": self.add(r, "Head camera checks the hand", tag="sensor gate", key="servo")
        return self.cur

    def find(self, key, back=6):
        for s in reversed(self.out[-back:]):
            if s.get("key") == key: return s
        return None

    def feed(self, r, scene):
        ev, st = r.get("ev"), r.get("stage")
        if ev == "say" and st in MOTION:
            text = (r.get("text") or "").strip(); title = text.rstrip(".")
            if text.startswith("I am holding the can") and self.find("hold", 12) is not None:
                self.find("hold", 12)["reminders"] = self.find("hold", 12).get("reminders", 0) + 1; return     # the handover reminder
            s = next((s for s in reversed(self.out[-4:]) if s["title"] == title), None)
            if s is not None and text.startswith(("I am holding", "I have no safe", "Press y", "Hold my arm")): s["n"] += 1; return
            self.add(r, title, kind="warn" if text.startswith(("I have no safe", "I missed", "I stop")) else "ok")
        elif ev == "target":
            p = r.get("p") or [0, 0, 0]
            self.add(r, "Located the %s can" % r.get("desc", ""), tag="sensor gate", det=["%.2f m ahead, %.2f m to the left, %d mm can (depth camera)" % (p[0], p[1], mm(r.get("diam")) or 0)] + ([self.plane] if self.plane else []))
        elif ev == "plane" and r.get("plane"): self.plane = "table top at z %+.3f m from the pelvis, fitted in depth" % r["plane"]["z"]
        elif ev == "safety_check":
            if r.get("blocked"): self.add(r, "Something is in the way: no motion", tag="sensor gate", kind="warn", det=[r.get("why") or ""])
            elif self.cur is not None: self.cur["checks"] = self.cur.get("checks", 0) + 1
        elif ev == "plan":
            if r.get("ok"):
                c = (r.get("checks") or {}).get("grasp") or {}; tried = r.get("tried") or []
                self.add(r, "Planned the reach", tag="scripted skill", det=["forearm yaw %s deg, pitch %s deg; %d of %d yaws feasible" % (r.get("psi"), r.get("pitch"), sum(1 for t in tried if t.get("ok")), len(tried)),
                                                                            "clearance to the torso %s cm, to the table %s cm" % (None if c.get("upper") is None else round(c["upper"] * 100, 1), None if c.get("table") is None else round(c["table"] * 100, 1))])
            else: self.add(r, "No safe reach: %s" % r.get("reason", "?"), tag="scripted skill", kind="warn")
        elif ev in ("move", "home"):
            lab = r.get("label", ""); name = move_name(lab)
            if self.cur is None or self.cur["stage"] != r.get("stage"): self.add(r, name[:1].upper() + name[1:], tag="scripted skill")
            e = r.get("err"); self.det(r, "%s%s%s%s" % (name, "" if e is None else ": palm within %s mm of the goal" % mm(e), ", %d correction rounds" % r["rounds"] if r.get("rounds") else "",
                                                       ", STOPPED: %s" % r["blocked"] if r.get("blocked") else ""), "warn" if r.get("blocked") else None)
        elif ev == "sag": self.det(r, "arm sag measured: %s mm" % mm(r.get("err")))
        elif ev == "measure" and str(r.get("label", "")).startswith("servo"):
            if r.get("in_view") is False: txt = "hand at the image edge: not used"
            elif r.get("err"): txt = "hand error %s mm (along the forearm, toward the can, up)" % ", ".join(str(mm(v)) for v in r["err"])
            else: txt = "hand seen, %s depth points" % r.get("n_blob")
            s = self.servo_step(r); s["det"].append(txt)
            if r.get("gemma_on_blob") is not None and r.get("in_view") is not False: s["det"].append("Gemma's box of the hand overlaps the depth blob %d%%" % round(r["gemma_on_blob"] * 100))
        elif ev == "servo" and r.get("aborted"): self.det(r, "servo stopped: %s" % r["aborted"], "warn")
        elif ev == "servo" and r.get("delta"): self.det(r, "correction %s mm" % ", ".join(str(mm(v)) for v in r["delta"]))
        elif ev == "ap_step":
            if self.cur is None or self.cur["title"] != "Approaching": self.add(r, "Approaching", tag="scripted skill")
            self.cur["sub"].append({"step": r.get("step"), "moved": mm(r.get("moved")), "gap": mm(r.get("gap"))})
        elif ev == "approach":
            if self.cur is None or self.cur["title"] != "Approaching": self.add(r, "Approaching", tag="scripted skill")
            ok = r.get("result") == "ok"
            self.det(r, "%s steps, final gap %s mm: %s" % (r.get("steps"), mm(r.get("gap")), "close the hand" if ok else "%s, %s" % (r.get("result"), r.get("why"))), None if ok else "warn")
        elif ev == "hand":
            if self.cur is None or self.cur.get("key") != "close": self.add(r, "Closing the hand, thumb first", tag="scripted skill", key="close")
            stv = r.get("state")
            if stv: self.cur["det"] = ["finger positions " + " ".join("%.2f" % v for v in stv)]
        elif ev == "stall": self.det(r, "finger stall pattern: %s" % r.get("pattern"), None if r.get("pattern") == "grasped" else "warn")
        elif ev == "verify":
            g = r.get("grasped") in (True, "True", "true"); hs = r.get("hand_state") or []
            self.add(r, "Grasp confirmed by the fingers" if g else "No grasp: the fingers did not stall on the can", tag="sensor gate", kind="ok" if g else "fail",
                     det=["closure %.2f, thumb %.2f, fingers stalled %s of 4" % (r.get("closure") or 0, hs[0] if hs else 0, sum(1 for v in r.get("stalled") or [] if v in (True, "True")))])
        elif ev == "lift_check" and r.get("rise") is not None: self.det(r, "head camera: the can rose %.1f cm" % (r["rise"] * 100))
        elif ev == "offer": self.add(r, "Offering the can", tag="scripted skill", det=["offer pose %s the head camera's view" % ("inside" if r.get("in_view") else "outside")])
        elif ev in ("hold", "cluster"):
            s = self.find("hold", 12)
            if s is None: s = self.add(r, "Waiting for the guest to take it", tag="sensor gate", key="hold", t0=r["_t"], checks=0, heard=[])
            if ev == "hold": s["checks"] = s.get("checks", 0) + 1
        elif ev == "gemma" and st in MOTION:
            k, a = r.get("kind"), (r.get("answer") or "").strip()
            if k == "take_it":
                s = self.find("hold", 12)
                if s is not None and a: s["heard"] = (s["heard"] + [a])[-4:]
            elif k == "yesno" and st == "HANDOVER" and self.find("hold", 12) is not None:
                h = self.find("hold", 12); h["asked"] = h.get("asked", 0) + 1; h["asked_last"] = "%s (%d ms)" % (a or "(empty)", r.get("ms") or 0)
            elif k == "yesno":
                self.add(r, "Gemma checks the grasp from the side camera" if st == "CHECK" else "Gemma: is the guest's hand on the can?", tag=r.get("tag"),
                         det=["%s -> %s (%d ms)%s" % (r.get("question", ""), a or "(empty)", r.get("ms") or 0, ", advisory only" if "advisory" in (r.get("tag") or "") else "")])
            elif k == "box": self.servo_step(r)["det"].append("Gemma boxed the robot's hand in %d ms" % (r.get("ms") or 0))
        elif ev == "taken": self.det(r, "the fingers felt a pull")
        elif ev == "release": self.add(r, "Released the can", tag=r.get("tag"), det=[RELEASE.get(r.get("how"), str(r.get("how"))) + (", after %.0f s" % r["hold_s"] if r.get("hold_s") else "")])
        elif ev == "held": self.add(r, "The arm holds still", tag="scripted skill", kind="warn", det=[r.get("why") or ""])
        elif ev == "way_home":
            if r.get("ok"): self.det(r, "way home planned")
            elif not (self.cur and (r.get("why") or "") in " ".join(self.cur["det"])): self.det(r, "no safe way home: %s" % r.get("why"), "warn")
        elif ev == "park": self.det(r, "arm parked at home")
        elif ev == "error": self.add(r, "Error", kind="fail", det=[str(r.get("error", ""))[:200]])


SUMMARY = {}
def summarize(sdir, n, path, cutoff=None):
    """Cached: rebuilt only when the order log grows, a frame is added or the replay clock moves."""
    key = (path, jsonl(path).size, mtime(os.path.join(sdir, "order_%02d" % n)), cutoff)
    if SUMMARY.get("key") != key: SUMMARY.update(key=key, o=build(sdir, n, path, cutoff))
    return SUMMARY["o"]


def build(sdir, n, path, cutoff):
    sname = register(sdir); recs = [r for r in jsonl(path).recs if cutoff is None or r["_t"] <= cutoff]
    odir = os.path.join(sdir, "order_%02d" % n); base = "run/%s/order_%02d" % (sname, n)
    try: names = set(os.listdir(odir))
    except OSError: names = set()
    scene = next((r.get("cans") or [] for r in reversed(recs) if r.get("ev") == "scene"), [])
    o = {"session": sname, "n": n, "t0": recs[0]["_t"] if recs else None, "t1": recs[-1]["_t"] if recs else None, "stage": None, "stage_t0": None,
         "stages": [], "result": None, "params": {}, "calib": {}, "deviations": [], "scene": [], "attempts": [], "chosen": None, "confirm": None,
         "gemma": [], "steps": [], "frames": [], "say": None, "say_t": None}
    steps = Steps(); last_record = None; att = None; box_item = None
    for r in recs:
        ev, st = r.get("ev"), r.get("stage")
        if st: o["stage"] = st
        if ev == "order": o["params"] = {k: v for k, v in (r.get("params") or {}).items() if k in ("model_grasp", "speed", "probe", "air", "no_grasp", "lift")}
        elif ev == "calib": o["calib"] = {"sha": r.get("calib_sha"), "git": r.get("git"), "dirty": r.get("dirty")}
        elif ev == "deviation": o["deviations"].append("%s %s" % (r.get("key"), r.get("cli")))
        elif ev == "stage": o["stages"].append({"stage": st, "ms": r.get("ms")}); o["stage_t0"] = r["_t"]
        elif ev == "say":
            o["say"], o["say_t"] = r.get("text"), r["_t"]
            if st == "LISTEN" and r.get("text") != "Listening.":
                att = {"asked": r.get("text"), "audio": None, "seconds": None, "answer": None, "ms": None, "idx": None, "tokens": None}; o["attempts"].append(att)
            elif st == "CONFIRM": o["confirm"] = r.get("text")
        elif ev == "record":
            last_record = r
            if att is None: att = {"asked": None, "answer": None, "idx": None}; o["attempts"].append(att)
            att.update(audio=file_ref(base, r.get("path"), names), seconds=r.get("seconds"))
        elif ev == "result": o["result"] = {k: r.get(k) for k in ("result", "autonomous", "release", "total_ms", "assisted", "hold_s")}
        if ev == "gemma":
            k, a = r.get("kind"), (r.get("answer") or "").strip(); media = r.get("media"); item = {
                "t": r["_t"], "stage": st, "kind": k, "q": r.get("question"), "a": a, "ms": r.get("ms"), "pn": r.get("prompt_n"), "on": r.get("predicted_n"),
                "cache": r.get("cache_n"), "tag": r.get("tag"), "err": r.get("error"), "n": 1, "ms_all": [r.get("ms") or 0], "media": None}
            if isinstance(media, str) and media.startswith("can "):
                try: item["media"] = {"crop": int(media[4:])}
                except ValueError: pass
            elif media == "audio" and k == "hear_choice" and last_record: item["media"] = {"audio": file_ref(base, last_record.get("path"), names)}
            elif media == "audio": item["media"] = {"audio": None}
            elif isinstance(media, str) and "/" in media: item["media"] = {"img": file_ref(base, media, names)}
            if k == "box":
                box_item = item; nums = re.findall(r"\d+", a[a.rindex("[") + 1:] if "[" in a else a)[:4]
                item["a"] = "box_2d [%s]" % ", ".join(nums) if len(nums) == 4 else (a or "no box")
            if k == "hear_choice":
                if att is None: att = {"asked": None, "audio": None, "seconds": None}; o["attempts"].append(att)
                att.update(answer=a, ms=r.get("ms"), idx=choice_index(a, len(scene)), tokens=[r.get("prompt_n"), r.get("predicted_n")]); att = None
            prev = next((g for g in reversed(o["gemma"][-4:]) if g["kind"] == k and g["a"] == item["a"] and g["stage"] == st), None) if k in ("take_it", "yesno") and not item["err"] else None
            if prev:
                prev["n"] += 1; prev["ms_all"].append(item["ms"] or 0); prev["t"] = item["t"]; o["gemma"].remove(prev); o["gemma"].append(prev)
            else: o["gemma"].append(item)
        elif ev == "measure" and box_item is not None:
            if "measure_%s.jpg" % r.get("label") in names: box_item["media"] = {"img": base + "/measure_%s.jpg" % r.get("label")}
            box_item = None
        steps.feed(r, scene)
    descs = {}
    for g in o["gemma"]:
        if g["kind"] == "describe" and g["media"] and "crop" in g["media"]: descs[g["media"]["crop"]] = g
    for a in o["attempts"]:
        if a.get("idx") is not None: o["chosen"] = a["idx"]
    o["scene"] = [{"i": c.get("i"), "desc": c.get("desc"), "words": c.get("words"), "box": c.get("box"), "size": c.get("size"), "p": c.get("p"),
                   "raw": (descs.get(c.get("i")) or {}).get("a"), "ms": (descs.get(c.get("i")) or {}).get("ms")} for c in scene]
    for g in o["gemma"]:
        g["ms_med"] = int(statistics.median(g.pop("ms_all")))
    o["gemma"] = o["gemma"][-60:]; o["steps"] = steps.out[-80:]
    o["frames"] = frames_of(odir, base, cutoff, recs, names, scene, o["chosen"])
    look = next((f for f in o["frames"] if f["url"].endswith(("bundle_look_color.jpg", "/look.jpg"))), None)
    o["look"] = look["url"] if look else None; o["look_raw"] = bool(look and look["overlay"])
    return o


# --- the tally across today's sessions ------------------------------------------------------------------------------------------
TALLY = {}
def tally(session_dirs, cutoff=None):
    paths = [p for s in session_dirs for _, p in orders_in(s)]; key = (tuple((p, jsonl(p).size) for p in paths), cutoff)
    if TALLY.get("key") != key: TALLY.update(key=key, t=count(paths, cutoff))
    return TALLY["t"]


def count(paths, cutoff):
    t = {"orders": 0, "finished": 0, "autonomous": 0, "success": 0, "honest_negatives": 0, "assisted": 0, "gemma_calls": 0, "gemma_ms": {}}
    for path in paths:
        recs = jsonl(path).recs
        if cutoff is not None: recs = [r for r in recs if r["_t"] <= cutoff]
        if not recs: continue
        t["orders"] += 1
        for r in recs:
            if r.get("ev") == "gemma" and not r.get("error"):
                t["gemma_calls"] += 1; t["gemma_ms"].setdefault(r.get("kind"), []).append(r.get("ms") or 0)
            elif r.get("ev") == "result":
                t["finished"] += 1; res = r.get("result")
                if r.get("autonomous"): t["autonomous"] += 1
                if res == "success": t["success"] += 1
                elif res == "refused": t["honest_negatives"] += 1
                elif res == "assisted": t["assisted"] += 1
    allms = [v for vs in t["gemma_ms"].values() for v in vs]
    t["gemma_median_ms"] = int(statistics.median(allms)) if allms else None
    t["gemma_ms"] = {k: {"n": len(v), "median": int(statistics.median(v))} for k, v in t["gemma_ms"].items() if v}
    return t


# --- no cloud and the server (PC2 only) -----------------------------------------------------------------------------------------
SYSTEM = {"nocloud": None, "server": None}


def sh(cmd):
    try: r = subprocess.run(cmd, capture_output=True, text=True, timeout=5); return (r.stdout + r.stderr).strip()
    except FileNotFoundError: return None
    except subprocess.TimeoutExpired: return "timeout"


def system_loop():
    while True:
        route = sh(["ip", "route"])
        if route is None: SYSTEM["nocloud"] = {"t": time.time(), "na": "not Linux: no-cloud evidence is shown on PC2 only"}
        else:
            radio, ts = sh(["nmcli", "radio", "wifi"]) or "n/a", sh(["systemctl", "is-active", "tailscaled"]) or "n/a"
            default = any(l.startswith("default") for l in route.splitlines()); wifi = radio.split()[-1] if radio.strip() else "?"
            SYSTEM["nocloud"] = {"t": time.time(), "default_route": default, "wifi": wifi, "tailscaled": ts, "ok": (not default) and wifi == "disabled" and ts != "active",
                                 "text": "$ ip route\n%s\n$ nmcli radio wifi\n%s\n$ systemctl is-active tailscaled\n%s\n$ ip -br addr\n%s" % (route or "(empty)", radio, ts, sh(["ip", "-br", "addr"]) or "")}
        srv = {"t": time.time(), "url": A.server, "ok": False, "model": None}
        try:
            with urllib.request.urlopen(A.server + "/health", timeout=1.5) as r: srv["ok"] = r.status == 200
            with urllib.request.urlopen(A.server + "/v1/models", timeout=1.5) as r: srv["model"] = (json.loads(r.read().decode()).get("data") or [{}])[0].get("id")
        except Exception as e: srv["error"] = type(e).__name__
        SYSTEM["server"] = srv
        time.sleep(10)


def alive(pid):
    if not isinstance(pid, int) or pid <= 0: return None
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True
    except OSError: return None


# --- live and replay sources ---------------------------------------------------------------------------------------------------
class Live:
    mode = "live"
    def __init__(self, runs): self.runs = runs; self.live = os.path.join(runs, "live")

    def current(self):
        """(session dir, order n, order path): the order named in status.json if it exists, else the newest order of the newest session."""
        st = read_json(os.path.join(self.live, "status.json")) or {}
        sdir = os.path.join(self.runs, st["session"]) if isinstance(st.get("session"), str) and SESSION_RE.match(st["session"]) else None
        if sdir:
            ords = orders_in(sdir); want = [o for o in ords if o[0] == st.get("order")] or ords[-1:]
            if want: return st, sdir, want[0][0], want[0][1]
        for s in reversed(sessions_in(self.runs)):
            ords = orders_in(s)
            if ords: return st, s, ords[-1][0], ords[-1][1]
        return st, None, None, None

    def snapshot(self):
        st, sdir, n, path = self.current(); now = time.time()
        o = summarize(sdir, n, path) if sdir else None
        fv = mtime(os.path.join(self.live, "frame.jpg"))
        current = bool(o and st.get("session") == o["session"] and st.get("order") == o["n"] and st.get("state") not in ("IDLE", "BOOT", "OFF") and alive(st.get("pid")) is not False)
        recent = [s for s in sessions_in(self.runs) if now - session_time(os.path.basename(s)) < A.hours * 3600]
        return {"mode": "live", "now": now, "order": o, "current": current, "tally": tally(recent), "tally_since": min([session_time(os.path.basename(s)) for s in recent] or [now]),
                "brain": {"state": st.get("state") or "OFF", "message": st.get("message"), "note": st.get("note"), "alive": alive(st.get("pid")), "t": st.get("t") if isinstance(st.get("t"), (int, float)) else None,
                          "frame": "live/frame.jpg?v=%d" % int(fv * 1000) if fv else None, "frame_label": st.get("frame_label"), "frame_t": fv or None,
                          "session": st.get("session"), "order": st.get("order"), "counters": st.get("counters")},
                "system": dict(SYSTEM, preflight=read_json(os.path.join(self.live, "preflight.json")))}


class Replay:
    mode = "replay"
    def __init__(self, dirs):
        self.sessions = []
        for d in dirs:
            d = os.path.abspath(d); self.sessions += [d] if orders_in(d) else [s for s in sessions_in(d) if orders_in(s)]
        if not self.sessions: sys.exit("--replay: no session folders with order_NN.jsonl under %s" % dirs)
        times = []
        for s in self.sessions:
            for n, p in orders_in(s):
                times += [r["_t"] for r in jsonl(p).recs if r["_t"] > 0]
                try: times += [e.stat().st_mtime for e in os.scandir(os.path.join(s, "order_%02d" % n)) if e.is_file()]
                except OSError: pass
        self.times = sorted(times); self.vt = [0.0]                              # real time -> replay time with long pauses shortened
        for a, b in zip(self.times, self.times[1:]): self.vt.append(self.vt[-1] + min(b - a, A.max_gap))
        self.start = time.time(); print("replay: %d session(s), %d orders, %.0f s at x%.1f" % (len(self.sessions), sum(len(orders_in(s)) for s in self.sessions), self.vt[-1] / A.speed if self.vt else 0, A.speed), flush=True)

    def cutoff(self):
        e = (time.time() - self.start) * A.speed
        if self.vt and e > self.vt[-1] + 8:
            if A.loop: self.start = time.time(); e = 0.0
        i = max(0, bisect.bisect_right(self.vt, e) - 1)
        return self.times[i] + max(0.0, min(e - self.vt[i], (self.times[i + 1] - self.times[i]) if i + 1 < len(self.times) else 0.0)) if self.times else 0.0

    def snapshot(self):
        c = self.cutoff(); cur = None
        for s in self.sessions:
            for n, p in orders_in(s):
                recs = jsonl(p).recs
                if recs and recs[0]["_t"] <= c: cur = (s, n, p)
        o = summarize(*cur, cutoff=c) if cur else None
        done = bool(o and o["result"]); state = "IDLE" if done or o is None else (o["stage"] or "LOOK")
        return {"mode": "replay", "now": c, "order": o, "current": not done, "tally": tally(self.sessions, c), "tally_since": self.times[0] if self.times else c,
                "replay": {"sessions": [os.path.basename(s) for s in self.sessions], "speed": A.speed, "max_gap": A.max_gap},
                "brain": {"state": state, "message": o["say"] if o else None, "alive": None, "t": None, "frame": None, "frame_label": None,
                          "session": o["session"] if o else None, "order": o["n"] if o else None},
                "system": {"nocloud": None, "server": None, "preflight": None}}


SRC = Replay(A.replay) if A.replay else Live(A.runs)
SNAP = {"v": 0, "json": b"{}"}; COND = threading.Condition()


def watch():
    """One thread rebuilds the snapshot 4 times a second and wakes the page streams only when it changed."""
    last = None
    while True:
        try:
            snap = SRC.snapshot(); key = json.dumps({k: v for k, v in snap.items() if k != "now"}, sort_keys=True, default=str)          # the clock alone is no change
            if key != last or SNAP["v"] == 0:
                with COND: SNAP["json"] = json.dumps(snap, default=str).encode(); SNAP["v"] += 1; COND.notify_all()
                last = key
        except Exception as e: print("snapshot failed: %r" % e, flush=True)
        time.sleep(0.25)


# --- HTTP ----------------------------------------------------------------------------------------------------------------------
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def send(self, code, ctype, body, cache="no-store", extra=None):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "page.html"), "rb") as f: return self.send(200, "text/html; charset=utf-8", f.read())
        if path == "/api/state": return self.send(200, "application/json", SNAP["json"])
        if path == "/events": return self.stream()
        if path == "/live/frame.jpg" and isinstance(SRC, Live): return self.file(os.path.join(SRC.live, "frame.jpg"), "no-store")
        m = re.match(r"^/run/(\d{8}T\d{6})/(order_\d+)/([A-Za-z0-9_.-]+)$", path)
        if m and m.group(1) in SESSIONS:
            full = os.path.realpath(os.path.join(SESSIONS[m.group(1)], m.group(2), m.group(3)))
            if full.startswith(SESSIONS[m.group(1)] + os.sep): return self.file(full, "max-age=600")
        self.send(404, "text/plain", b"not found")

    def file(self, full, cache):
        ctype = FILES.get(os.path.splitext(full)[1])
        if ctype is None: return self.send(404, "text/plain", b"not found")
        try:
            with open(full, "rb") as f: data = f.read()
        except OSError: return self.send(404, "text/plain", b"not found")
        rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")           # Safari plays audio only with range replies
        if rng and data:
            a = int(rng.group(1)) if rng.group(1) else max(0, len(data) - int(rng.group(2) or 0)); b = int(rng.group(2)) if rng.group(1) and rng.group(2) else len(data) - 1
            b = min(b, len(data) - 1)
            if a > b: return self.send(416, "text/plain", b"", extra={"Content-Range": "bytes */%d" % len(data)})
            return self.send(206, ctype, data[a:b + 1], cache, {"Content-Range": "bytes %d-%d/%d" % (a, b, len(data)), "Accept-Ranges": "bytes"})
        self.send(200, ctype, data, cache, {"Accept-Ranges": "bytes"})

    def stream(self):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.send_header("Connection", "close"); self.end_headers()
        self.close_connection = True
        v = -1
        try:
            while True:
                with COND:
                    if SNAP["v"] == v: COND.wait(10)
                    data, nv = SNAP["json"], SNAP["v"]
                if nv != v: self.wfile.write(b"data: " + data + b"\n\n"); v = nv
                else: self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError): return


def main():
    threading.Thread(target=watch, daemon=True).start()
    if isinstance(SRC, Live): threading.Thread(target=system_loop, daemon=True).start()
    try: srv = ThreadingHTTPServer((A.host, A.port), H)
    except OSError as e: sys.exit("port %d: %s (the old brainview.py also uses 8000: stop it, or pass --port 8001)" % (A.port, e))
    srv.daemon_threads = True
    print("dashboard on http://%s:%d/ (%s)" % (A.host, A.port, "replay of %d session(s)" % len(SRC.sessions) if isinstance(SRC, Replay) else "live, runs %s" % A.runs), flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
