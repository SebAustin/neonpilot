# ADR 0002 — Staged greedy sweep (A→B→C→confirm) instead of a full grid search

## Context

`optimize` must find a near-optimal `llama.cpp` runtime config across four tunable knob groups
(thread count, KV-cache type, flash-attention, batch/ubatch size) within a hard wall-clock budget
(900s full-model, 180s CI). A full Cartesian product of the candidate sets described in
`PLAN.md` §4.1 (4 thread configs × 6 flash-attn/KV pairs × 3 batch pairs) is 72 combinations
before even adding a baseline — around O(product) ≈ 36+ once the actual per-knob candidate counts
are applied, and each config costs roughly 20-25 seconds to measure (model load + `-r reps`
prefill/generation passes) plus a cooldown gap.

## Decision

Use a staged, greedy hill-climbing search instead: measure the baseline first, then Stage A
(threads only) picks a winner, Stage B (flash-attn × KV-cache, with Stage A's winning thread
count fixed) picks a winner, Stage C (batch/ubatch, with A and B's winners fixed) picks a winner,
and a final confirm pass re-measures baseline vs. the Stage-C winner back-to-back. Each
fully-measured candidate is checked against the running best via a statistical-dominance test
(`bench/stats.dominates`, k=1.0 stddev margin); if the best already beats it outside noise, the
rest of that candidate's stage is pruned (marked `status="pruned"`, never benched) rather than
measured to completion.

## Consequences

- **Fits the budget with headroom.** Worst case (no pruning) is 1 baseline + 4 (A) + 6 (B) + 3
  (C) + 2 (confirm) = 16 configs, versus 36+ for the full grid — the documented worst-case time
  table (`PLAN.md` §4.4) projects ~668s against a 900s budget, leaving room for slower-than-
  estimated throughput or a high-variance re-measure. With early stopping, real runs typically
  land at ~10-12 configs.
- **May miss the true joint optimum.** A greedy per-knob-group search can converge to a
  locally-but-not-globally optimal config if two knobs interact non-additively (e.g. the best
  KV-cache type depends on the *final* thread count rather than Stage A's winner). This is an
  accepted trade-off: `PLAN.md` §4.1 orders the stages by expected impact (threads first, then
  flash-attn/KV — "the most impactful group for CPU decode and memory bandwidth" — then batching),
  so the highest-value knobs are optimized with the least contamination from later-fixed values.
- **Pruning removes future work only, never in-progress measurement.** A candidate that's already
  been benched is never discarded or its result overwritten — pruning only skips *not-yet-run*
  candidates in the same stage, so every reported number is a real measurement, and pruned
  trials are shown greyed-out in the report for methodology transparency.
- **Truncation is a last resort, not the expected path.** If elapsed time projects over budget,
  work is dropped in the order *adaptive cooldown extras → Stage C → confirm pass* — never Stage
  A/B, and the confirm pass is dropped only after Stage C, since it's what makes the headline
  speedup number a fair back-to-back comparison. `SweepResult.budget_truncated` and
  `dropped_stages` record this so the report never silently presents a degraded measurement as a
  full one.
- **Rejected alternative:** full Cartesian grid — correctness-simpler (finds the true joint
  optimum over the candidate sets) but roughly 2-3x more configs, which would either blow the
  15-minute budget or force cutting reps below the ≥3 statistical-reliability floor.
