# Apple M5 Pro — idle-machine reference run (2026-08-07)

> **This is the clean, otherwise-idle-machine reference result** — the number SC2's "≥10%
> speedup" bar and SC3's preset policy are actually measured against, not another
> adaptive/loaded-machine case study. It is real, unmodified `neonpilot optimize` output;
> nothing here is fabricated or hand-adjusted. The honest outcome on this machine is **defaults
> already win — measured +0.0%, and no preset was packaged** — see "Why no preset was
> packaged" below for why that is the *correct* result, not a shortfall.

## What's here

- [`result.json`](./result.json) — the full `SweepResult` artifact (every trial, baseline,
  confirm pass, budget accounting, both load snapshots).
- [`chip.json`](./chip.json) — the `ChipReport` probe snapshot for this machine.
- [`plan.json`](./plan.json) / [`trials.json`](./trials.json) / [`run.log`](./run.log) — the
  staged-sweep plan, the per-trial array, and the live progress log.
- [`report.md`](./report.md) / [`report.html`](./report.html) — the `neonpilot report` output
  generated from this same run (open `report.html` directly in a browser; it's self-contained).

Copied verbatim from the real run directory — only these artifacts, per the run/preset-artifact
split documented in the main [README](../../../README.md#where-artifacts-land).

## Machine and run conditions

| | |
|---|---|
| Machine | Apple M5 Pro, 5 P-cores + 10 E-cores (15 total), 24 GB RAM, macOS/darwin arm64 |
| `llama.cpp` pin | tag `b10069` = SHA `178a6c44937154dc4c4eff0d166f4a044c4fceba` |
| Reference model | Qwen2.5-3B-Instruct Q4_K_M (~2.1 GB) — the same GGUF file used for both M1 Max case studies |
| Budget / reps | 1500s budget, 5 reps/config, `prompt_n=512`, `gen_n=128` |
| Outcome | Completed in full: `budget_truncated=false`, elapsed **437.9s** (well under the 1500s budget — the full-model 900s default budget wasn't even needed), 7 trials measured / 8 pruned / 0 errored |

## The receipts: load telemetry recorded by this run

Unlike the loaded/moderate-load M1 Max case studies, this run's own `SweepResult.load_before`/
`load_after` (feature F-A) show a genuinely quiet machine throughout, not just at the start:

| | `load_before` (sweep start) | `load_after` (sweep end) |
|---|---|---|
| `loadavg_1m` | **1.07** | **3.19** |
| `loadavg_5m` | 1.48 | 2.58 |
| `loadavg_15m` | 1.76 | 2.21 |
| Top process (`ps -Ao pcpu,comm -r`) | WindowServer — 6.5% CPU | Slack Helper (Renderer) — 4.4% CPU |

`loadavg_1m` rose from 1.07 to 3.19 over the course of the sweep — still well under the tuner's
own `--strict-idle` threshold (0.5× the 15-core total, i.e. 7.5) at both ends — and the top
process at either end is ordinary desktop background activity (WindowServer, Slack), not a
competing compute-heavy workload. This is the reference-grade environment the M1 Max case
studies explicitly said they were *not*.

## Chip ISA features

| Feature | Present |
|---|---|
| neon | True |
| dotprod | True |
| fp16 | True |
| i8mm | True |
| bf16 | True |
| sme | True |
| sme2 | True |
| sve | False |
| sve2 | False |

Every KleidiAI-relevant Arm Silicon feature — including `sme2`, absent on the M1 Max reference
machine — probes `True` here. See [`chip.json`](./chip.json) for the raw `sysctl` capture and
[`docs/results/m5-vs-m1-compare/`](../m5-vs-m1-compare/) for the side-by-side feature table
against the M1 Max.

## Results

| Metric | Baseline (`threads=5, fa=auto, kv=f16, b=2048/512` — llama.cpp defaults) | Tuned | Speedup |
|---|---|---|---|
| Generation t/s (avg ± stddev) | 61.57 ± 0.38 | 61.57 ± 0.38 | **+0.0%** |
| Prefill t/s (avg ± stddev) | 178.70 ± 3.11 | 178.70 ± 3.11 | **+0.0%** |

Winning config: **defaults**, as resolved by `llama-bench` itself — no tuned candidate the
staged sweep measured beat the baseline, so the confirm pass's own baseline re-measurement is
the reported "best." Both numbers are the confirm-pass measurement (baseline re-measured
back-to-back with the sweep's best-found tuned candidate, in the same thermal/scheduling
window), not a comparison across different points in the sweep.

## Interpretation: no tuned config beat the shipped defaults

On this idle, current-generation chip, `llama.cpp`'s own resolved defaults —
`threads=5` (this chip's own P-core count), `flash_attn=auto`, KV cache `f16`,
`batch/ubatch=2048/512` — are already the fastest measured configuration for both generation and
prefill. Every alternative the staged sweep actually measured (threads=3 with various
flash-attention/KV-cache/batching combinations) topped out at 46–51 gen t/s, well below the
defaults' 61.57 t/s. `neonpilot` reported this honestly: `speedup_gen_pct=0.0`,
`speedup_prefill_pct=0.0`, and the report's own methodology section prints a "statistical
caution" line rather than a headline percentage, since baseline and tuned are the same
measurement.

This is the honest reference-grade counterpart to the two M1 Max case studies: on a *loaded*
workstation, adaptive tuning wins big (+144.2% and +81.6% generation speedups, both receipted
with load telemetry); on an *idle*, modern chip, defaults are already optimal, and the tool's job
is to measure and say so — not to invent a win. Both outcomes are the same statistical-honesty
machinery working correctly under different ambient conditions.

## Cross-generation observation (see the full comparison for details)

Using the exact same GGUF file (Qwen2.5-3B-Instruct Q4_K_M), the M5 Pro's shipped defaults
(61.57 gen t/s) run **~2.6x** the M1 Max's best *tuned* result (24.05 gen t/s,
[`docs/results/m1-max-moderate-load-20260806/`](../m1-max-moderate-load-20260806/)) — even
though the M1 Max number is itself the winner of an adaptive tuning sweep, not its own defaults.
Both measurements are CPU-only (`-DGGML_METAL=OFF`) on the same pinned `llama.cpp` commit, so
this reflects real generational CPU throughput and kernel-tier improvement (SME2 vs. DOTPROD-tier
KleidiAI kernels — see the ISA table above), not a GPU/accelerator difference. See
[`docs/results/m5-vs-m1-compare/compare.md`](../m5-vs-m1-compare/compare.md) for the full
side-by-side.

## Why no preset was packaged

**No preset was packaged or committed from this run**, and this time it's not just policy — it's
enforced by the tool itself. The sweep's own `best` trial is the confirm-pass baseline
re-measurement, and `TrialResult.is_synthetic_config=true` on that trial (it's a *reconstruction*
of what `llama-bench` resolves to when no `-t/-ctk/-ctv/-fa` flags are passed, not a directly
measured/appliable flag set — see `docs/dev/build-notes.md` item 16, finding H3). `apply`'s
preset-packaging path refuses to package a synthetic-config `best` unconditionally, so running
`neonpilot apply --run-dir` against this run's artifacts would itself refuse, rather than
requiring a human to remember the policy. `presets/` stays empty for this chip until a future
sweep — on this machine or another with the same ISA profile — actually measures a config that
beats `llama.cpp`'s own defaults. See `CONTRIBUTING.md`'s "Contributing a preset for a new chip"
section for the general policy this follows.

## A known engineering wart surfaced by this run

Stages B and C of this sweep explored flash-attention/KV-cache/batch variants around
`threads=3` — an inferior thread count that the true baseline (`threads=5`, the defaults) already
dominates by more than 10 t/s — because the baseline itself isn't measured until the confirm
pass, so Stage A's winner-selection had nothing to compare its one measured candidate against.
The confirm pass caught this and the final verdict stayed honest (`+0.0%`, defaults win), but
real sweep time was spent exploring around the wrong thread count. Logged in full, with the
candidate fix, in [`docs/dev/build-notes.md`](../../dev/build-notes.md) (item 27).
