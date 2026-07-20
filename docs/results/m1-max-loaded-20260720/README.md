# M1 Max case study — measured under ambient load (2026-07-20)

> **This is measured under ambient load; an adaptive result, not an idle-machine reference.**
> It is real, unmodified `neonpilot optimize` output — nothing here is fabricated or
> hand-adjusted — but the machine was busy with unrelated work while the sweep ran, so the
> headline numbers reflect the tuner adapting to *that* machine state, not a clean-room
> best case. See [README.md's "Idle-machine reference" section](../../../README.md#results)
> for the still-open idle-machine measurement this is not a substitute for.

## What's here

- [`result.json`](./result.json) — the full `SweepResult` artifact (every trial, baseline,
  confirm pass, budget accounting) from the real run.
- [`report.md`](./report.md) / [`report.html`](./report.html) — the `neonpilot report` output
  generated from that same run (open `report.html` directly in a browser; it's self-contained).

Copied verbatim from `~/.neonpilot/runs/20260720T170908Z/` (the run directory itself is not
committed — only these three artifacts, per the run/preset-artifact split documented in the
main README).

## Machine and run conditions

| | |
|---|---|
| Machine | Apple M1 Max, 64 GB RAM, macOS 26.5 |
| `llama.cpp` pin | tag `b10069` = SHA `178a6c44937154dc4c4eff0d166f4a044c4fceba` |
| Reference model | Qwen2.5-3B-Instruct Q4_K_M (~2.1 GB) |
| Budget / reps | 900s budget, 3 reps/config, `prompt_n=512`, `gen_n=128` (full-model defaults) |
| Outcome | Completed in full: `budget_truncated=false`, 543.9s elapsed, 8 trials measured / 7 pruned / 0 errored |
| **Ambient load during the sweep** | Docker Desktop ~54% CPU, a VM ~19% CPU, Webex, and WindowServer all running concurrently; `loadavg` **7.6–12.2** on this 10-core machine (i.e. often *over*-subscribed) |

## Results

| Metric | Baseline (`threads=8`, llama.cpp defaults) | Tuned (`threads=6, fa=off, kv=f16, b=4096/2048`) | Speedup |
|---|---|---|---|
| Generation t/s (median ± stddev) | 9.05 ± 1.79 | 22.11 ± 1.04 | +144.2% |
| Prefill t/s (median ± stddev) | 137.8 ± 56.6 | 168.0 ± 2.2 | +21.9% |

Both numbers are the confirm-pass measurement (baseline and winner re-measured back-to-back in
the same thermal/scheduling window, per the project's baseline-fairness methodology) — not a
comparison across different points in the sweep.

## Interpretation (verified against the per-trial samples in `result.json`)

`llama.cpp`'s decode loop synchronizes all worker threads at a per-layer barrier. Requesting all
8 P-cores (`threads=8`, the shipped default and this chip's P-core count) leaves that barrier
with **zero scheduling slack**: on an idle machine that's optimal, but under this run's ambient
load (Docker Desktop, a VM, and Webex all competing for the same P-cores), the OS scheduler has
to preempt one of llama.cpp's own worker threads to service the other processes, and every other
worker then stalls at the barrier waiting for it. That is exactly what the baseline shows: wildly
unstable prefill (±56.6 t/s stddev against a 137.8 t/s mean) and a generation throughput
(9.05 t/s) far below what this chip is capable of. Leaving two P-cores unrequested
(`threads=6`) gives the scheduler room to service the competing processes without stalling
llama.cpp's own barrier, and every stage-A/B/C trial at `threads=6` (see `result.json`'s
`trials` array) is both faster *and* far less variable than the `threads=8` trials measured in
the same run. **The tuner adapted correctly to the machine as it actually was** — this is the
staged sweep and the credibility-guard methodology working exactly as designed, just not on a
quiet machine.

## Preset policy for this run

**No preset was packaged or committed from this run.** `presets/` stays empty until an
otherwise-idle-machine run produces a winning config that reflects the chip's actual capability
rather than this run's specific ambient-load conditions. See `CONTRIBUTING.md`'s "Contributing a
preset for a new chip" section for the policy this follows.
