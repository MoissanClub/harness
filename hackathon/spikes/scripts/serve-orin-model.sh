#!/bin/bash
# Start llama-server on PC2 with the harness flags for one Gemma 4 size.
# Usage: ~/spike/serve-orin-model.sh e2b|e4b|12b [extra llama-server flags]   (serve-orin.sh stays the E2B demo launcher)
R=$HOME/cuda-user/root/usr/local/cuda-12.6
export LD_LIBRARY_PATH=$R/lib64:/usr/local/cuda-12.6/lib64:${LD_LIBRARY_PATH:-}
M=$HOME/models/gemma4
case "$1" in
  e2b) W=gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf; P=mmproj-BF16.gguf ;;
  e4b) W=gemma-4-E4B_q4_0-it.gguf; P=gemma-4-E4B-it-mmproj.gguf ;;
  12b) W=gemma-4-12b-it-qat-q4_0.gguf; P=mmproj-gemma-4-12b-it-qat-q4_0.gguf ;;
  *) echo "usage: $0 e2b|e4b|12b [flags]" >&2; exit 2 ;;
esac
SIZE=$1; shift
pkill -x llama-server 2>/dev/null; sleep 1
LAUNCH="$HOME/llama.cpp/build/bin/llama-server -m $M/$W --mmproj $M/$P --alias gemma4-$SIZE --host 127.0.0.1 --port 8080 -ngl 99 --jinja -np 1 -c 4096 --swa-full --cache-ram 0 $*"
mkdir -p /tmp/harness-bench-logs
echo "$LAUNCH" > /tmp/harness-bench-logs/current-launch.txt   # read by run_bench.py into manifest.json
nohup $LAUNCH > $HOME/spike/server-$SIZE.log 2>&1 < /dev/null &
echo "server pid $!"
for i in $(seq 1 180); do
  if curl -s http://127.0.0.1:8080/health | grep -q '"ok"'; then echo "server healthy after ${i}s"; exit 0; fi
  sleep 1
done
echo "server not healthy after 180s"; tail -20 $HOME/spike/server-$SIZE.log; exit 1
