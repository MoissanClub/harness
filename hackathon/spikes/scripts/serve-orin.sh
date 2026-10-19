#!/bin/bash
# Start llama-server on PC2 with the harness flags. Usage: ~/spike/serve-orin.sh [extra llama-server flags]
R=$HOME/cuda-user/root/usr/local/cuda-12.6
export LD_LIBRARY_PATH=$R/lib64:/usr/local/cuda-12.6/lib64:${LD_LIBRARY_PATH:-}
M=$HOME/models/gemma4
pkill -x llama-server 2>/dev/null; sleep 1
LAUNCH="$HOME/llama.cpp/build/bin/llama-server -m $M/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf --mmproj $M/mmproj-BF16.gguf --alias gemma4-e2b --host 127.0.0.1 --port 8080 -ngl 99 --jinja -np 1 -c 4096 --swa-full --cache-ram 0 $*"
echo "$LAUNCH" > $HOME/harness/bench/server-launch.txt
nohup $LAUNCH > $HOME/spike/server.log 2>&1 < /dev/null &
echo "server pid $!"
for i in $(seq 1 120); do
  if curl -s http://127.0.0.1:8080/health | grep -q '"ok"'; then echo "server healthy after ${i}s"; exit 0; fi
  sleep 1
done
echo "server not healthy after 120s"; tail -20 $HOME/spike/server.log; exit 1
