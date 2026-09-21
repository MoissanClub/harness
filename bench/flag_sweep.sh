#!/bin/sh
# Restart the server under each flag set and time a fixed set of finalist variants (latency A/B).
# Usage: bench/flag_sweep.sh [image-limit]; results land in experiments/*-latency-flags-<tag>/.
set -eu
cd "$(dirname "$0")/.."
LIMIT="${1:-40}"
VARIANTS="codex-off,where-grammar-off-480x336,face-tool-480x336,box-prefill-480x336"
BASE="-np 1 --cache-ram 0"
MTP="--spec-type draft-mtp"

sweep() {
  tag="$1"; shift
  bench/serve.sh "$tag" "$@"
  python3 -B bench/run_bench.py --tag "flags-$tag" --limit "$LIMIT" --variants "${SWEEP_VARIANTS:-$VARIANTS}"
}

sweep user-default $MTP --spec-draft-n-max 2
sweep np1-mtp2 $BASE $MTP --spec-draft-n-max 2
sweep np1-nomtp $BASE
sweep np1-mtp1 $BASE $MTP --spec-draft-n-max 1
sweep np1-mtp3 $BASE $MTP --spec-draft-n-max 3
sweep np1-mtp4 $BASE $MTP --spec-draft-n-max 4
sweep np1-mtp2-c4096 $BASE $MTP --spec-draft-n-max 2 -c 4096
sweep np1-mtp2-c4096-swafull $BASE $MTP --spec-draft-n-max 2 -c 4096 --swa-full
sweep np1-mtp2-c4096-nockpt $BASE $MTP --spec-draft-n-max 2 -c 4096 --ctx-checkpoints 0
sweep np1-mtp2-prio $BASE $MTP --spec-draft-n-max 2 -c 4096 --prio 2 --poll 100
SWEEP_VARIANTS="where-grammar-off-384x240,face-tool-384x240,box-prefill-384x240" \
  sweep np1-mtp2-img40 $BASE $MTP --spec-draft-n-max 2 -c 4096 --image-min-tokens 40
