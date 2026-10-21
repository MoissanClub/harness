"""Desk gate (DEV_WORKFLOW S1, under two minutes, no robot): compile every module, the geometry tests, the reach replay, calib
freshness, and one seeded mock order. Run: ~/miniforge3/envs/brain/bin/python -B check.py   (exit 1 on any failure)."""
import os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); PY = sys.executable; ok = True
def run(name, cmd, env=None, timeout=300):
    global ok
    t0 = time.time(); r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, **(env or {})))
    good = r.returncode == 0; ok = ok and good
    print("%-28s %s %.1fs" % (name, "ok " if good else "FAIL", time.time() - t0)); 
    if not good: print((r.stdout + r.stderr)[-3000:])
    return r
run("compile", [PY, "-B", "-m", "py_compile", "brain.py", "geom.py", "gemma.py", "motion.py", "calib.py", "mock_robot.py", "preflight.py", "brainview.py", "replay_reach.py", "test_geom.py"])
run("test_geom", [PY, "-B", "test_geom.py"])
run("replay_reach", [PY, "-B", "replay_reach.py"])
run("calib", [PY, "-B", "calib.py"])
# the mock's hand constant K (fingertip front, near face, median z relative to the perceived axis at the ALIGNED PRE-GRASP, scene mid, 2026-10-20)
r = run("mock order (hidden error)", [PY, "-B", "brain.py", "--mock", "--mock-gemma", "--no-preflight", "--orders", "1", "--pause", "0.3", "--release-after", "4", "--runs", "/tmp/brain-check-runs", "--accept-calib", "--K", "0.062", "-0.052", "-0.002"],
        env={"BRAIN_MOCK_SCENE": "mid", "BRAIN_MOCK_ORDERS": "silver", "BRAIN_MOCK_SLEEP": "0.1", "BRAIN_MOCK_ERR": "0.11", "BRAIN_MOCK_ERRK": "0.04"}, timeout=600)
if "RESULT order 1: success" not in r.stdout: ok = False; print("mock order did not succeed:\n" + r.stdout[-2500:])
print("CHECK:", "PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
