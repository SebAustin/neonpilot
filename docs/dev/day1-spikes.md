# Day-1 verification spikes — results (2026-07-20, Apple M1 Max)

All `[probe-day1]` items from PLAN.md §0, now verified on the reference machine.

## S1 — sysctl ISA feature ground truth (M1 Max)

Raw capture: `tests/fixtures/sysctl_apple_m1_max.txt`. Key flags:

| Feature | sysctl key | Value |
|---|---|---|
| NEON / AdvSIMD | `hw.optional.arm.AdvSIMD` | **1** |
| DotProd | `hw.optional.arm.FEAT_DotProd` | **1** |
| FP16 | `hw.optional.arm.FEAT_FP16` | **1** |
| I8MM | `hw.optional.arm.FEAT_I8MM` | **0** |
| BF16 | `hw.optional.arm.FEAT_BF16` | **0** |
| SME | `hw.optional.arm.FEAT_SME` | **0** |
| SME2 | `hw.optional.arm.FEAT_SME2` | **0** |

Topology: `hw.perflevel0.physicalcpu=8` (Performance), `hw.perflevel1.physicalcpu=2`
(Efficiency), `hw.physicalcpu=10`, `hw.memsize` ≈ 64 GiB, cacheline 128 B.

## S2 — toolchain

- `cmake` installed via Homebrew (was absent). `clang` at `/usr/bin/clang`.
- llama.cpp pinned at release tag **`b10069`** (2026-07-20), shallow clone in `vendor/llama.cpp`.
- Build: `cmake -B build -DGGML_METAL=OFF -DGGML_BLAS=OFF -DGGML_CPU_KLEIDIAI=ON
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF
  -DCMAKE_BUILD_TYPE=Release`, target `llama-bench`. Builds clean.
  Note: `llama-cli` target does not exist with examples off — **not needed**; the tuner
  uses `llama-bench` only.

## S3 — KleidiAI engagement on M1 Max (the load-bearing probe-copy fact)

Verbose run (`llama-bench -v`, SmolLM2-135M Q4_K_M) shows:

```
kleidiai: primary q4 kernel feature DOTPROD
kleidiai: primary q8 kernel feature DOTPROD
kleidiai: no compatible f32 kernels found for CPU features mask 1
kleidiai: SME disabled
load_tensors:   CPU_Mapped model buffer size =    98.87 MiB
load_tensors: CPU_KLEIDIAI model buffer size =    30.26 MiB
load_tensors:   CPU_REPACK model buffer size =    17.28 MiB
repack: repack tensor blk.0.ffn_down.weight with q6_K_8x4
```

**Verified conclusion for probe copy:** on M1 Max (no i8mm/SME), KleidiAI *does*
engage, selecting DOTPROD-tier micro-kernels for q4/q8 weights; SME kernels are
disabled; remaining quant types go through ggml's generic CPU_REPACK (`q6_K_8x4`)
or plain CPU paths. On SME2-capable chips (Apple M5), the same log is expected to
select SME-tier kernels — to be captured during the M5 benchmark run.

## S4 — llama-bench JSON output shape (b10069)

Fields confirmed: `build_commit`, `cpu_info`, `n_batch`, `n_ubatch`, `n_threads`
(default **8** on M1 Max = P-core count), `type_k`/`type_v` (default `f16`),
`flash_attn` (**-1** = auto default), `n_prompt`, `n_gen`, `avg_ns`, `stddev_ns`,
`avg_ts`, `stddev_ts`, `samples_ns[]`, `samples_ts[]`. One JSON array entry per
(test × config). Logs are suppressed by default (stderr empty without `-v`).

## S5 — models

- CI/integration: `unsloth/SmolLM2-135M-Instruct-GGUF` → `SmolLM2-135M-Instruct-Q4_K_M.gguf` (101 MB) ✓ downloaded
- Real benchmark: `Qwen/Qwen2.5-3B-Instruct-GGUF` → `qwen2.5-3b-instruct-q4_k_m.gguf` (~2.1 GB) ✓ downloaded
- Cache location: `~/.neonpilot/models/`
