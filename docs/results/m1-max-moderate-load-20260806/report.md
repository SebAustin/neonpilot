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
| Generation t/s | 13.24 +/- 1.85 t/s | 24.05 +/- 0.59 t/s | +81.6% |
| Prefill t/s | 182.51 +/- 0.49 t/s | 160.03 +/- 0.54 t/s | -12.3% |

## Methodology

- Repetitions per config: 3 (`-r 3`), prompt_n=512, gen_n=128
- Wall-clock budget: 900s; actual elapsed: 480.7s
- Trials: 8 measured, 7 pruned (early-stop or budget), 0 errored
- llama.cpp commit: `178a6c44937154dc4c4eff0d166f4a044c4fceba`
- Winning config: threads=6, cache_type=f16/f16, flash_attn=off, batch/ubatch=2048/512
- Measurement conditions: loadavg(1m/5m/15m)=3.78/4.23/3.73, top process: /Applications/Claude.app/Contents/Frameworks/Claude Helper (Renderer).app/Contents/MacOS/Claude Helper (Renderer) (55.3% CPU)

## All trials

| Trial | Stage | Status | Threads | KV | FA | Gen t/s | Prefill t/s |
|---|---|---|---|---|---|---|---|
| A1 | A | ok | 6 | f16 | auto | 26.81 | 159.44 |
| A2 | A | ok | 8 | f16 | auto | 14.08 | 193.12 |
| A3 | A | pruned | 9 | f16 | auto | - | - |
| A4 | A | pruned | 10 | f16 | auto | - | - |
| B1 | B | ok | 6 | f16 | off | 22.80 | 163.27 |
| B2 | B | pruned | 6 | q8_0 | off | - | - |
| B3 | B | pruned | 6 | q4_0 | off | - | - |
| B4 | B | pruned | 6 | f16 | on | - | - |
| B5 | B | pruned | 6 | q8_0 | on | - | - |
| B6 | B | pruned | 6 | q4_0 | on | - | - |
| C1 | C | ok | 6 | f16 | off | 22.80 | 165.35 |
| C2 | C | ok | 6 | f16 | off | 21.61 | 162.03 |
| C3 | C | ok | 6 | f16 | off | 23.17 | 162.37 |
| confirm-baseline | confirm | ok | 8 | f16 | auto | 13.24 | 182.51 |
| confirm-best | confirm | ok | 6 | f16 | off | 24.05 | 160.03 |
