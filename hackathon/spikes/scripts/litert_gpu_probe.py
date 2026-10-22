"""Spoken-order probe for the LiteRT-LM GPU run plan (hackathon/briefs/2026-10-21-litert-gpu.md). One script, three engines, the same
clips, prompts, greedy decoding and scoring, so the only variable is the engine:
  --engine gpu    LiteRT-LM (litert-lm-api 0.18.0), text model on the GPU (WebGPU over Vulkan), audio and vision towers on the CPU
  --engine cpu    LiteRT-LM, everything on the CPU (--threads)
  --engine llama  llama-server at 127.0.0.1:8080 (serve-orin.sh), thinking off, greedy: the payloads of order_words.py and gemma.py
Sets: sunday = order_words.py's two-word answer over the six Sunday clips (2 rounds = the 12 Sunday requests);
      v2 = brain/gemma.py's hear_choice (spoken order + numbered can descriptions -> a number or none) over spikes/clips/v2 (14 clips).
Each request is a fresh conversation (what the brain does per order); clips rotate so no two consecutive requests share audio.
Writes one JSON line per request to --out, prints a summary line per set; --report FILE... applies the plan's gate to saved rows;
--selfcheck compares the prompts with order_words.py and gemma.py (Mac desk check). Stdlib only; litert_lm is imported for gpu/cpu.
Run with python -I (no imports from the script's directory)."""
import argparse, ast, base64, json, os, re, shutil, statistics, subprocess, sys, threading, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# --- prompts: copies of order_words.py (WORDS_*) and hackathon/brain/gemma.py (CHOOSE_*); --selfcheck proves they still match
WORDS_SYSTEM = ("You are a drinks host robot. A guest may ask for a can in any language. "
                "Answer with exactly two words: the can colour (red, green, blue, or none if no can was requested) "
                "and the language code the guest spoke (en, zh, es, or other).")
WORDS_Q = "What did the guest ask for?"
CHOOSE_SYSTEM = ("You are a drinks host robot. The cans on the table are numbered: {cans}. The guest says which can they want, in any "
                 "language; they may name its colour, brand, flavour, picture, size or position. Answer with the number of that can only, "
                 "or none if no listed can matches.")
CHOOSE_Q = "Which can does the guest want?"
SCENE = ["purple la croix", "silver chi sparkling", "black coffee"]  # mock_robot.py scene "three", left to right
CANS = "; ".join("%d: %s" % (i + 1, d) for i, d in enumerate(SCENE))
SETS = {
    "sunday": {"system": WORDS_SYSTEM, "q": WORDS_Q, "max_tokens": 6, "default_clips": "~/spike/clips",
               "expect": {"en_green": ("green", "en"), "en_red": ("red", "en"), "en_blue": ("blue", "en"),
                          "zh_green": ("green", "zh"), "es_red": ("red", "es"), "en_other": ("none", "en")}},
    "v2": {"system": CHOOSE_SYSTEM.format(cans=CANS), "q": CHOOSE_Q, "max_tokens": 4, "default_clips": str(HERE.parent / "clips" / "v2"),
           "expect": {"I_d_like_the_silver_one": 2, "a_coke_please": None, "black": 3, "blue": None, "coffee": 3, "give_me_the_chi": 2,
                      "je_voudrais_la_canette_argentee_Thomas": 2, "quiero_la_lata_morada_Monica": 1, "red": None, "silver": 2,
                      "the_La_Croix_please": 1, "the_purple_can": 1, "我要紫色的_Tingting": 1, "c922_owner_purple": 1}},
}
LLAMA_BASE = {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "chat_template_kwargs": {"enable_thinking": False}}
# --- the plan's pre-registered gate (hackathon/briefs/2026-10-21-litert-gpu.md, "The deciding number"), applied by --report
GATE = {"gpu": {"p50": 1.0, "max": 1.5}, "cpu": {"p50": 1.5, "max": 2.5}}
ACC_SLACK_CLIPS = 1  # LiteRT may miss at most one clip more than llama.cpp (same tag), per set: 1 clip x rounds requests


def score(set_name, stem, answer):
    """(ok, format_ok, parsed) for one answer, the same rules as order_words.py (sunday) and Gemma.hear_choice (v2)."""
    exp = SETS[set_name]["expect"][stem]
    if set_name == "sunday":
        w = (answer or "").strip().lower().replace(",", " ").split()
        fmt = len(w) >= 2 and w[0] in ("red", "green", "blue", "none") and w[1] in ("en", "zh", "es", "other")
        return (len(w) >= 2 and w[0] == exp[0] and w[1] == exp[1]), fmt, " ".join(w[:2])
    m = re.search(r"\d+", answer or ""); idx = int(m.group()) if m else None
    idx = idx if idx is not None and 1 <= idx <= len(SCENE) else None
    fmt = bool(re.fullmatch(r"\s*(\d+|none)\W*", (answer or "").lower()))
    return idx == exp, fmt, idx


def clips_for(set_name, folder):
    d = Path(os.path.expanduser(folder))
    have = {p.stem: p for p in d.glob("*.wav")}
    missing = [s for s in SETS[set_name]["expect"] if s not in have]
    if missing: sys.exit("set %s: missing clips in %s: %s" % (set_name, d, ", ".join(missing)))
    return [have[s] for s in SETS[set_name]["expect"]]


def meminfo():
    try:
        kv = dict(l.split(":", 1) for l in open("/proc/meminfo"))
        return int(kv["MemAvailable"].split()[0]) // 1024
    except OSError: return None


def self_hwm():
    try: return next(int(l.split()[1]) // 1024 for l in open("/proc/self/status") if l.startswith("VmHWM"))
    except (OSError, StopIteration): return None


def mapped_libs():
    """GPU-related shared libraries this process actually mapped (Linux): shows whether the prebuilt accelerator was picked up."""
    try: lines = open("/proc/self/maps").read().splitlines()
    except OSError: return None
    paths = {l.split()[-1] for l in lines if "/" in l.split()[-1]}
    return sorted(p for p in paths if re.search(r"LiteRt|litert-lm|dawn|vulkan|nvidia|tegra", os.path.basename(p), re.I))


class Tegra:
    """Samples tegrastats (GR3D_FREQ %, RAM MB) in the background, if it exists; gr3d(t0, t1) is the max GR3D % in a window."""
    def __init__(self):
        self.s, self.p = [], None
        if shutil.which("tegrastats"):
            def die_with_parent():   # Linux: SIGTERM to tegrastats when this process dies, so a crashed probe leaves no orphan
                import ctypes, signal
                ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
            try:   # started before the engine (and before any other thread), where preexec_fn is safe
                self.p = subprocess.Popen(["tegrastats", "--interval", "100"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                          preexec_fn=die_with_parent if sys.platform.startswith("linux") else None)
                threading.Thread(target=self._read, daemon=True).start()
            except (OSError, subprocess.SubprocessError) as e:   # no GR3D then: the gate prints FAIL for want of proof
                print("tegrastats not started:", e, flush=True); self.p = None

    def _read(self):
        for line in self.p.stdout:
            g = re.search(r"GR3D_FREQ (\d+)%", line); r = re.search(r"RAM (\d+)/(\d+)MB", line)
            self.s.append((time.monotonic(), int(g.group(1)) if g else None, int(r.group(1)) if r else None))

    def gr3d(self, t0, t1):
        v = [g for t, g, _ in self.s if t0 - 0.15 <= t <= t1 + 0.15 and g is not None]
        return max(v) if v else None

    def ram_max(self):
        v = [r for _, _, r in self.s if r is not None]
        return max(v) if v else None

    def close(self):
        if self.p: self.p.terminate()


class Llama:
    name = "llama"

    def __init__(self, a):
        self.base = a.llama_url
        self.load_s, self.info = 0.0, {"server": self.base}

    def ask(self, set_name, clip):
        S = SETS[set_name]
        audio = {"type": "input_audio", "input_audio": {"data": base64.b64encode(clip.read_bytes()).decode(), "format": "wav"}}
        payload = dict(LLAMA_BASE, max_tokens=S["max_tokens"], messages=[{"role": "system", "content": S["system"]},
                       {"role": "user", "content": [{"type": "text", "text": S["q"]}, audio]}])
        req = urllib.request.Request(self.base + "/chat/completions", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=60) as r: body = json.loads(r.read())
        dt = time.perf_counter() - t0
        tm = body.get("timings", {})
        return (body["choices"][0]["message"].get("content") or ""), dt, dt, {k: tm.get(k) for k in ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms", "cache_n")}

    def smoke(self):
        req = urllib.request.Request(self.base.rsplit("/v1", 1)[0] + "/health")
        with urllib.request.urlopen(req, timeout=5) as r: return r.read().decode()[:80]

    def close(self): pass


class LiteRT:
    def __init__(self, a):
        import importlib.metadata as md
        import litert_lm as L
        self.L, self.name = L, a.engine
        if a.verbose: L.set_min_log_severity(L.LogSeverity.INFO)
        so = Path(L.__file__).parent / "liblitert-lm.so"
        self.info = {"litert_lm_api": md.version("litert-lm-api"), "liblitert_lm_bytes": so.stat().st_size if so.exists() else None,
                     "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", ""), "model": a.model, "threads": a.threads,
                     "mem_avail_before_mb": meminfo()}
        main = L.Backend.GPU() if a.engine == "gpu" else L.Backend.CPU(thread_count=a.threads)
        cache = os.path.expanduser(a.cache); os.makedirs(cache, exist_ok=True)   # the engine refuses a missing cache dir (Mac desk run)
        self.info["cache_entries_before"] = len(os.listdir(cache))                # 0 = a cold load (shader and weight caches built now)
        t0 = time.perf_counter()
        self.engine = L.Engine(a.model, backend=main, audio_backend=L.Backend.CPU(thread_count=a.threads), vision_backend=L.Backend.CPU(),
                               max_num_tokens=2048, cache_dir=cache, enable_benchmark=True)
        self.load_s = time.perf_counter() - t0
        self.info.update(load_s=round(self.load_s, 2), mem_avail_after_load_mb=meminfo(), mapped=mapped_libs())
        self.nothink = L.ThinkingConfig(enable_thinking=False)
        self.greedy = L.SamplerConfig(top_k=1, temperature=0.0, seed=1)

    @staticmethod
    def text(msg):
        parts = getattr(msg, "contents", None)
        if parts is not None: return "".join(getattr(c, "text", "") for c in parts)
        c = msg.get("content") if isinstance(msg, dict) else msg
        return "".join(x.get("text", "") for x in c) if isinstance(c, list) else str(c)

    def _turn(self, system, content, max_tokens):
        L = self.L
        t0 = time.perf_counter()
        conv = self.engine.create_conversation(messages=[{"role": "system", "content": system}], thinking_config=self.nothink, sampler_config=self.greedy)
        t1 = time.perf_counter()
        try:
            msg = conv.send_message(content, max_output_tokens=max_tokens)
            t2 = time.perf_counter()
            try:
                b = conv.get_benchmark_info()
                bench = {"ttft_s": round(b.time_to_first_token_in_second, 3), "prefill_n": b.last_prefill_token_count,
                         "prefill_tps": round(b.last_prefill_tokens_per_second, 1), "decode_n": b.last_decode_token_count,
                         "decode_tps": round(b.last_decode_tokens_per_second, 1)}
            except Exception as e: bench = {"bench_error": str(e)[:120]}
        finally:
            conv.close()
        return self.text(msg), t2 - t0, t2 - t1, bench

    def ask(self, set_name, clip):
        S, L = SETS[set_name], self.L
        return self._turn(S["system"], L.Contents([L.Content.Text(S["q"]), L.Content.AudioFile(str(clip.resolve()))]), S["max_tokens"])

    def smoke(self):
        ans, dt, _, bench = self._turn("Reply with one word.", "Say meow.", 4)
        return "%r in %.2fs %s" % (ans, dt, bench)

    def close(self): self.engine.close()


def pct(v, q):
    v = sorted(v); return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def summarize(rows):
    tot = [r["total_s"] for r in rows]
    g = [r["gr3d_max"] for r in rows if r.get("gr3d_max") is not None]
    return {"n": len(rows), "correct": sum(r["ok"] for r in rows), "format_ok": sum(r["format_ok"] for r in rows),
            "p50": round(statistics.median(tot), 3), "p90": round(pct(tot, 0.9), 3), "max": round(max(tot), 3),
            "gr3d_median_of_max": statistics.median(g) if g else None}


def run(a):
    tegra = Tegra()   # first: no other thread exists yet, and GR3D is sampled through the engine load too
    eng = Llama(a) if a.engine == "llama" else LiteRT(a)
    out = Path(os.path.expanduser(a.out)); out.parent.mkdir(parents=True, exist_ok=True)
    print("engine %s ready in %.2fs %s" % (a.engine, eng.load_s, json.dumps(eng.info)), flush=True)
    print("smoke:", eng.smoke(), flush=True)
    if a.engine != "llama":   # the accelerator may load lazily, at the first turn rather than at engine creation
        eng.info["mapped_after_smoke"] = mapped_libs()
        print("mapped after smoke:", json.dumps(eng.info["mapped_after_smoke"]), flush=True)
    if a.smoke:
        eng.close(); tegra.close(); return
    sets = [s for s in a.sets.split(",") if s]
    for s in sets:
        clips = clips_for(s, getattr(a, "clips_" + s) or SETS[s]["default_clips"])
        eng.ask(s, clips[-1])  # warm-up, untimed, on the last clip; the first timed request uses a different clip
        rows = []
        for rnd in range(a.rounds):
            for c in clips:
                t0 = time.monotonic()
                try:
                    ans, total, send, extra = eng.ask(s, c); err = None
                except Exception as e:
                    ans, total, send, extra, err = "", float("nan"), float("nan"), {}, "%s: %s" % (type(e).__name__, str(e)[:200])
                ok, fmt, parsed = score(s, c.stem, ans)
                row = {"tag": a.tag, "engine": a.engine, "set": s, "round": rnd, "clip": c.name, "expect": SETS[s]["expect"][c.stem],
                       "answer": ans[:80], "parsed": parsed, "ok": bool(ok and not err), "format_ok": bool(fmt and not err),
                       "total_s": round(total, 3), "send_s": round(send, 3), "gr3d_max": tegra.gr3d(t0, time.monotonic()),
                       "error": err, **extra}
                rows.append(row)
                with out.open("a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print("  %-44s ok=%-5s %-14r total=%.3fs gr3d=%s %s" % (c.name, row["ok"], ans[:14], total, row["gr3d_max"], err or ""), flush=True)
        good = [r for r in rows if not r["error"]]
        sm = summarize(good) if good else {"n": 0}
        sm.update(errors=len(rows) - len(good), mem_avail_end_mb=meminfo(), self_hwm_mb=self_hwm(), tegra_ram_max_mb=tegra.ram_max())
        summ = {"tag": a.tag, "engine": a.engine, "set": s, "summary": sm, "info": eng.info}
        with out.open("a") as f: f.write(json.dumps(summ, ensure_ascii=False) + "\n")
        print("SUMMARY %s %s %s" % (a.engine, s, json.dumps(sm)), flush=True)
    if a.hold:
        input("HOLD: %s engine resident; run the other engine now, press Enter here to close " % a.engine)
    eng.close(); tegra.close()


def report(files):
    """The plan's gate over saved rows, per tag (one tag = one session's run; a rerun gets a new tag): LiteRT (gpu or cpu) against the
    llama.cpp rows with the same tag and set. A set passes only with every expected request answered (no errors, on either engine)."""
    rows = [json.loads(l) for f in files for l in open(os.path.expanduser(f)) if l.strip()]
    by = {}
    for r in rows:
        if "clip" in r: by.setdefault((r["tag"], r["engine"], r["set"]), []).append(r)

    def rounds(rs): return max(r["round"] for r in rs) + 1

    for k, rs in sorted(by.items()):
        good = [r for r in rs if not r.get("error")]
        print("%-16s %-6s %-7s errors %d %s" % (k + (len(rs) - len(good), json.dumps(summarize(good)) if good else "{}")))
    verdicts = {}
    for (tag, eng, s), rs in sorted(by.items()):
        if eng == "llama": continue
        vs = verdicts.setdefault((tag, eng), {})
        base = by.get((tag, "llama", s))
        if not base: print("GATE %s %s %s: FAIL | no llama.cpp rows with tag %s for this set" % (tag, eng, s, tag)); vs[s] = False; continue
        n_exp, R = len(SETS[s]["expect"]) * rounds(rs), rounds(rs)
        errs, berrs = sum(bool(r.get("error")) for r in rs), sum(bool(r.get("error")) for r in base)
        if errs or berrs or len(rs) != n_exp or len(base) != n_exp:
            print("GATE %s %s %s: FAIL | rows %d/%d with %d errors, llama rows %d/%d with %d errors: not a complete comparison" % (
                tag, eng, s, len(rs), n_exp, errs, len(base), n_exp, berrs)); vs[s] = False; continue
        sm, bm, g, slack = summarize(rs), summarize(base), GATE[eng], ACC_SLACK_CLIPS * R   # greedy: a clip's rounds agree, so slack is per clip
        acc_ok = sm["correct"] >= bm["correct"] - slack
        lat_ok = sm["p50"] <= g["p50"] and sm["max"] <= g["max"]
        gpu_ok = eng != "gpu" or (sm["gr3d_median_of_max"] or 0) >= 50              # no tegrastats reading = GPU use unproven = FAIL
        vs[s] = acc_ok and lat_ok and gpu_ok
        print("GATE %s %s %s: %s | correct %d/%d vs llama %d/%d (slack %d = %d clip x %d rounds), format %d/%d | p50 %.3f<=%.1f max %.3f<=%.1f | GR3D %s%s" % (
            tag, eng, s, "PASS" if vs[s] else "FAIL", sm["correct"], sm["n"], bm["correct"], bm["n"], slack, ACC_SLACK_CLIPS, R,
            sm["format_ok"], sm["n"], sm["p50"], g["p50"], sm["max"], g["max"], sm["gr3d_median_of_max"], "" if gpu_ok else " (GPU use unproven)"))
        per = {}
        for i, side in ((0, rs), (1, base)):
            for r in side: per.setdefault(r["clip"], [0, 0])[i] += r["ok"]
        diff = ["%s %s %d/%d vs llama %d/%d" % (c, eng, a, R, b, R) for c, (a, b) in sorted(per.items()) if a != b]
        print("  per-clip differences: " + ("; ".join(diff) if diff else "none"))
    for (tag, eng), sets in sorted(verdicts.items()):   # an engine passes only with both sets present and passing under one tag
        miss = [s for s in SETS if s not in sets]
        print("GATE %s %s: %s" % (tag, eng.upper(), "INCOMPLETE (missing %s)" % ",".join(miss) if miss else ("PASS" if all(sets.values()) else "FAIL")))


def selfcheck():
    """Desk check: the prompts here equal order_words.py's and gemma.py's, every expected clip exists, the scorer reads known answers."""
    def consts(p):
        out = {}
        for n in ast.parse(Path(p).read_text()).body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                try: out[n.targets[0].id] = ast.literal_eval(n.value)
                except (ValueError, TypeError, SyntaxError): pass
        return out
    ow, gm = consts(HERE / "order_words.py"), consts(HERE.parent.parent / "brain" / "gemma.py")
    checks = [("WORDS_SYSTEM == order_words.py", WORDS_SYSTEM == ow.get("WORDS_SYSTEM")),
              ("CHOOSE_SYSTEM == gemma.py", CHOOSE_SYSTEM == gm.get("CHOOSE_SYSTEM")), ("CHOOSE_Q == gemma.py", CHOOSE_Q == gm.get("CHOOSE_Q")),
              ("LLAMA_BASE == gemma.py BASE", LLAMA_BASE == gm.get("BASE")),
              ("v2 clips present", all((Path(SETS["v2"]["default_clips"]) / (s + ".wav")).exists() for s in SETS["v2"]["expect"])),
              ("score sunday 'green, zh'", score("sunday", "zh_green", "green, zh")[:2] == (True, True)),
              ("score sunday 'none en' on es_red is wrong", score("sunday", "es_red", "none en")[0] is False),
              ("score v2 '2' on silver", score("v2", "silver", "2")[:2] == (True, True)),
              ("score v2 'none' on red", score("v2", "red", "none")[:2] == (True, True)),
              ("score v2 '4' (out of range) on red counts as none", score("v2", "red", "4")[0] is True),
              ("score v2 'The purple one' on the_purple_can is wrong", score("v2", "the_purple_can", "The purple one")[:2] == (False, False))]
    for name, ok in checks: print("%-50s %s" % (name, "ok" if ok else "FAIL"))
    sys.exit(0 if all(ok for _, ok in checks) else 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--engine", choices=["gpu", "cpu", "llama"])
    ap.add_argument("--sets", default="sunday,v2")
    ap.add_argument("--clips-sunday"); ap.add_argument("--clips-v2")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--model", default=os.path.expanduser("~/litert/gemma-4-E2B-it.litertlm"))
    ap.add_argument("--cache", default="~/litert/cache")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--llama-url", default="http://127.0.0.1:8080/v1")
    ap.add_argument("--out", default="~/spike/litert_gpu/orders.jsonl")
    ap.add_argument("--tag", default="pc2")
    ap.add_argument("--smoke", action="store_true", help="load the engine, one text turn, exit")
    ap.add_argument("--hold", action="store_true", help="keep the engine resident after the runs until Enter")
    ap.add_argument("--verbose", action="store_true", help="LiteRT-LM INFO logs (the WebGPU adapter line)")
    ap.add_argument("--report", nargs="+", metavar="JSONL")
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    if a.selfcheck: selfcheck()
    elif a.report: report(a.report)
    elif a.engine: run(a)
    else: ap.error("--engine, --report or --selfcheck")
