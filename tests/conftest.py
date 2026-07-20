"""Shared pytest fixtures: fixture-file loading helpers + a deterministic sample SweepResult."""

from __future__ import annotations

from pathlib import Path

import pytest

from neonpilot.models import (
    SCHEMA_VERSION,
    BenchSample,
    CooldownPolicy,
    RuntimeConfig,
    SweepBudget,
    ThermalSnapshot,
    TrialResult,
)
from neonpilot.probe.macos_sysctl import read_chip_report

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    """Return a function that reads a fixture file (relative to tests/fixtures/) as text."""

    def _read(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return _read


@pytest.fixture
def sample_chip_report():
    """A real, verified ChipReport (M1 Max) with all timestamps fixed for golden-file stability."""
    text = (FIXTURES_DIR / "sysctl_apple_m1_max.txt").read_text(encoding="utf-8")
    report = read_chip_report(text)
    return _with_fixed_probed_at(report)


def _with_fixed_probed_at(report):
    import dataclasses

    return dataclasses.replace(report, probed_at="2026-07-20T00:00:00+00:00")


def _cfg(**overrides) -> RuntimeConfig:
    defaults = {
        "threads": 8,
        "cache_type_k": "f16",
        "cache_type_v": "f16",
        "flash_attn": "auto",
        "batch": 2048,
        "ubatch": 512,
    }
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


def _sample(
    avg_ts: float, test_type: str, n_prompt: int = 0, n_gen: int = 0, stddev_ts: float = 1.0
) -> BenchSample:
    return BenchSample(
        test_type=test_type,
        n_prompt=n_prompt,
        n_gen=n_gen,
        avg_ts=avg_ts,
        stddev_ts=stddev_ts,
        samples_ts=[avg_ts],
    )


def _trial(
    trial_id, stage, cfg, gen_ts=None, prefill_ts=None, status="ok", error=None
) -> TrialResult:
    return TrialResult(
        trial_id=trial_id,
        stage=stage,
        config=cfg,
        prefill=_sample(prefill_ts, "pp", n_prompt=64) if prefill_ts is not None else None,
        generation=_sample(gen_ts, "tg", n_gen=32) if gen_ts is not None else None,
        reps=2,
        started_at="2026-07-20T00:00:00+00:00",
        ended_at="2026-07-20T00:00:01+00:00",
        thermal=ThermalSnapshot(
            source="idle-skip", cpu_temp_c=None, throttled=None, cooldown_s=0.0
        ),
        status=status,
        error=error,
    )


@pytest.fixture
def sample_sweep_result():
    """A deterministic, fully synthetic SweepResult (no timestamps/randomness) for golden
    report/preset tests. Not a real hardware measurement -- see docs/dev/build-notes.md."""
    from neonpilot.models import SweepResult

    baseline_cfg = _cfg(threads=8)
    tuned_cfg = _cfg(
        threads=10,
        cache_type_k="q4_0",
        cache_type_v="q4_0",
        flash_attn="on",
        batch=4096,
        ubatch=2048,
    )

    a1 = _trial("A1", "A", _cfg(threads=6), gen_ts=45.0, prefill_ts=100.0)
    a2 = _trial("A2", "A", _cfg(threads=8), status="pruned")
    confirm_baseline = _trial(
        "confirm-baseline", "confirm", baseline_cfg, gen_ts=40.0, prefill_ts=100.0
    )
    confirm_best = _trial("confirm-best", "confirm", tuned_cfg, gen_ts=60.0, prefill_ts=180.0)

    budget = SweepBudget(total_seconds=180, reps=2, prompt_n=64, gen_n=32)
    return SweepResult(
        schema_version=SCHEMA_VERSION,
        model_file="SmolLM2-135M-Instruct-Q4_K_M.gguf",
        model_class="smollm2-135m-instruct-q4_k_m",
        llama_cpp_commit="178a6c44937154dc4c4eff0d166f4a044c4fceba",
        baseline=confirm_baseline,
        trials=[a1, a2, confirm_baseline, confirm_best],
        best=confirm_best,
        speedup_gen_pct=50.0,
        speedup_prefill_pct=80.0,
        elapsed_s=42.5,
        budget=budget,
        budget_truncated=False,
        dropped_stages=[],
    )


@pytest.fixture
def sample_cooldown_policy():
    return CooldownPolicy(
        target_temp_c=None, max_cooldown_s=20.0, fixed_delay_s=20.0, idle_skip=True
    )
