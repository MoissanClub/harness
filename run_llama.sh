#!/bin/sh
# Single-client robot config; each flag is measured in LATENCY_RESULTS.md (M4 Pro, 2026-09-21).
#   -np 1 --cache-ram 0   one slot, no host prompt cache: deterministic prefix reuse, no hidden KV copies
#   -c 4096 --swa-full    full-size SWA cache at a small context: prefix reuse without checkpoints, -55 ms/request
#   no --spec-type        MTP drafting is slower than plain decode on this Mac (95 vs 113 tok/s); re-test on Orin NX
# Previous: llama serve -hf unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL --alias gemma4-e2b --gpu-layers all --jinja --spec-type draft-mtp --spec-draft-n-max 2
llama serve -hf unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL --alias gemma4-e2b --gpu-layers all --jinja -np 1 -c 4096 --swa-full --cache-ram 0
