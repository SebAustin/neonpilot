"""Run one stage's candidate list with candidate-level early stopping (PLAN.md section 4.3).

Simplification recorded in docs/dev/build-notes.md: PLAN.md's per-knob "monotonically worse
along the swept axis" pruning condition is generalized here to "the running incumbent (best
trial seen anywhere in the sweep so far) statistically dominates this candidate" -- a
conservative, stage-agnostic rule that prunes at least as eagerly and never prunes a
candidate that's already been benched.
"""

from __future__ import annotations

from collections.abc import Callable

from neonpilot.bench.stats import dominates
from neonpilot.bench.thermal import cooldown as default_cooldown
from neonpilot.models import (
    CooldownPolicy,
    RuntimeConfig,
    SweepContext,
    ThermalSnapshot,
    TrialResult,
)
from neonpilot.search._selection import better
from neonpilot.search._trial import RunBenchFn, execute_trial, pruned_trial

CooldownFn = Callable[[CooldownPolicy], ThermalSnapshot]

_SKIPPED_COOLDOWN = ThermalSnapshot(
    source="idle-skip", cpu_temp_c=None, throttled=None, cooldown_s=0.0
)


def run_stage(
    *,
    stage_name: str,
    candidates: list[RuntimeConfig],
    ctx: SweepContext,
    incumbent: TrialResult,
    run_bench: RunBenchFn,
    cooldown_fn: CooldownFn = default_cooldown,
    extras_dropped: bool = False,
) -> tuple[list[TrialResult], list[float], TrialResult]:
    """Bench each candidate in order, pruning the rest of the stage once the incumbent
    statistically dominates a just-measured candidate.

    :return: `(trials, wall_seconds_per_trial, updated_incumbent)`. `trials` has one entry per
        candidate (benched, pruned, or errored) -- pruning never drops a trial from the list,
        only marks it `status="pruned"` without spending a subprocess call on it.
    """
    trials: list[TrialResult] = []
    durations: list[float] = []
    current_best = incumbent
    prune_rest = False

    for index, cfg in enumerate(candidates, start=1):
        trial_id = f"{stage_name}{index}"
        if prune_rest:
            trials.append(pruned_trial(cfg, stage_name, trial_id))
            continue

        snapshot = _SKIPPED_COOLDOWN if extras_dropped else cooldown_fn(ctx.cooldown)
        trial, duration = execute_trial(
            ctx=ctx,
            cfg=cfg,
            stage=stage_name,
            trial_id=trial_id,
            run_bench=run_bench,
            thermal_snapshot=snapshot,
        )
        trials.append(trial)
        durations.append(duration)

        if trial.status == "ok":
            if dominates(current_best, trial):
                prune_rest = True
            current_best = better(current_best, trial)

    return trials, durations, current_best
