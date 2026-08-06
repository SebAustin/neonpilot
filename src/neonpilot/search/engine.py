"""Orchestrate a staged benchmark sweep: baseline -> Stage A -> B -> C -> confirm pass.

Implements PLAN.md sections 4.1 (staged sweep), 4.3 (early stopping), and 4.4 (adaptive
cooldown + budget truncation). Truncation order per section 4.4: adaptive cooldown "extras"
are dropped first (free -- no stage/trial is skipped), then Stage C, then the confirm pass
(dropped last because the confirm pass is what makes the section 9 speedup number a fair
back-to-back measurement). `budget_truncated`/`dropped_stages` are only set when a stage or
the confirm pass is actually skipped -- not when only cooldown time was reclaimed.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from neonpilot.bench import runner as bench_runner
from neonpilot.bench.sysload import collect_load_snapshot as default_collect_load
from neonpilot.bench.thermal import cooldown as default_cooldown
from neonpilot.models import (
    SCHEMA_VERSION,
    BenchSample,
    LoadSnapshot,
    SearchPlan,
    SweepContext,
    SweepResult,
    ThermalSnapshot,
    TrialResult,
)
from neonpilot.search import _selection
from neonpilot.search._stage_runner import CooldownFn, run_stage
from neonpilot.search._trial import RunBenchFn, execute_trial, pruned_trial

#: Injected collector signature (feature F-A): a zero-arg callable returning a `LoadSnapshot`
#: (or `None` when `os.getloadavg()` itself failed -- N1: reproducible in restricted/sandboxed
#: containers), mirroring the `RunBenchFn`/`CooldownFn` dependency-injection pattern already
#: used here so tests never need a real `ps`/`os.getloadavg()` call.
CollectLoadFn = Callable[[], LoadSnapshot | None]

#: Worst-case config count with no pruning (PLAN.md section 4.1: "16 configs"), used as the
#: initial average-trial-cost estimate before any real timing data exists.
_WORST_CASE_CONFIG_COUNT = 16
_CONFIRM_TRIAL_COUNT = 2
_SKIPPED_COOLDOWN = ThermalSnapshot(
    source="idle-skip", cpu_temp_c=None, throttled=None, cooldown_s=0.0
)


def _pct_speedup(best: BenchSample | None, baseline: BenchSample | None) -> float:
    if best is None or baseline is None or baseline.avg_ts == 0:
        return 0.0
    return (best.avg_ts - baseline.avg_ts) / baseline.avg_ts * 100


class _BudgetTracker:
    """Tracks elapsed wall-clock time and projects whether remaining work fits the budget."""

    def __init__(self, ctx: SweepContext) -> None:
        self._ctx = ctx
        self._start = time.monotonic()
        self._trial_durations: list[float] = []
        self.extras_dropped = False
        self.dropped_stages: list[str] = []
        self.budget_truncated = False

    def record(self, durations: list[float]) -> None:
        self._trial_durations.extend(durations)

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def _avg_trial_s(self) -> float:
        if self._trial_durations:
            return statistics.mean(self._trial_durations)
        return self._ctx.budget.total_seconds / _WORST_CASE_CONFIG_COUNT

    def _avg_cooldown_s(self) -> float:
        return 0.0 if self.extras_dropped else self._ctx.cooldown.max_cooldown_s

    def projected(self, remaining_trials: int) -> float:
        return self.elapsed() + remaining_trials * (self._avg_trial_s() + self._avg_cooldown_s())

    def over_budget(self, remaining_trials: int) -> bool:
        return self.projected(remaining_trials) > self._ctx.budget.total_seconds

    def try_fit(self, remaining_trials: int, stage_to_drop: str) -> bool:
        """Attempt to fit `remaining_trials` in budget; drop cooldown extras first, then the
        named stage. Returns True iff the stage must be dropped."""
        if not self.over_budget(remaining_trials):
            return False
        if not self.extras_dropped:
            self.extras_dropped = True
        if not self.over_budget(remaining_trials):
            return False
        self.budget_truncated = True
        self.dropped_stages.append(stage_to_drop)
        return True

    def mark_partially_dropped(self, stage_name: str) -> None:
        """Record that `stage_name` was cut short mid-stage (H6: a new candidate was never
        started because the budget projection said it wouldn't fit) -- distinct from
        `try_fit`'s all-or-nothing drop of an entire not-yet-started stage."""
        self.budget_truncated = True
        self.dropped_stages.append(stage_name)


def _run_baseline(ctx: SweepContext, run_bench: RunBenchFn) -> tuple[TrialResult, float]:
    return execute_trial(
        ctx=ctx,
        cfg=None,
        stage="baseline",
        trial_id="baseline",
        run_bench=run_bench,
        thermal_snapshot=None,
    )


def _run_confirm_pass(
    ctx: SweepContext,
    candidate_cfg,
    run_bench: RunBenchFn,
    cooldown_fn: CooldownFn,
    extras_dropped: bool,
) -> tuple[TrialResult, TrialResult, list[float]]:
    snapshot_a = _SKIPPED_COOLDOWN if extras_dropped else cooldown_fn(ctx.cooldown)
    confirm_baseline, duration_a = execute_trial(
        ctx=ctx,
        cfg=None,
        stage="confirm",
        trial_id="confirm-baseline",
        run_bench=run_bench,
        thermal_snapshot=snapshot_a,
    )
    snapshot_b = _SKIPPED_COOLDOWN if extras_dropped else cooldown_fn(ctx.cooldown)
    confirm_candidate, duration_b = execute_trial(
        ctx=ctx,
        cfg=candidate_cfg,
        stage="confirm",
        trial_id="confirm-best",
        run_bench=run_bench,
        thermal_snapshot=snapshot_b,
    )
    return confirm_baseline, confirm_candidate, [duration_a, duration_b]


def run(
    plan: SearchPlan,
    ctx: SweepContext,
    *,
    run_bench: RunBenchFn = bench_runner.run_bench,
    cooldown_fn: CooldownFn = default_cooldown,
    collect_load: CollectLoadFn = default_collect_load,
) -> SweepResult:
    """Run the full staged sweep (baseline -> A -> B -> C -> confirm) and return a SweepResult.

    :param run_bench: injected so this is unit-testable with a deterministic fake (PLAN.md
        section 1.3's `SweepContext` comment: "runner is dependency-injected as a callable").
    :param cooldown_fn: injected for the same reason; defaults to the real adaptive cooldown.
    :param collect_load: injected for the same reason (feature F-A); defaults to the real
        `ps`/`os.getloadavg()`-backed collector. Called once at sweep start and once at sweep
        end so a report can cite recorded ambient-load numbers.
    """
    tracker = _BudgetTracker(ctx)
    load_before = collect_load()

    baseline_trial, baseline_duration = _run_baseline(ctx, run_bench)
    tracker.record([baseline_duration])
    running_best = baseline_trial

    stage_a_trials, _durations_a, running_best, a_budget_exceeded = run_stage(
        stage_name="A",
        candidates=plan.stage_a,
        ctx=ctx,
        incumbent=running_best,
        run_bench=run_bench,
        cooldown_fn=cooldown_fn,
        extras_dropped=tracker.extras_dropped,
        budget_tracker=tracker,
    )
    if a_budget_exceeded:
        tracker.mark_partially_dropped("A")
    stage_a_winner = _selection.select_stage_a_winner(stage_a_trials, baseline_trial)

    stage_b_candidates = [
        replace(cfg, threads=stage_a_winner.config.threads) for cfg in plan.stage_b
    ]
    stage_b_trials, _durations_b, running_best, b_budget_exceeded = run_stage(
        stage_name="B",
        candidates=stage_b_candidates,
        ctx=ctx,
        incumbent=running_best,
        run_bench=run_bench,
        cooldown_fn=cooldown_fn,
        extras_dropped=tracker.extras_dropped,
        budget_tracker=tracker,
    )
    if b_budget_exceeded:
        tracker.mark_partially_dropped("B")
    stage_b_winner = _selection.select_stage_b_winner(stage_b_trials, stage_a_winner)

    stage_c_trials, stage_c_winner = _run_stage_c(
        plan, ctx, stage_a_winner, stage_b_winner, tracker, run_bench, cooldown_fn
    )
    running_best = _selection.better(running_best, stage_c_winner)

    final_baseline, best, confirm_trials = _run_confirm_or_fallback(
        ctx, baseline_trial, stage_c_winner, running_best, tracker, run_bench, cooldown_fn
    )
    load_after = collect_load()

    all_trials = stage_a_trials + stage_b_trials + stage_c_trials + confirm_trials
    return SweepResult(
        schema_version=SCHEMA_VERSION,
        model_file=Path(ctx.model_path).name,
        model_class=ctx.model_class,
        llama_cpp_commit=ctx.llama_cpp_commit,
        baseline=final_baseline,
        trials=all_trials,
        best=best,
        speedup_gen_pct=_pct_speedup(best.generation, final_baseline.generation),
        speedup_prefill_pct=_pct_speedup(best.prefill, final_baseline.prefill),
        elapsed_s=tracker.elapsed(),
        load_before=load_before,
        load_after=load_after,
        budget=ctx.budget,
        budget_truncated=tracker.budget_truncated,
        dropped_stages=tracker.dropped_stages,
    )


def _run_stage_c(plan, ctx, stage_a_winner, stage_b_winner, tracker, run_bench, cooldown_fn):
    remaining_before_c = len(plan.stage_c) + _CONFIRM_TRIAL_COUNT
    if tracker.try_fit(remaining_before_c, "C"):
        stage_c_trials = [
            pruned_trial(cfg, "C", f"C{index}") for index, cfg in enumerate(plan.stage_c, start=1)
        ]
        return stage_c_trials, stage_b_winner

    stage_c_candidates = [
        replace(
            cfg,
            threads=stage_a_winner.config.threads,
            flash_attn=stage_b_winner.config.flash_attn,
            cache_type_k=stage_b_winner.config.cache_type_k,
            cache_type_v=stage_b_winner.config.cache_type_v,
        )
        for cfg in plan.stage_c
    ]
    stage_c_trials, _durations_c, _, c_budget_exceeded = run_stage(
        stage_name="C",
        candidates=stage_c_candidates,
        ctx=ctx,
        incumbent=stage_b_winner,
        run_bench=run_bench,
        cooldown_fn=cooldown_fn,
        extras_dropped=tracker.extras_dropped,
        budget_tracker=tracker,
    )
    if c_budget_exceeded:
        tracker.mark_partially_dropped("C")
    stage_c_winner = _selection.select_stage_c_winner(stage_c_trials, stage_b_winner)
    return stage_c_trials, stage_c_winner


def _run_confirm_or_fallback(
    ctx, baseline_trial, stage_c_winner, running_best, tracker, run_bench, cooldown_fn
):
    if tracker.try_fit(_CONFIRM_TRIAL_COUNT, "confirm"):
        return baseline_trial, running_best, []

    confirm_baseline, confirm_candidate, confirm_durations = _run_confirm_pass(
        ctx, stage_c_winner.config, run_bench, cooldown_fn, tracker.extras_dropped
    )
    tracker.record(confirm_durations)
    best = _selection.better(confirm_baseline, confirm_candidate)
    return confirm_baseline, best, [confirm_baseline, confirm_candidate]
