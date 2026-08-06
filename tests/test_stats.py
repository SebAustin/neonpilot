"""Tests for bench/stats.py: dominates() truth table."""

from __future__ import annotations

from neonpilot.bench.stats import dominates
from neonpilot.models import BenchSample, RuntimeConfig, TrialResult

_CFG = RuntimeConfig(
    threads=8, cache_type_k="f16", cache_type_v="f16", flash_attn="auto", batch=2048, ubatch=512
)


def _trial(trial_id: str, gen_avg_ts: float | None, gen_stddev_ts: float = 0.0) -> TrialResult:
    generation = (
        None
        if gen_avg_ts is None
        else BenchSample(
            test_type="tg",
            n_prompt=0,
            n_gen=128,
            avg_ts=gen_avg_ts,
            stddev_ts=gen_stddev_ts,
            samples_ts=[gen_avg_ts],
        )
    )
    return TrialResult(
        trial_id=trial_id,
        stage="A",
        config=_CFG,
        prefill=None,
        generation=generation,
        reps=3,
        started_at="2026-07-20T00:00:00Z",
        ended_at="2026-07-20T00:00:01Z",
        thermal=None,
        status="ok",
        error=None,
    )


def test_dominates_true_when_clearly_faster():
    best = _trial("best", gen_avg_ts=100.0, gen_stddev_ts=1.0)
    cand = _trial("cand", gen_avg_ts=50.0, gen_stddev_ts=1.0)
    assert dominates(best, cand) is True


def test_dominates_false_when_within_noise_band():
    best = _trial("best", gen_avg_ts=100.0, gen_stddev_ts=10.0)
    cand = _trial("cand", gen_avg_ts=95.0, gen_stddev_ts=10.0)
    assert dominates(best, cand) is False


def test_dominates_false_when_candidate_faster():
    best = _trial("best", gen_avg_ts=50.0, gen_stddev_ts=1.0)
    cand = _trial("cand", gen_avg_ts=100.0, gen_stddev_ts=1.0)
    assert dominates(best, cand) is False


def test_dominates_false_when_generation_missing():
    best = _trial("best", gen_avg_ts=None)
    cand = _trial("cand", gen_avg_ts=50.0)
    assert dominates(best, cand) is False
    assert dominates(cand, best) is False
