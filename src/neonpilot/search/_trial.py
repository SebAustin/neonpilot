"""Wrap one `run_bench` call into a TrialResult, catching the untrusted-subprocess boundary's
exceptions per PLAN.md section 1.4 ("Non-zero exit / malformed JSON -> TrialResult(status=
"error"), never a crash").
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from neonpilot.bench.parser import BenchParseError
from neonpilot.bench.runner import BenchRunError
from neonpilot.models import BenchSample, RuntimeConfig, SweepContext, ThermalSnapshot, TrialResult

RunBenchFn = Callable[[str, str, RuntimeConfig | None, int, int, int, int], list[BenchSample]]


def baseline_display_config(threads: int) -> RuntimeConfig:
    """Best-effort reconstruction of llama.cpp's own resolved defaults for the baseline
    trial's `.config` display field (robustness review H3).

    `BenchSample` (PLAN.md section 1.3) does not carry n_threads/type_k/type_v/flash_attn, so
    this is NOT parsed from the actual JSON response. `threads` comes from
    `SweepContext.baseline_threads` (the caller's best estimate of llama.cpp's own default,
    typically the chip's P-core count) rather than a hardcoded constant, so it's no longer
    silently wrong on a non-8-P-core chip. The resulting `TrialResult.is_synthetic_config` is
    always set True by `execute_trial` for this config -- see docs/dev/build-notes.md.
    """
    return RuntimeConfig(
        threads=threads,
        cache_type_k="f16",
        cache_type_v="f16",
        flash_attn="auto",
        batch=2048,
        ubatch=512,
    )


def execute_trial(
    *,
    ctx: SweepContext,
    cfg: RuntimeConfig | None,
    stage: str,
    trial_id: str,
    run_bench: RunBenchFn,
    thermal_snapshot: ThermalSnapshot | None,
) -> tuple[TrialResult, float]:
    """Run one llama-bench call (or the cfg=None baseline) and wrap it in a TrialResult.

    :return: `(trial, wall_seconds)` -- the wall-clock seconds are used by the caller to keep a
        running average trial cost for budget projection (PLAN.md section 4.4).
    """
    started_at = datetime.now(UTC).isoformat()
    is_synthetic = cfg is None
    display_config = cfg if cfg is not None else baseline_display_config(ctx.baseline_threads)
    start = time.monotonic()
    try:
        samples = run_bench(
            ctx.binary,
            ctx.model_path,
            cfg,
            ctx.budget.reps,
            ctx.budget.prompt_n,
            ctx.budget.gen_n,
            ctx.timeout_s,
        )
    except (BenchRunError, BenchParseError) as exc:
        duration = time.monotonic() - start
        trial = TrialResult(
            trial_id=trial_id,
            stage=stage,
            config=display_config,
            prefill=None,
            generation=None,
            reps=ctx.budget.reps,
            started_at=started_at,
            ended_at=datetime.now(UTC).isoformat(),
            thermal=thermal_snapshot,
            status="error",
            error=str(exc),
            is_synthetic_config=is_synthetic,
        )
        return trial, duration

    duration = time.monotonic() - start
    prefill = next((s for s in samples if s.test_type == "pp"), None)
    generation = next((s for s in samples if s.test_type == "tg"), None)
    trial = TrialResult(
        trial_id=trial_id,
        stage=stage,
        config=display_config,
        prefill=prefill,
        generation=generation,
        reps=ctx.budget.reps,
        started_at=started_at,
        ended_at=datetime.now(UTC).isoformat(),
        thermal=thermal_snapshot,
        status="ok",
        error=None,
        is_synthetic_config=is_synthetic,
    )
    return trial, duration


def pruned_trial(cfg: RuntimeConfig, stage: str, trial_id: str) -> TrialResult:
    """A candidate that was never benched (early-stop dominance or budget truncation)."""
    now = datetime.now(UTC).isoformat()
    return TrialResult(
        trial_id=trial_id,
        stage=stage,
        config=cfg,
        prefill=None,
        generation=None,
        reps=0,
        started_at=now,
        ended_at=now,
        thermal=None,
        status="pruned",
        error=None,
    )
