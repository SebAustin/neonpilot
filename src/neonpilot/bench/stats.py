"""Cross-config statistics helpers: median/stddev for reporting, dominance for early stopping.

Per PLAN.md section 4.3, llama-bench's own `avg_ts`/`stddev_ts` are trusted for *within-config*
variance (computed over the `-r reps` samples in a single call); this module is used only for
*cross-config* comparisons -- median/stddev of an arbitrary sample list, and the dominance
rule that drives candidate-level pruning.
"""

from __future__ import annotations

import statistics

from neonpilot.models import TrialResult

#: Dominance safety margin (PLAN.md section 4.3): best dominates cand iff
#: best.gen_ts - k*best.stddev > cand.gen_ts + k*cand.stddev
_DOMINANCE_K = 1.0


def median(xs: list[float]) -> float:
    """Median of a non-empty list of floats.

    :raises ValueError: if `xs` is empty.
    """
    if not xs:
        raise ValueError("median() requires a non-empty list")
    return statistics.median(xs)


def stddev(xs: list[float]) -> float:
    """Sample standard deviation of `xs`. Returns 0.0 for a single-element list (no variance)."""
    if not xs:
        raise ValueError("stddev() requires a non-empty list")
    if len(xs) == 1:
        return 0.0
    return statistics.stdev(xs)


def dominates(best: TrialResult, cand: TrialResult) -> bool:
    """True iff `best`'s generation throughput statistically dominates `cand`'s.

    Uses each trial's *generation* BenchSample (avg_ts/stddev_ts), the primary objective
    (PLAN.md section 4.2). Returns False -- "cannot prove dominance" -- if either trial lacks a
    generation sample, so callers never prune on missing data.
    """
    if best.generation is None or cand.generation is None:
        return False
    best_floor = best.generation.avg_ts - _DOMINANCE_K * best.generation.stddev_ts
    cand_ceiling = cand.generation.avg_ts + _DOMINANCE_K * cand.generation.stddev_ts
    return best_floor > cand_ceiling
