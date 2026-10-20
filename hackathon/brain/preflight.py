"""Preflight for the hackathon brain. Checks: llama-server health plus a warm-up request, FSM 500, hands publishing, D435i and C922
present (video and mic), the camera services stopped, arm service state, power mode and jetson_clocks, the factory assistant asleep,
and the no-cloud evidence (no default route, Wi-Fi radio off, tailscaled stopped). Prints a pass/fail table, writes runs/live/preflight.json
(shown on the brain view) and exits 1 on any hard failure, which makes brain.py refuse to start.
Usage: python preflight.py [--venue] [--json] [--mock] [--server URL] [--g1fetch DIR] [--runs DIR]
--venue: the no-cloud checks are hard failures. Default: warnings, so the office can keep Tailscale up for remote work."""
import argparse, glob, json, os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "bench"))
from client import get_json, timed_chat
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--venue", action="store_true"); ap.add_argument("--json", action="store_true"); ap.add_argument("--mock", action="store_true")
ap.add_argument("--server", default="http://127.0.0.1:8080/v1"); ap.add_argument("--g1fetch", default=os.environ.get("G1FETCH", "/home/unitree/g1-fetch"))
ap.add_argument("--runs", default=os.path.join(HERE, "runs")); ap.add_argument("--cam3", default="auto")
A = ap.parse_args()
ROOT = A.server.rsplit("/v1", 1)[0]
CAM_SERVICES = ["teleimager-realsense-webrtc.service", "teleimager-compat.service"]
CHECKS = []


def sh(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError: return 127, "command not found"
    except subprocess.TimeoutExpired: return 124, "timeout"


def check(name, fn, hard=True):
    """Run one check; fn returns (ok_or_status, detail[, hint]). True=PASS, False=FAIL (WARN when not hard), or 'WARN'/'SKIP'."""
    t0 = time.time()
    try: r = fn()
    except Exception as e: r = (False, "%s: %s" % (type(e).__name__, str(e)[:160]))
    st, detail, hint = (tuple(r) + ("",))[:3]
    status = st if isinstance(st, str) else ("PASS" if st else ("FAIL" if hard else "WARN"))
    CHECKS.append({"name": name, "status": status, "detail": detail, "hint": hint, "ms": int((time.time() - t0) * 1000)})
    return status == "PASS"


# --- server -----------------------------------------------------------------------------------------
def c_server():
    h = get_json(ROOT, "/health", timeout=5)
    models = get_json(ROOT, "/v1/models", timeout=5).get("data", [])
    ids = [m.get("id") for m in models]
    return h.get("status") == "ok", "health %s, models %s" % (h.get("status"), ids), "~/spike/serve-orin.sh"


def c_warmup():
    img = None
    try:
        import cv2
        node = A.cam3 if A.cam3 != "auto" else next(iter(sorted(glob.glob("/dev/v4l/by-id/usb-046d_C922*-video-index0"))), "/dev/video6")
        cap = cv2.VideoCapture(node, cv2.CAP_V4L2); cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        ok = False
        for _ in range(8): ok, fr = cap.read()
        cap.release(); img = fr if ok else None
    except Exception: img = None
    if img is not None:
        from gemma import Gemma
        ans, rec = Gemma(A.server).warmup(img)
        return "error" not in rec, "C922 frame + yes/no: %r in %d ms (prompt %s tok)" % (ans, rec["ms"], rec.get("prompt_n")), ""
    msgs = [{"role": "system", "content": "You are a robot's vision module. Image left/right are robot left/right."}, {"role": "user", "content": "Say ready. Answer with one word."}]
    r = timed_chat(A.server, {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "max_tokens": 3, "chat_template_kwargs": {"enable_thinking": False}, "messages": msgs}, timeout=60)
    return "WARN", "text-only warm-up (no C922 frame): %r in %d ms" % (r["content"].strip(), r["total_s"] * 1000), "the vision prefix is still cold"


# --- devices and services (no DDS) -------------------------------------------------------------------
def c_cam_services():
    code, out = sh(["systemctl", "is-active"] + CAM_SERVICES)
    if code == 127: return "SKIP", "systemctl not available", ""
    states = out.split()
    return all(s != "active" for s in states), ", ".join("%s=%s" % (s.split(".")[0].replace("teleimager-", ""), st) for s, st in zip(CAM_SERVICES, states)), "sudo systemctl stop " + " ".join(CAM_SERVICES)


def c_d435i():
    ids = glob.glob("/dev/v4l/by-id/*RealSense*") + glob.glob("/dev/v4l/by-id/*Intel*")
    code, lsusb = sh(["lsusb"])
    usb = [l for l in lsusb.splitlines() if "8086:0b3a" in l.lower() or "realsense" in l.lower()]
    return bool(ids or usb), "%d v4l nodes, lsusb: %s" % (len(ids), usb[0][:60] if usb else "none"), "check the head camera cable"


def c_c922_video():
    ids = sorted(glob.glob("/dev/v4l/by-id/usb-046d_C922*-video-index0"))
    return bool(ids), ids[0] if ids else "no C922 video node", "plug the C922 into PC2"


def c_c922_mic():
    code, out = sh(["arecord", "-l"])
    if code == 127: return False, "arecord not found", "apt install alsa-utils"
    m = re.search(r"card (\d+): [^\n]*C922", out)
    return bool(m), "plughw:%s,0" % m.group(1) if m else "no C922 capture card in arecord -l", "the brain records from plughw:N,0"


def c_power():
    try: online = open("/sys/devices/system/cpu/online").read().strip()
    except OSError: return "SKIP", "not a Jetson", ""
    maxn = online == "0-7"
    return maxn, "cpus online %s (%s)" % (online, "MAXN" if maxn else "not MAXN: 15 W mode has 4 cores"), "sudo nvpmodel -m 0 (reboot)"


def c_clocks():
    d = "/sys/class/devfreq/17000000.gpu"
    if not os.path.isdir(d): return "SKIP", "no GPU devfreq node", ""
    cur, mn, mx = [int(open(os.path.join(d, f)).read()) // 1000000 for f in ("cur_freq", "min_freq", "max_freq")]
    pinned = mn == mx
    return "PASS" if pinned else "WARN", "GPU %d MHz now, min %d, max %d (%s)" % (cur, mn, mx, "pinned by jetson_clocks" if pinned else "NOT pinned"), "sudo jetson_clocks (after every boot)"


def c_no_default_route():
    code, out = sh(["ip", "route"])
    if code == 127: return "SKIP", "ip not available", ""
    default = [l for l in out.splitlines() if l.startswith("default")]
    return not default, (default[0][:70] if default else "no default route"), "unplug the uplink / nmcli con down <uplink>"


def c_wifi_radio():
    code, out = sh(["nmcli", "radio", "wifi"])          # prints enabled / disabled (PC2's nmcli has no 'status' argument)
    if code == 127: return "SKIP", "nmcli not available", ""
    st = out.strip().split()[-1] if out.strip() else "?"
    return st == "disabled", "onboard Wi-Fi radio %s" % st, "nmcli radio wifi off (the MT7612U AP is hostapd, unaffected)"


def c_tailscaled():
    code, out = sh(["systemctl", "is-active", "tailscaled"])
    if code == 127: return "SKIP", "systemctl not available", ""
    return out.strip() != "active", "tailscaled %s" % out.strip(), "sudo systemctl stop tailscaled"


# --- DDS checks (g1-fetch + unitree_sdk2py) ----------------------------------------------------------
DDS = {}
def dds_init():
    if "cfg" in DDS: return DDS["cfg"]
    sys.path.insert(0, A.g1fetch)
    from g1_fetch.config import load_config
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    cfg = load_config(os.path.join(A.g1fetch, "configs", "pc2.yaml"))
    ChannelFactoryInitialize(0, str(cfg.network_interface)); DDS["cfg"] = cfg
    return cfg


def c_fsm():
    cfg = dds_init()
    from g1_fetch.control.loco import UnitreeLoco
    loco = UnitreeLoco(cfg); loco.start()
    try: fsm = loco.fsm_id()
    finally: loco.close()
    return fsm == 500, "fsm_id %s" % fsm, "R1+X on the remote (locked stand, in the stand)"


def c_hands():
    cfg = dds_init()
    from g1_fetch.control.hand import UnitreeBraincoHand
    out = {}
    for side in ("left", "right"):
        h = UnitreeBraincoHand(cfg, side); t0 = time.time()
        while h._state_msg is None and time.time() - t0 < 2.0: time.sleep(0.05)
        out[side] = h._state_msg is not None; h.close()
    left = out["left"]
    return ("PASS" if left and out["right"] else "WARN" if left else "FAIL"), "left %s, right %s" % tuple("publishing" if out[s] else "silent" for s in ("left", "right")), "systemctl status brainco_hand.service"


def c_arm_service():
    dds_init()
    from unitree_sdk2py.go2.robot_state.robot_state_client import RobotStateClient
    c = RobotStateClient(); c.SetTimeout(5.0); c.Init()
    code, lst = c.ServiceList()
    if code != 0 or not lst: return "WARN", "ServiceList code %s" % code, ""
    st = {s.name: s.status for s in lst}
    arm = st.get("g1_arm_example")                     # Unitree robot_state docs: status 0 = on, 1 = off
    return ("PASS" if arm == 0 else "WARN" if arm == 1 else "FAIL"), "g1_arm_example %s (brain switches it off at start, on at exit)" % ("on" if arm == 0 else "off" if arm == 1 else "unknown %s" % arm), "off after a crashed run is fine: the brain restores it on exit"


def c_assistant():
    dds_init()
    from unitree_sdk2py.core.channel import ChannelSubscriber
    from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_
    msgs = []; sub = ChannelSubscriber("rt/audio_msg", String_); sub.Init(lambda m: msgs.append(m.data), 10)
    time.sleep(3.0); sub.Close()
    return "PASS" if not msgs else "WARN", "rt/audio_msg: %d messages in 3 s%s" % (len(msgs), " e.g. " + msgs[0][:60] if msgs else ""), "put the factory assistant to sleep in the app (close interaction)"


def main():
    check("server", c_server); check("warmup", c_warmup)
    if A.mock:
        for n in ("cam_services", "d435i", "c922_video", "c922_mic", "power", "clocks", "fsm", "hands", "arm_service", "assistant"):
            CHECKS.append({"name": n, "status": "SKIP", "detail": "mock", "hint": "", "ms": 0})
    else:
        check("cam_services", c_cam_services); check("d435i", c_d435i); check("c922_video", c_c922_video); check("c922_mic", c_c922_mic)
        check("power", c_power, hard=False); check("clocks", c_clocks, hard=False)
        check("fsm", c_fsm); check("hands", c_hands); check("arm_service", c_arm_service, hard=False); check("assistant", c_assistant, hard=False)
    for n, fn in (("no_default_route", c_no_default_route), ("wifi_radio", c_wifi_radio), ("tailscaled", c_tailscaled)): check(n, fn, hard=A.venue)
    ok = all(c["status"] != "FAIL" for c in CHECKS); warns = sum(c["status"] == "WARN" for c in CHECKS)
    rows = ["%-17s %-5s %s%s" % (c["name"], c["status"], c["detail"], ("  -> " + c["hint"]) if c["status"] in ("FAIL", "WARN") and c["hint"] else "") for c in CHECKS]
    table = "\n".join(rows) + "\nPREFLIGHT: %s (%d warnings)%s" % ("PASS" if ok else "FAIL", warns, "" if ok else "  failed: " + ", ".join(c["name"] for c in CHECKS if c["status"] == "FAIL"))
    rep = {"ok": ok, "venue": A.venue, "t": time.time(), "when": time.strftime("%Y-%m-%d %H:%M:%S"), "checks": CHECKS, "table": table}
    live = os.path.join(A.runs, "live"); os.makedirs(live, exist_ok=True)
    with open(os.path.join(live, "preflight.json"), "w") as f: json.dump(rep, f)
    print(json.dumps(rep) if A.json else table)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
