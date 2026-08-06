# M1 Max case study #2 — measured under moderate ambient load (2026-08-06)

> **This is measured under moderate ambient load; an adaptive result, not an idle-machine
> reference.** It is real, unmodified `neonpilot optimize` output — nothing here is fabricated
> or hand-adjusted. This run also carries neonpilot's own **load telemetry** (feature F-A):
> `SweepResult.load_before`/`load_after`, recorded automatically at sweep start and end — see
> "The receipts" below. See
> [README.md's "Case studies" section](../../../README.md#results) for how this run fits
> alongside the July 20 case study.

## What's here

- [`result.json`](./result.json) — the full `SweepResult` artifact (every trial, baseline,
  confirm pass, budget accounting, and both load snapshots) from the real run.
- [`report.md`](./report.md) / [`report.html`](./report.html) — the `neonpilot report` output
  generated from that same run via `uv run neonpilot report --run-dir
  ~/.neonpilot/runs/20260806T112600Z` (open `report.html` directly in a browser; it's
  self-contained). Its "Methodology" section includes the "Measurement conditions" line the
  load-telemetry feature adds.

Copied verbatim from `~/.neonpilot/runs/20260806T112600Z/` (the run directory itself is not
committed — only these four artifacts, per the run/preset-artifact split documented in the main
README).

## Machine and run conditions

| | |
|---|---|
| Machine | Apple M1 Max, 64 GB RAM, macOS 26.5.2 (same reference machine as the July 20 case study) |
| `llama.cpp` pin | tag `b10069` = SHA `178a6c44937154dc4c4eff0d166f4a044c4fceba` |
| Reference model | Qwen2.5-3B-Instruct Q4_K_M (~2.1 GB) |
| Budget / reps | 900s budget, 3 reps/config, `prompt_n=512`, `gen_n=128` (full-model defaults) |
| Outcome | Completed in full: `budget_truncated=false`, 480.7s elapsed, 8 trials measured / 7 pruned / 0 errored |

## The receipts: load telemetry recorded by this run

Unlike the July 20 case study (which predates feature F-A and has `load_before`/`load_after` =
`null`), this run's `result.json` carries an automatic, tool-recorded snapshot of ambient host
load at sweep start and sweep end — no manual `top`/Activity Monitor transcription, no
hand-adjustment. Verbatim from `result.json`:

| | `load_before` (sweep start) | `load_after` (sweep end) |
|---|---|---|
| `loadavg_1m` | **3.78** | **8.40** |
| `loadavg_5m` | 4.23 | 6.82 |
| `loadavg_15m` | 3.73 | 5.30 |
| Top process (`ps -Ao pcpu,comm -r`) | Claude Helper (Renderer) — 55.3% CPU | WindowServer — 45.7% CPU |
| 2nd process | WindowServer — 46.3% CPU | **Virtualization VM — 35.8% CPU** |
| 3rd process | Claude Helper — 23.2% CPU | Claude Helper — 29.0% CPU |

`loadavg_1m` more than doubled over the course of the sweep (3.78 → 8.40, on a 10-core
machine) — a Virtualization.framework VM that wasn't running when the sweep started came back
and was consuming ~36% of a core by the time it finished. Neither number was edited or curated;
this is exactly what the sweep's own telemetry captured, unprompted, on a machine doing normal
day-to-day work in the background. This is case study #2: **moderate, and non-constant, ambient
load** — a different regime from July 20's heavier-but-steadier Docker/VM/Webex load, and this
run's own telemetry is what makes that distinction verifiable instead of anecdotal.

## Results

| Metric | Baseline (`threads=8`, llama.cpp defaults) | Tuned (`threads=6, fa=off, kv=f16, b=2048/512`) | Speedup |
|---|---|---|---|
| Generation t/s (avg ± stddev) | 13.24 ± 1.85 | 24.05 ± 0.59 | **+81.6%** |
| Prefill t/s (avg ± stddev) | 182.51 ± 0.49 | 160.03 ± 0.54 | **−12.3%** |

Both numbers are the confirm-pass measurement (baseline and winner re-measured back-to-back in
the same thermal/scheduling window, per the project's baseline-fairness methodology) — not a
comparison across different points in the sweep.

## Interpretation, including the prefill tradeoff (verified against `result.json`'s per-trial samples)

**Generation (+81.6%):** the same `threads=6` finding as the July 20 case study, reproduced
independently on a different day under a different (moderate, not heavy) load regime — every
Stage A/B/C trial at `threads=6` (see `result.json`'s `trials` array, e.g. `A1`: 26.81 t/s,
`C1`-`C3`: 21.6-23.2 t/s) beats every `threads=8` trial (`A2`: 14.08 t/s) by a wide, consistent
margin. `llama.cpp`'s decode loop synchronizes all worker threads at a per-layer barrier;
requesting all 8 P-cores leaves that barrier with zero scheduling slack, so any competing
process (Claude Helper, WindowServer, and — as the telemetry above shows — a VM that started
mid-run) forces a preemption that stalls every other worker thread waiting at the barrier.
Leaving two P-cores unrequested (`threads=6`) gives the scheduler room to service that
competing work without stalling llama.cpp's own barrier.

**Prefill (−12.3%, honestly reported, not hidden):** unlike July 20 (where a larger batch/ubatch
choice, `b=4096/2048`, happened to also help prefill, +21.9%), this run's tuned config kept the
baseline's `batch=2048/ubatch=512` and only changed `threads` (8→6) and `flash_attn`
(`auto`→`off`). Prefill is compute-bound and, unlike the memory/scheduling-bound decode loop,
genuinely benefits from more threads when nothing else is competing for them — so trading two
P-cores away for decode-time scheduling slack costs prefill throughput (baseline 182.5 t/s vs.
tuned 160.0 t/s). This is expected, not a bug: `search/_selection.py` optimizes generation
throughput as PLAN.md's primary objective (Stage A/B pick the generation-throughput winner;
Stage C's own guard only requires prefill *not to regress past the dominance margin* against
that generation-optimal config, not to also win on prefill). A workload that's prefill-dominated
(e.g. long-context ingestion with short completions) would want a different, threads=8-leaning
config — which is exactly the kind of nuance real per-run measurement surfaces and a single
"headline speedup" number would hide.

## Preset policy for this run

**No preset was packaged or committed from this run**, same policy as July 20. `presets/` stays
empty until an otherwise-idle-machine run (loadavg comfortably below the tuner's own
`--strict-idle` 0.5×core-count threshold, and the caveat this feature adds absent) produces a
winning config that reflects the chip's actual capability rather than either run's specific
ambient-load conditions. See `CONTRIBUTING.md`'s "Contributing a preset for a new chip" section
for the policy this follows. That idle run is expected to come from the Apple M5 reference
machine's `make benchmark` invocation (see the main README's "Case studies" section) — at which
point this feature's own telemetry is exactly what will confirm, in the report itself, that the
number is reference-grade.
