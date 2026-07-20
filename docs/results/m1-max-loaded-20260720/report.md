# neonpilot report: Apple M1 Max / qwen2.5-3b-instruct-q4_k_m

Model file: `qwen2.5-3b-instruct-q4_k_m.gguf`  |  llama.cpp commit: `178a6c44937154dc4c4eff0d166f4a044c4fceba`  |  schema: `1.0.0`

## Chip ISA features

| Feature | Present |
|---|---|
| bf16 | False |
| dotprod | True |
| fp16 | True |
| i8mm | False |
| neon | True |
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
| Generation t/s | 9.05 +/- 1.79 t/s | 22.11 +/- 1.04 t/s | +144.2% |
| Prefill t/s | 137.82 +/- 56.60 t/s | 168.03 +/- 2.18 t/s | +21.9% |

## Methodology

- Repetitions per config: 3 (`-r 3`), prompt_n=512, gen_n=128
- Wall-clock budget: 900s; actual elapsed: 543.9s
- Trials: 8 measured, 7 pruned (early-stop or budget), 0 errored
- llama.cpp commit: `178a6c44937154dc4c4eff0d166f4a044c4fceba`
- Winning config: threads=6, cache_type=f16/f16, flash_attn=off, batch/ubatch=4096/2048

## All trials

| Trial | Stage | Status | Threads | KV | FA | Gen t/s | Prefill t/s |
|---|---|---|---|---|---|---|---|
| A1 | A | ok | 6 | f16 | auto | 26.54 | 169.00 |
| A2 | A | ok | 8 | f16 | auto | 8.36 | 158.60 |
| A3 | A | pruned | 9 | f16 | auto | - | - |
| A4 | A | pruned | 10 | f16 | auto | - | - |
| B1 | B | ok | 6 | f16 | off | 19.53 | 170.60 |
| B2 | B | pruned | 6 | q8_0 | off | - | - |
| B3 | B | pruned | 6 | q4_0 | off | - | - |
| B4 | B | pruned | 6 | f16 | on | - | - |
| B5 | B | pruned | 6 | q8_0 | on | - | - |
| B6 | B | pruned | 6 | q4_0 | on | - | - |
| C1 | C | ok | 6 | f16 | off | 21.20 | 168.77 |
| C2 | C | ok | 6 | f16 | off | 22.83 | 168.73 |
| C3 | C | ok | 6 | f16 | off | 21.67 | 170.35 |
| confirm-baseline | confirm | ok | 8 | f16 | auto | 9.05 | 137.82 |
| confirm-best | confirm | ok | 6 | f16 | off | 22.11 | 168.03 |
