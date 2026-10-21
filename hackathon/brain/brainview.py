"""Brain view: one page served from PC2 over the robot's access point (http://10.42.0.1:8000) with server-sent events. Stdlib only.
Shows the latest head-camera frame with boxes, the state, the last question / answer / milliseconds, the provenance tag, the
autonomous success counter, the stage timings, the preflight result and a no-cloud panel (ip route, nmcli radio status, tailscaled).
It reads what brain.py and preflight.py write under runs/live/ (status.json, frame.jpg, preflight.json), so it can run before,
during and after the brain. Usage: python brainview.py [--port 8000] [--live DIR]"""
import argparse, json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--port", type=int, default=8000); ap.add_argument("--host", default="0.0.0.0")
ap.add_argument("--live", default=os.path.join(HERE, "runs", "live"))
A = ap.parse_args()
NOCLOUD = {"t": 0, "ip_route": "", "nmcli": "", "tailscaled": "", "addr": "", "default_route": None, "wifi": "", "ok": None}


def sh(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5); return (r.stdout + r.stderr).strip()
    except FileNotFoundError: return "n/a (%s not installed)" % cmd[0]
    except subprocess.TimeoutExpired: return "timeout"


def nocloud_loop():
    while True:
        route, radio, ts = sh(["ip", "route"]), sh(["nmcli", "radio", "wifi"]), sh(["systemctl", "is-active", "tailscaled"])
        default = any(l.startswith("default") for l in route.splitlines())
        wifi = radio.strip().split()[-1] if radio.strip() and "n/a" not in radio else "?"
        NOCLOUD.update(t=time.time(), ip_route=route or "(empty)", nmcli=radio, tailscaled=ts, addr=sh(["ip", "-br", "addr"]), default_route=default, wifi=wifi,
                       ok=(not default) and wifi == "disabled" and ts == "inactive")
        time.sleep(10)


def read_json(path):
    try:
        with open(path) as f: return json.load(f)
    except (OSError, ValueError): return None


def mtime(path):
    try: return os.stat(path).st_mtime_ns
    except OSError: return 0


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>G1 brain</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b0f14;--panel:#141b24;--line:#223041;--fg:#e6edf3;--dim:#8b9bb0;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--gemma:#7c9cff;--skill:#c5a3ff;--gate:#56d4dd}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
header{display:flex;align-items:center;gap:18px;padding:10px 18px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:18px;margin:0;font-weight:600}header .sub{color:var(--dim);font-size:13px}
#state{font-size:34px;font-weight:700;letter-spacing:.04em;padding:4px 16px;border-radius:8px;background:#1f2a3a;min-width:220px;text-align:center}
#state.IDLE{background:#1f2a3a}#state.LISTEN,#state.UNDERSTAND{background:#2c3f6b}#state.LOCATE,#state.CHECK{background:#2a4a6b}#state.PICK,#state.LIFT,#state.VERIFY,#state.SERVO,#state.APPROACH{background:#4a3b6b}#state.LOOK{background:#2a4a6b}
#state.HANDOVER{background:#2f5a3b}#state.RECOVER{background:#6b4a1e}#state.OFF,#state.BOOT{background:#3a3a3a}
.counter{margin-left:auto;text-align:right}.counter b{font-size:30px;color:var(--ok)}.counter span{color:var(--dim);font-size:12px;display:block}
main{display:grid;grid-template-columns:minmax(320px,660px) 1fr;gap:16px;padding:16px}@media(max-width:900px){main{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.panel h2{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}
#frame{width:100%;border-radius:6px;background:#000;aspect-ratio:4/3}#flabel{color:var(--dim);font-size:13px;margin-top:6px;min-height:18px}
.qa .q{color:var(--dim)}.qa .a{font-size:26px;font-weight:600;margin:4px 0}.ms{font-variant-numeric:tabular-nums;color:var(--fg)}
.tag{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;background:#2b3444;color:var(--fg)}
.tag.gemma{background:#2a3a7a;color:#dbe4ff}.tag.skill{background:#4b3a7a;color:#efe4ff}.tag.gate{background:#1f5a60;color:#dffcff}.tag.adv{background:#5a4a1f;color:#fff2c9}
.msg{font-size:18px;font-style:italic;color:#ffd8a8;min-height:24px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font-size:14px}.kv span:first-child{color:var(--dim)}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:3px 6px;text-align:left;border-bottom:1px solid var(--line)}th{color:var(--dim);font-weight:500}td.n{text-align:right;font-variant-numeric:tabular-nums}
pre{margin:0;white-space:pre-wrap;font:12px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;color:#c9d4e0}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;background:var(--dim)}.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}.dot.warn{background:var(--warn)}
#events li{list-style:none;padding:3px 0;border-bottom:1px solid var(--line);font-size:13px}#events{margin:0;padding:0;max-height:260px;overflow:auto}
#events .st{color:var(--dim);display:inline-block;min-width:88px}#events .an{font-weight:600}
#age{color:var(--bad);font-size:13px;display:none}
</style></head><body>
<header><div><h1>Unitree G1 &middot; Gemma 4 E2B on the Jetson</h1><div class="sub">"Any language, one can" &middot; every decision shown with its latency and provenance &middot; nothing leaves the robot</div></div>
<div id="state" class="BOOT">&mdash;</div><div id="age">brain not updating</div>
<div class="counter"><b id="auto">0</b><span>autonomous orders completed</span></div></header>
<main>
<div class="col">
 <div class="panel"><h2>Head camera</h2><img id="frame" alt="head camera"><div id="flabel"></div></div>
 <div class="panel" style="margin-top:16px"><h2>Decisions this order</h2><ul id="events"></ul></div>
</div>
<div class="col">
 <div class="panel qa"><h2>Last question</h2><div class="q" id="q">&mdash;</div><div class="a" id="a">&mdash;</div>
  <div><span class="ms" id="ms"></span> &nbsp; <span class="tag" id="tag">&mdash;</span> &nbsp; <span class="q" id="kind"></span></div>
  <div class="msg" id="msg"></div></div>
 <div class="grid2" style="margin-top:16px">
  <div class="panel"><h2>Order</h2><div class="kv"><span>order</span><b id="order">0</b><span>colour</span><b id="colour">&mdash;</b><span>result</span><b id="result">&mdash;</b><span>honest negatives</span><b id="neg">0</b><span>assisted</span><b id="assisted">0</b><span>failed</span><b id="failed">0</b><span>grasps / misses</span><b id="gm">0 / 0</b></div></div>
  <div class="panel"><h2>Stage times</h2><table id="stages"><tr><th>stage</th><th>ms</th></tr></table></div>
 </div>
 <div class="grid2" style="margin-top:16px">
  <div class="panel"><h2>No cloud</h2><div id="ncsum"></div><pre id="nc"></pre></div>
  <div class="panel"><h2>Preflight</h2><div id="pfsum"></div><pre id="pf"></pre></div>
 </div>
</div></main>
<script>
const $=id=>document.getElementById(id);let fv=-1,lastT=0;
function tagClass(t){t=(t||'').toLowerCase();return t.includes('advisory')?'adv':t.includes('gemma')?'gemma':t.includes('gate')?'gate':'skill'}
function render(d){const s=d.status||{};lastT=s.t||0;
 $('state').textContent=s.state||'—';$('state').className=s.state||'';$('auto').textContent=(s.counters||{}).autonomous||0;
 const c=s.counters||{};$('order').textContent=s.order||0;$('colour').textContent=s.colour||'—';$('result').textContent=s.last_result||'—';
 $('neg').textContent=c.honest_negatives||0;$('assisted').textContent=c.assisted||0;$('failed').textContent=c.failed||0;$('gm').textContent=(c.grasps||0)+' / '+(c.misses||0);
 const l=s.last;if(l){$('q').textContent=l.question||'';$('a').textContent=l.answer||'(empty)';$('ms').textContent=l.ms?l.ms+' ms':'';$('tag').textContent=l.tag||'';$('tag').className='tag '+tagClass(l.tag);$('kind').textContent=(l.stage||'')+' · '+(l.kind||'')+(l.prompt_n?' · '+l.prompt_n+' prompt tok, '+(l.predicted_n||0)+' out':'')}
 $('msg').textContent=s.message?'“'+s.message+'”':'';
 if(d.frame_v!==fv){fv=d.frame_v;$('frame').src='/frame.jpg?v='+fv}$('flabel').textContent=s.frame_label||'';
 const st=$('stages');st.innerHTML='<tr><th>stage</th><th>ms</th></tr>'+(s.stages||[]).map(x=>'<tr><td>'+x.stage+'</td><td class="n">'+x.ms+'</td></tr>').join('');
 $('events').innerHTML=(s.events||[]).slice().reverse().map(e=>'<li><span class="st">'+(e.stage||'')+'</span><span class="tag '+tagClass(e.tag)+'">'+(e.tag||'')+'</span> '+(e.question||'').slice(0,70)+' → <span class="an">'+(e.answer||'')+'</span> <span class="ms">'+(e.ms||0)+' ms</span></li>').join('');
 const n=d.nocloud||{};if(n.t){$('ncsum').innerHTML='<span class="dot '+(n.ok?'ok':'bad')+'"></span>'+(n.ok?'no default route, Wi-Fi off, Tailscale stopped':'default route: '+(n.default_route?'YES':'no')+' · Wi-Fi '+n.wifi+' · tailscaled '+n.tailscaled);
  $('nc').textContent='$ ip route\n'+n.ip_route+'\n$ nmcli radio status\n'+n.nmcli+'\n$ systemctl is-active tailscaled\n'+n.tailscaled+'\n$ ip -br addr\n'+n.addr}
 const p=d.preflight;if(p){$('pfsum').innerHTML='<span class="dot '+(p.ok?'ok':'bad')+'"></span>'+(p.ok?'PASS':'FAIL')+' at '+p.when+(p.venue?' (venue mode)':'');$('pf').textContent=(p.checks||[]).map(c=>c.name.padEnd(17)+c.status.padEnd(5)+' '+c.detail).join('\n')}}
const es=new EventSource('/events');es.onmessage=e=>render(JSON.parse(e.data));
setInterval(()=>{$('age').style.display=(lastT&&Date.now()/1000-lastT>20)?'block':'none'},2000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, ctype, body, extra=None):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def snapshot(self):
        return {"status": read_json(os.path.join(A.live, "status.json")) or {}, "frame_v": mtime(os.path.join(A.live, "frame.jpg")),
                "nocloud": NOCLOUD, "preflight": read_json(os.path.join(A.live, "preflight.json")), "t": time.time()}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/": return self._send(200, "text/html; charset=utf-8", PAGE.encode())
        if path == "/status.json": return self._send(200, "application/json", json.dumps(self.snapshot()).encode())
        if path == "/nocloud": return self._send(200, "application/json", json.dumps(NOCLOUD).encode())
        if path == "/frame.jpg":
            try:
                with open(os.path.join(A.live, "frame.jpg"), "rb") as f: return self._send(200, "image/jpeg", f.read())
            except OSError: return self._send(404, "text/plain", b"no frame yet")
        if path == "/events": return self.sse()
        self._send(404, "text/plain", b"not found")

    def sse(self):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.send_header("Connection", "keep-alive"); self.end_headers()
        last = None; ping = time.time()
        try:
            while True:
                snap = self.snapshot(); key = (mtime(os.path.join(A.live, "status.json")), snap["frame_v"], NOCLOUD["t"], mtime(os.path.join(A.live, "preflight.json")))
                if key != last:
                    self.wfile.write(("data: " + json.dumps(snap) + "\n\n").encode()); self.wfile.flush(); last = key; ping = time.time()
                elif time.time() - ping > 10:
                    self.wfile.write(b": ping\n\n"); self.wfile.flush(); ping = time.time()
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError, OSError): return


def main():
    os.makedirs(A.live, exist_ok=True)
    threading.Thread(target=nocloud_loop, daemon=True).start()
    srv = ThreadingHTTPServer((A.host, A.port), H); srv.daemon_threads = True
    print("brain view on http://%s:%d/ (live dir %s)" % (A.host, A.port, A.live), flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
