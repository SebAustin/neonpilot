"""Tests for search/_selection.py: per-stage winner-selection rules (PLAN.md section 4.1/4.2)."""

from __future__ import annotations

from neonpilot.models import BenchSample, RuntimeConfig, TrialResult
from neonpilot.search._selection import (
    better,
    select_stage_a_winner,
    select_stage_b_winner,
    select_stage_c_winner,
)

_CFG = RuntimeConfig(
    threads=8, cache_type_k="f16", cache_type_v="f16", flash_attn="auto", batch=2048, ubatch=512
)


def _sample(avg_ts: float, stddev_ts: float = 1.0, test_type: str = "tg") -> BenchSample:
    return BenchSample(
        test_type=test_type,
        n_prompt=0,
        n_gen=128,
        avg_ts=avg_ts,
        stddev_ts=stddev_ts,
        samples_ts=[avg_ts],
    )


def _trial(
    trial_id: str,
    threads=8,
    cache_type_k="f16",
    flash_attn="auto",
    batch=2048,
    ubatch=512,
    gen_ts=None,
    prefill_ts=None,
    status="ok",
):
    cfg = RuntimeConfig(
        threads=threads,
        cache_type_k=cache_type_k,
        cache_type_v=cache_type_k,
        flash_attn=flash_attn,
        batch=batch,
        ubatch=ubatch,
    )
    generation = _sample(gen_ts, test_type="tg") if gen_ts is not None else None
    prefill = _sample(prefill_ts, test_type="pp") if prefill_ts is not None else None
    return TrialResult(
        trial_id=trial_id,
        stage="A",
        config=cfg,
        prefill=prefill,
        generation=generation,
        reps=3,
        started_at="2026-07-20T00:00:00Z",
        ended_at="2026-07-20T00:00:01Z",
        thermal=None,
        status=status,
        error=None,
    )


def test_better_picks_higher_generation_ts():
    a = _trial("a", gen_ts=10.0)
    b = _trial("b", gen_ts=20.0)
    assert better(a, b) is b
    assert better(b, a) is b


def test_better_ignores_unmeasured_trials():
    ok = _trial("ok", gen_ts=10.0)
    pruned = _trial("pruned", gen_ts=None, status="pruned")
    errored = _trial("errored", gen_ts=None, status="error")
    assert better(ok, pruned) is ok
    assert better(pruned, ok) is ok
    assert better(ok, errored) is ok


def test_select_stage_a_winner_highest_gen_ts():
    trials = [
        _trial("A1", threads=6, gen_ts=50.0),
        _trial("A2", threads=8, gen_ts=70.0),
        _trial("A3", threads=9, gen_ts=60.0),
    ]
    winner = select_stage_a_winner(trials, fallback=trials[0])
    assert winner.trial_id == "A2"


def test_select_stage_a_winner_ties_broken_by_prefill_then_fewer_threads():
    trials = [
        _trial("A1", threads=10, gen_ts=50.0, prefill_ts=100.0),
        _trial(
            "A2", threads=6, gen_ts=50.0, prefill_ts=100.0
        ),  # same gen+prefill, fewer threads wins
    ]
    winner = select_stage_a_winner(trials, fallback=trials[0])
    assert winner.trial_id == "A2"


def test_select_stage_a_winner_falls_back_when_nothing_measured():
    trials = [_trial("A1", gen_ts=None, status="pruned")]
    fallback = _trial("baseline", gen_ts=5.0)
    assert select_stage_a_winner(trials, fallback) is fallback


def test_select_stage_b_winner_prefers_smaller_kv_on_tie():
    trials = [
        _trial("B1", cache_type_k="f16", gen_ts=80.0, prefill_ts=100.0),
        _trial("B2", cache_type_k="q4_0", gen_ts=80.0, prefill_ts=100.0),
    ]
    winner = select_stage_b_winner(trials, fallback=trials[0])
    assert winner.trial_id == "B2"


def test_select_stage_b_winner_highest_gen_ts_wins_outright():
    trials = [
        _trial("B1", cache_type_k="f16", gen_ts=90.0),
        _trial("B2", cache_type_k="q4_0", gen_ts=80.0),
    ]
    winner = select_stage_b_winner(trials, fallback=trials[0])
    assert winner.trial_id == "B1"


def test_select_stage_c_winner_highest_prefill_without_regression():
    guard = _trial("B*", gen_ts=100.0)
    trials = [
        _trial("C1", batch=2048, ubatch=512, gen_ts=100.0, prefill_ts=120.0),
        _trial("C2", batch=4096, ubatch=2048, gen_ts=100.0, prefill_ts=200.0),
    ]
    winner = select_stage_c_winner(trials, guard=guard)
    assert winner.trial_id == "C2"


def test_select_stage_c_winner_excludes_regressed_candidates():
    guard = _trial("B*", gen_ts=100.0, prefill_ts=50.0)
    regressed = _trial("C1", gen_ts=1.0, prefill_ts=500.0)  # huge prefill but gen collapses
    ok_candidate = _trial("C2", gen_ts=100.0, prefill_ts=120.0)
    winner = select_stage_c_winner([regressed, ok_candidate], guard=guard)
    assert winner.trial_id == "C2"


def test_select_stage_c_winner_falls_back_to_guard_when_all_regressed():
    guard = _trial("B*", gen_ts=100.0, prefill_ts=50.0)
    regressed = _trial("C1", gen_ts=1.0, prefill_ts=500.0)
    winner = select_stage_c_winner([regressed], guard=guard)
    assert winner is guard
