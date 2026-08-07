# neonpilot report: Apple M5 Pro / qwen2.5-3b-instruct-q4_k_m

Model file: `qwen2.5-3b-instruct-q4_k_m.gguf`  |  llama.cpp commit: `178a6c44937154dc4c4eff0d166f4a044c4fceba`  |  schema: `1.0.0`

## Chip ISA features

| Feature | Present |
|---|---|
| bf16 | True |
| dotprod | True |
| fp16 | True |
| i8mm | True |
| neon | True |
| sme | True |
| sme2 | True |
| sve | False |
| sve2 | False |

## llama.cpp fast-path activation

| Feature | Kernel | Active | Why |
|---|---|---|---|
| neon | NEON generic dot-product kernel (CPU_REPACK, no KleidiAI micro-kernel) | False | NEON present but superseded by a higher KleidiAI tier (dotprod/i8mm/sme2). |
| dotprod | KleidiAI DOTPROD q4/q8 GEMM | False | dotprod present but superseded by a higher-tier kernel (i8mm/sme2). |
| i8mm | KleidiAI I8MM q4/q8 GEMM | False | i8mm present but superseded by SME2, the higher-tier kernel on this chip. |
| sme | SME (non-SME2) kernel | True | SME present -> SME kernels available (tier below SME2 if SME2 absent). |
| sme2 | SME2 kernel (M5) | True | SME2 present -> SME-tier KleidiAI kernels engage for q4/q8 GEMM (Apple M5+). |

## Baseline vs. tuned

| Metric | Baseline | Tuned | Speedup |
|---|---|---|---|
| Generation t/s | 61.57 +/- 0.38 t/s | 61.57 +/- 0.38 t/s | +0.0% |
| Prefill t/s | 178.70 +/- 3.11 t/s | 178.70 +/- 3.11 t/s | +0.0% |

## Methodology

- Repetitions per config: 5 (`-r 5`), prompt_n=512, gen_n=128
- Wall-clock budget: 1500s; actual elapsed: 437.9s
- Trials: 7 measured, 8 pruned (early-stop or budget), 0 errored
- llama.cpp commit: `178a6c44937154dc4c4eff0d166f4a044c4fceba`
- Winning config: defaults (as resolved by llama-bench; tuning did not beat the baseline)
- Measurement conditions: loadavg(1m/5m/15m)=1.07/1.48/1.76, top process: /System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer (6.5% CPU)
- **Statistical caution:** the measured generation speedup does not clear the dominance margin used for early-stopping -- baseline and tuned throughput confidence bands overlap (k=1.0, PLAN.md section 4.3). Treat the headline percentage as noisy, not proven; consider re-running with more repetitions (`--reps`) or on a quieter machine before trusting it.

## All trials

| Trial | Stage | Status | Threads | KV | FA | Gen t/s | Prefill t/s |
|---|---|---|---|---|---|---|---|
| A1 | A | ok | 3 | f16 | auto | 50.55 | 123.39 |
| A2 | A | pruned | 5 | f16 | auto | - | - |
| A3 | A | pruned | 14 | f16 | auto | - | - |
| A4 | A | pruned | 15 | f16 | auto | - | - |
| B1 | B | ok | 3 | f16 | off | 48.17 | 115.95 |
| B2 | B | pruned | 3 | q8_0 | off | - | - |
| B3 | B | pruned | 3 | q4_0 | off | - | - |
| B4 | B | pruned | 3 | f16 | on | - | - |
| B5 | B | pruned | 3 | q8_0 | on | - | - |
| B6 | B | pruned | 3 | q4_0 | on | - | - |
| C1 | C | ok | 3 | f16 | off | 47.80 | 114.30 |
| C2 | C | ok | 3 | f16 | off | 47.62 | 114.42 |
| C3 | C | ok | 3 | f16 | off | 46.44 | 113.63 |
| confirm-baseline | confirm | ok | 5 | f16 | auto | 61.57 | 178.70 |
| confirm-best | confirm | ok | 3 | f16 | off | 46.94 | 113.11 |
