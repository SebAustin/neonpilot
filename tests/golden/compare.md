# neonpilot compare: Apple M1 Max vs. Apple M5

A: `smollm2-135m-instruct-q4_k_m` on Apple M1 Max | B: `smollm2-135m-instruct-q4_k_m` on Apple M5

## Chip feature comparison

| Feature | Apple M1 Max | Apple M5 | Differs |
|---|---|---|---|
| bf16 | False | True | yes |
| dotprod | True | True |  |
| fp16 | True | True |  |
| i8mm | False | True | yes |
| neon | True | True |  |
| sme | False | True | yes |
| sme2 | False | True | yes |
| sve | False | False |  |
| sve2 | False | False |  |

## Throughput

### Apple M1 Max

| Metric | Baseline | Tuned | Speedup |
|---|---|---|---|
| Generation t/s | 40.00 | 60.00 | +50.0% |
| Prefill t/s | 100.00 | 180.00 | +80.0% |

Winning config: threads=10, cache_type=q4_0/q4_0, flash_attn=on, batch/ubatch=4096/2048

### Apple M5

| Metric | Baseline | Tuned | Speedup |
|---|---|---|---|
| Generation t/s | 80.00 | 136.00 | +70.0% |
| Prefill t/s | 200.00 | 360.00 | +80.0% |

Winning config: threads=14, cache_type=q8_0/q8_0, flash_attn=on, batch/ubatch=4096/2048

## Winning config diff

| Field | A | B | Differs |
|---|---|---|---|
| threads | 10 | 14 | yes |
| cache_type_k | q4_0 | q8_0 | yes |
| cache_type_v | q4_0 | q8_0 | yes |
| flash_attn | on | on |  |
| batch | 4096 | 4096 |  |
| ubatch | 2048 | 2048 |  |
