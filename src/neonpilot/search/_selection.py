"""Winner-selection helpers for search/engine.py (PLAN.md sections 4.1/4.2).

Kept separate from `engine.py`'s orchestration loop so each stage's selection rule -- which
differs per PLAN.md section 4.1 -- is independently testable.
"""

from __future__ import annotations

from neonpilot.bench.stats import dominates
from neonpilot.models import TrialResult

#: KV-cache "smaller is better" tie-break rank (PLAN.md section 4.1: "memory-tie rule
#: preferring smaller KV cache when within noise"). Lower rank == smaller cache.
_KV_CACHE_RANK = {"q4_0": 0, "q8_0": 1, "f16": 2}


def is_measured(trial: TrialResult) -> bool:
    """True iff `trial` was actually benched (status "ok") and has a generation sample."""
    return trial.status == "ok" and trial.generation is not None


def measured(trials: list[TrialResult]) -> list[TrialResult]:
    """Filter to trials that were actually benched successfully."""
    return [trial for trial in trials if is_measured(trial)]


def better(a: TrialResult, b: TrialResult) -> TrialResult:
    """Whichever of `a`/`b` has higher generation t/s; an unmeasured trial always loses."""
    if not is_measured(b):
        return a
    if not is_measured(a):
        return b
    return b if b.generation.avg_ts > a.generation.avg_ts else a


def select_stage_a_winner(trials: list[TrialResult], fallback: TrialResult) -> TrialResult:
    """Highest generation t/s; ties broken by prefill t/s, then fewer threads."""
    candidates = measured(trials)
    if not candidates:
        return fallback
    return max(
        candidates,
        key=lambda t: (
            t.generation.avg_ts,
            t.prefill.avg_ts if t.prefill else 0.0,
            -t.config.threads,
        ),
    )


def select_stage_b_winner(trials: list[TrialResult], fallback: TrialResult) -> TrialResult:
    """Highest generation t/s; ties broken by prefill t/s, then smaller KV cache."""
    candidates = measured(trials)
    if not candidates:
        return fallback
    return max(
        candidates,
        key=lambda t: (
            t.generation.avg_ts,
            t.prefill.avg_ts if t.prefill else 0.0,
            -_KV_CACHE_RANK.get(t.config.cache_type_k, 0),
        ),
    )


def select_stage_c_winner(trials: list[TrialResult], guard: TrialResult) -> TrialResult:
    """Highest prefill t/s among candidates that don't statistically regress vs `guard`.

    "Regress" means `guard` statistically dominates the candidate on generation t/s
    (PLAN.md section 4.1: "requiring generation t/s not to regress > noise").
    """
    candidates = [t for t in measured(trials) if not dominates(guard, t)]
    if not candidates:
        return guard
    return max(
        candidates, key=lambda t: (t.prefill.avg_ts if t.prefill else 0.0, t.generation.avg_ts)
    )
