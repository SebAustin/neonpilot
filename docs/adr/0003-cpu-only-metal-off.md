# ADR 0003 — CPU-only; Metal/GPU backends explicitly disabled at build time

## Context

`llama.cpp` on Apple Silicon can run inference on the CPU (NEON/KleidiAI kernels) or offload to
the GPU via Metal. neonpilot's entire premise is explaining and tuning *Arm CPU* inference —
thread placement across P/E cores, KV-cache quantization for CPU memory bandwidth, KleidiAI
kernel-tier activation (NEON/DOTPROD/I8MM/SME2). If the benchmarked binary could silently fall
back to or blend in GPU acceleration, every measurement and every ISA-probe narrative in the
report would become ambiguous — a speedup could come from Metal, not from the tuned CPU flags.

## Decision

Build the pinned `llama.cpp` commit with `-DGGML_METAL=OFF -DGGML_BLAS=OFF
-DGGML_CPU_KLEIDIAI=ON` (`scripts/fetch_llama.sh`), so Metal and BLAS backends are compiled out
entirely rather than merely left unselected at runtime, and KleidiAI's Arm CPU kernels are
compiled in. Every `optimize` measurement therefore runs exclusively on Arm CPU kernel paths.

## Consequences

- **Comparisons are apples-to-apples.** Baseline vs. tuned speedup, and the M1 Max vs. M5
  cross-generation story, both measure the same backend family (Arm CPU kernels) end to end — no
  risk of a GPU offload skewing one side of a comparison.
- **Aligns with the ISA-probe differentiator.** The whole value of `neonpilot probe`'s
  "which KleidiAI kernel tier engages" narrative depends on CPU kernels actually being the thing
  doing the work; a Metal-capable build would make that narrative partially fictional on Apple
  Silicon.
- **Matches the brief's stated scope.** `REQUIREMENTS.md`'s non-goals explicitly rule out a GPU/
  Metal backend — "this is the point of the project." Compiling it out at build time makes this
  a structural guarantee, not just a documented convention that a stray `-ngl` flag could violate
  at runtime.
- **Trade-off accepted.** Absolute throughput numbers are lower than a Metal-accelerated build
  would produce, and this is not directly comparable to GPU-based llama.cpp benchmarks published
  elsewhere. That is intentional — neonpilot is not claiming to be the fastest possible inference
  setup, only the best-tuned *CPU* configuration for a given Arm chip.
- **Rejected alternative:** leaving Metal compiled in but unused via runtime flags (`-ngl 0`) —
  rejected because it depends on every invocation remembering to pass the flag correctly, whereas
  compiling it out removes the failure mode entirely.
