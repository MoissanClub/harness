# Gemma 4 on G1 Orin NX

Research checkpoint: **2026-09-17**. Target: PC2, Orin NX 16 GB, reported JP6.2 / L4T 36.4.3. **PC2 deployment and performance remain unverified.**

## Recommendation

- Start with **llama.cpp CUDA**, Google's **Gemma 4 E4B IT QAT Q4_0**, and matching multimodal projector. Preserve the Mac baseline's model and API.
- Keep JP6.2 for the initial measurement. Evaluate MTP speculative decoding next; use TensorRT Edge-LLM as the main alternative runtime.
- Optimize **fresh observation → complete, valid action chunk**, not just tokens/s.
- Preserve [runner-defaults.json](runner-defaults.json) as the format/thinking source of truth. The harness uses brief thinking and omits final acknowledgements; do not trade away capability silently.

## Runtime and OS choices

| Stack | Evidence / benefit | Remaining qualification |
| --- | --- | --- |
| llama.cpp CUDA | Existing GGUF, vision, and native tool API; least integration work | Current build and full workload on PC2 |
| TensorRT Edge-LLM | Official Orin JP7.2 target; Gemma 4 vision, compiled engines, CUDA graphs, MTP | Engine conversion, INT4+MTP combination, Gemma tool parsing; no published E4B/NX comparison establishing a win |
| little-gemma | Gemma-specific CUDA engine; actual NX16GB benchmarks | Custom socket protocol; tool API adapter and numerical parity checks; internal precision changes |
| vLLM | NVIDIA documents E4B vision/tools on Orin JP6 | A suitable quantized checkpoint, total memory, single-request latency |

SGLang/server TensorRT-LLM Gemma support does not establish an E4B/NX16GB deployment. [NVIDIA runtime recipe][recipe] · [Edge supported models][models] · [Edge platform matrix][edge]

**JetPack 7.2.1 supports Orin**: Ubuntu 24.04, CUDA 13.2.1, TensorRT 10.16.2. Upgrade for stack compatibility, not an assumed speedup. The local [G1 JP7.2 guide](../unitree-jetpack/versions/7.2/README.md) covers L4T 39.2.0, not 39.2.1. Preserve rollback and qualify networking, cameras, hands, and robot services. [NVIDIA release][jp]

Edge-LLM supports FP16/INT8/INT4 engines on Orin, not FP8/FP4. Pin a verified release: 0.10.1 fixes an INT4 accuracy defect in 0.10.0. [Known issues][issues]

## Hardware versus software quantization

- Orin NX is **Ampere SM87**. NVIDIA explicitly lists native **INT4×INT4 → INT32** and INT8 Tensor Core operations; native FP4 is absent. There is no direct INT4×FP16 matrix instruction. [Hardware matrix][hardware]
- Q4_0 is a storage format: 32 weights occupy 16 packed bytes plus a 2-byte scale, or **4.5 bits/weight**. Reconstruction is `weight = scale * (nibble - 8)`. QAT changes training/weight values, not kernel dispatch.
- A CUDA kernel is a GPU function, not code restricted to "CUDA cores." Its instructions can use general-purpose integer/float units, Tensor Cores, and memory units.

Source audit: llama.cpp **`c77ae695c93a6092cd7edb36909de5e43710af25`**, ordinary dense Q4_0 CUDA operations:

| Work | Normal path on SM87 |
| --- | --- |
| Typical decode/small batch (≤8 columns in audited build) | Packed Q4 → unpacked byte lanes; dynamically quantized Q8 activations; integer `DP4A` dot products |
| Larger prefill batches | Packed Q4 → INT8 tiles; Q8 activations; INT8 Tensor Core matrix multiplication |
| Fallback | cuBLAS may dequantize to FP16 |

Scales/corrections produce floating-point results. Fast paths unpack locally in registers/shared memory, retaining compact weights in DRAM. Norms, activations, and reductions use non-tensor units too. Thresholds are implementation choices; Q4_K follows different rules. [Dispatch][dispatch] · [Dot product][dot] · [Tensor instruction][mma]

Compact weights save memory traffic regardless of arithmetic precision. Native INT4 needs compatible activations or additional decomposition work. CPU/cameras share DRAM bandwidth; peak TOPS does not predict decode speed.

## Memory and latency expectations

Google's files total **5.155 GB model + 0.992 GB mmproj**. Runtime also needs KV cache, activations, graph/workspace buffers, OS, and robot services. Do not infer RAM from "E4B." [Google files][google]

External NX16GB results, MAXN with pinned clocks:

| E4B QAT configuration | Reported decode tokens/s |
| --- | ---: |
| llama.cpp reference, plain | 18.7 |
| llama.cpp + MTP, prose / image description | 24.5 / 28.8 |
| little-gemma, plain / MTP image description | 20.7 / 31.5 |

These use **Unsloth QAT and older llama builds**. MTP gains depend on draft acceptance; long outputs do not predict short-call gains. [Methodology][bench]

**Illustrative calculation, not a PC2 prediction:** assume **15–20 tokens/s** and **1–3 s for fresh-image processing plus prefill** on a warm server:

| Generated tokens, including thinking | Estimated complete response |
| --- | --- |
| 20 | 2–5 s |
| 60 | 4–7 s |
| 300 | 16–23 s |

The image allowance is unverified and depends on image budget, history, power, and contention. JPEG reduces transport bytes, not vision-token work at identical processed dimensions.

## Deployment and optimization order

1. **Record the baseline:** model/projector hashes, llama commit, CUDA/JetPack versions, build flags, resolved server properties, power mode, and clocks. Build Release CUDA for `CMAKE_CUDA_ARCHITECTURES=87`; verify model and projector GPU placement.
2. **Control allocation:** start with one slot; size context from task requirements and measured RAM. Avoid swap-dependent operation; retain room for robot services.
3. **Verify existing optimizations:** CUDA graphs default on; Flash Attention defaults to auto. Check actual behavior. `GGML_CUDA_FORCE_MMQ` does not force single-token Tensor Core use. [Dispatch order][matmul]
4. **Run inexpensive A/B tests:** prefill microbatches 128/256/512; Flash Attention modes; supported power/clocks with thermal monitoring. Test KV quantization when context traffic/memory matters. No gain is guaranteed.
5. **Test MTP:** use the [matching Google QAT assistant][assistant] and compatible conversion; the main GGUF repository contains no assistant head. Measure acceptance, memory, correctness, and short-call latency.
6. **Profile:** idle GPU gaps suggest launch/synchronization work; high memory bandwidth suggests reuse/compression; low bandwidth and utilization suggest layout/parallelism. Neither idle Tensor Cores nor "bandwidth-bound" proves optimality.
7. **Investigate model-specific work removal:** little-gemma reports 1.75× faster own warm E4B prefill by skipping computations beyond final necessary KV writes. Cold first-chunk cost remains. Check applicability/upstream coverage before porting. Native INT4 kernels and crossover tuning remain research candidates. [Prefill evidence][prefill]

## Evaluation requirements

- Fix image-token budget, rendered prompt, sampling, thinking, context, and quantization. Record unavoidable differences rather than attributing them to the engine.
- Separate process startup, warm-server/fresh-frame requests, and exact-image cache reuse.
- Report vision/prefill time, first-token time, complete valid-call p50/p95, output/reasoning tokens, decode rate, peak shared RAM, temperature, clocks, and power.
- Include robot services and repeated operation long enough to expose throttling. Retain failed/truncated responses and test tool-result roundtrips.
- Use varied observations and realistic action chunks. The existing three-image study is a protocol diagnostic; see [AGENTS.md](AGENTS.md) and [TASK_CHUNK_PROPOSAL.md](TASK_CHUNK_PROPOSAL.md) for the autonomy goal and proposed evaluation.

## Jetson-PI-Edge: relevance and limits

[Jetson-PI-Edge][pi] targets π0/π0.5/GR00T action tensors: fixed-shape graph reuse, GPU intermediates, and combined denoising steps. Gemma tool calls have no denoising loop.

Its ~413 ms π0.5 result and 8.66× control-frequency gain concern different models, scheduling, and larger Orin hardware. Revisit for a future VLA controller; these do not establish E4B acceleration. [Paper][paper]

[recipe]: https://www.jetson-ai-lab.com/tutorials/gemma4-on-jetson/
[models]: https://github.com/NVIDIA/TensorRT-Edge-LLM/blob/main/docs/source/user_guide/getting_started/supported-models.md
[edge]: https://nvidia.github.io/TensorRT-Edge-LLM/user_guide/getting_started/support-matrix.html
[jp]: https://developer.nvidia.com/embedded/jetpack/downloads
[issues]: https://nvidia.github.io/TensorRT-Edge-LLM/user_guide/getting_started/limitations.html
[hardware]: https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/compute-capabilities.html
[dispatch]: https://github.com/ggml-org/llama.cpp/blob/c77ae695c93a6092cd7edb36909de5e43710af25/ggml/src/ggml-cuda/mmvq.cu#L356-L367
[matmul]: https://github.com/ggml-org/llama.cpp/blob/c77ae695c93a6092cd7edb36909de5e43710af25/ggml/src/ggml-cuda/ggml-cuda.cu#L1868-L1876
[dot]: https://github.com/ggml-org/llama.cpp/blob/c77ae695c93a6092cd7edb36909de5e43710af25/ggml/src/ggml-cuda/vecdotq.cuh#L102-L120
[mma]: https://github.com/ggml-org/llama.cpp/blob/c77ae695c93a6092cd7edb36909de5e43710af25/ggml/src/ggml-cuda/mma.cuh#L942-L949
[google]: https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/tree/main
[bench]: https://github.com/cortexist/little-gemma/blob/main/docs/benchmarks.md
[assistant]: https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-unquantized-assistant
[prefill]: https://github.com/cortexist/little-gemma/blob/main/docs/prefill-performance-journal.md
[pi]: https://github.com/PKU-SEC-Lab/Jetson-PI-Edge
[paper]: https://arxiv.org/html/2607.12659v1
