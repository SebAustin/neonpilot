# neonpilot report: Apple M1 Max / smollm2-135m-instruct-q4_k_m

Model file: `SmolLM2-135M-Instruct-Q4_K_M.gguf`  |  llama.cpp commit: `178a6c44937154dc4c4eff0d166f4a044c4fceba`  |  schema: `1.0.0`

## Chip ISA features

| Feature | Present |
|---|---|
| neon | True |
| dotprod | True |
| i8mm | False |
| bf16 | False |
| fp16 | True |
| sme | False |
| sme2 | False |
| sve | False |
| sve2 | False |

## llama.cpp fast-path activation

| Feature | Kernel | Active | Why |
|---|---|---|---|
| neon | NEON generic dot-product kernel (CPU_REPACK, no KleidiAI micro-kernel) | False | NEON present but superseded by a higher KleidiAI tier (dotprod/i8mm/sme2). |
| dotprod | KleidiAI DOTPROD q4/q8 GEMM | True | i8mm ABSENT -> DOTPROD-tier KleidiAI kernels engaged; SME disabled; other quant types via CPU_REPACK q6_K_8x4. |
| i8mm | KleidiAI I8MM q4/q8 GEMM | False | i8mm ABSENT -> falls back to a lower KleidiAI tier (dotprod) or CPU_REPACK. |
| sme | SME (non-SME2) kernel | False | SME absent -> no SME-family kernels available on this chip. |
| sme2 | SME2 kernel (M5) | False | SME2 absent -> SME-tier KleidiAI kernels do not engage on this chip. |

## Baseline vs. tuned

| Metric | Baseline | Tuned | Speedup |
|---|---|---|---|
| Generation t/s | 40.00 +/- 1.00 t/s | 60.00 +/- 1.00 t/s | +50.0% |
| Prefill t/s | 100.00 +/- 1.00 t/s | 180.00 +/- 1.00 t/s | +80.0% |

## Methodology

- Repetitions per config: 2 (`-r 2`), prompt_n=64, gen_n=32
- Wall-clock budget: 180s; actual elapsed: 42.5s
- Trials: 3 measured, 1 pruned (early-stop or budget), 0 errored
- llama.cpp commit: `178a6c44937154dc4c4eff0d166f4a044c4fceba`
- Winning config: threads=10, cache_type=q4_0/q4_0, flash_attn=on, batch/ubatch=4096/2048

## All trials

| Trial | Stage | Status | Threads | KV | FA | Gen t/s | Prefill t/s |
|---|---|---|---|---|---|---|---|
| A1 | A | ok | 6 | f16 | auto | 45.00 | 100.00 |
| A2 | A | pruned | 8 | f16 | auto | - | - |
| confirm-baseline | confirm | ok | 8 | f16 | auto | 40.00 | 100.00 |
| confirm-best | confirm | ok | 10 | q4_0 | on | 60.00 | 180.00 |
