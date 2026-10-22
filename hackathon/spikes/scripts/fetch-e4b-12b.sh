#!/bin/bash
# Fetch Gemma 4 E4B and 12B (Google QAT q4_0 GGUF) plus the 12B MTP head. Resumable.
cd ~/models/gemma4
get() { curl -L -C - -s --retry 5 -o "$2" "https://huggingface.co/$1/resolve/main/$2"; echo "$(date +%T) $2 exit $?"; }
get google/gemma-4-12B-it-qat-q4_0-gguf mmproj-gemma-4-12b-it-qat-q4_0.gguf
get unsloth/gemma-4-12B-it-qat-GGUF mtp-gemma-4-12B-it.gguf
get google/gemma-4-E4B-it-qat-q4_0-gguf gemma-4-E4B-it-mmproj.gguf
get google/gemma-4-E4B-it-qat-q4_0-gguf gemma-4-E4B_q4_0-it.gguf
get google/gemma-4-12B-it-qat-q4_0-gguf gemma-4-12b-it-qat-q4_0.gguf
ls -la; echo FETCH_DONE
