# neonpilot compare: Apple M5 Pro vs. Apple M1 Max

A: `qwen2.5-3b-instruct-q4_k_m` on Apple M5 Pro | B: `qwen2.5-3b-instruct-q4_k_m` on Apple M1 Max

## Chip feature comparison

| Feature | Apple M5 Pro | Apple M1 Max | Differs |
|---|---|---|---|
| bf16 | True | False | yes |
| dotprod | True | True |  |
| fp16 | True | True |  |
| i8mm | True | False | yes |
| neon | True | True |  |
| sme | True | False | yes |
| sme2 | True | False | yes |
| sve | False | False |  |
| sve2 | False | False |  |

## Throughput

### Apple M5 Pro

| Metric | Baseline | Tuned | Speedup |
|---|---|---|---|
| Generation t/s | 61.57 | 61.57 | +0.0% |
| Prefill t/s | 178.70 | 178.70 | +0.0% |

Winning config: defaults (as resolved by llama-bench; tuning did not beat the baseline)
Measurement conditions: loadavg(1m/5m/15m)=1.07/1.48/1.76, top process: /System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer (6.5% CPU)

### Apple M1 Max

| Metric | Baseline | Tuned | Speedup |
|---|---|---|---|
| Generation t/s | 13.24 | 24.05 | +81.6% |
| Prefill t/s | 182.51 | 160.03 | -12.3% |

Winning config: threads=6, cache_type=f16/f16, flash_attn=off, batch/ubatch=2048/512
Measurement conditions: loadavg(1m/5m/15m)=3.78/4.23/3.73, top process: /Applications/Claude.app/Contents/Frameworks/Claude Helper (Renderer).app/Contents/MacOS/Claude Helper (Renderer) (55.3% CPU)

## Winning config diff

| Field | A | B | Differs |
|---|---|---|---|
| threads | defaults (not measured) | 6 |  |
| cache_type_k | defaults (not measured) | f16 |  |
| cache_type_v | defaults (not measured) | f16 |  |
| flash_attn | defaults (not measured) | off |  |
| batch | defaults (not measured) | 2048 |  |
| ubatch | defaults (not measured) | 512 |  |
