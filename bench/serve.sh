#!/bin/sh
# Restart the benchmark llama server on port 8080 with extra flags, then wait until healthy.
# Usage: bench/serve.sh TAG [extra llama serve flags...]
# Only the process listening on port 8080 is stopped; other llama instances are left alone.
set -eu
TAG="$1"; shift
LOG_DIR="${BENCH_LOG_DIR:-/tmp/harness-bench-logs}"
MODEL="${BENCH_MODEL:--hf unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL --alias gemma4-e2b}"
mkdir -p "$LOG_DIR"
PID=$(lsof -nP -tiTCP:8080 -sTCP:LISTEN || true)
if [ -n "$PID" ]; then
  kill $PID
  tries=0
  while lsof -nP -tiTCP:8080 -sTCP:LISTEN >/dev/null; do
    tries=$((tries + 1)); [ "$tries" -gt 150 ] && { echo "port 8080 still busy" >&2; exit 1; }
    sleep 0.2
  done
fi
# shellcheck disable=SC2086
nohup llama serve $MODEL --gpu-layers all --jinja --offline --log-timestamps \
  --log-file "$LOG_DIR/server-$TAG.log" "$@" >"$LOG_DIR/server-$TAG.stdout" 2>&1 &
SERVER=$!
echo "$TAG: llama serve $MODEL --gpu-layers all --jinja $*" >>"$LOG_DIR/launches.txt"
echo "$TAG: llama serve $MODEL --gpu-layers all --jinja $*" >"$LOG_DIR/current-launch.txt"  # read by run_bench.py
tries=0
until curl -sf -m 2 http://127.0.0.1:8080/health >/dev/null; do
  kill -0 "$SERVER" 2>/dev/null || { echo "server exited; see $LOG_DIR/server-$TAG.stdout" >&2; exit 1; }
  tries=$((tries + 1)); [ "$tries" -gt 400 ] && { echo "server not healthy after 120 s" >&2; exit 1; }
  sleep 0.3
done
echo "ready: $TAG (pid $(lsof -nP -tiTCP:8080 -sTCP:LISTEN)) flags: $*"
