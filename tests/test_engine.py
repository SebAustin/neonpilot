"""Tests for search/engine.py with a MOCKED runner (PLAN.md sections 4.1-4.4).

No real subprocess/sleep ever happens here: `run_bench` and `cooldown_fn` are fully injected
fakes, and `time.monotonic` is monkeypatched where budget-truncation timing needs to be
deterministic. This is the mocked-runner test suite called for in milestone M3.
"""

from __future__ import annotations

import time

import pytest

from neonpilot.bench.runner import BenchRunError
from neonpilot.models import (
    BenchSample,
    CooldownPolicy,
    LoadSnapshot,
    SweepBudget,
    SweepContext,
    ThermalSnapshot,
)
from neonpilot.probe.macos_sysctl import read_chip_report
from neonpilot.search import engine, planner


def _make_ctx(
    *, total_seconds=900, max_cooldown_s=0.0, reps=2, prompt_n=64, gen_n=32
) -> SweepContext:
    return SweepContext(
        binary="fake-bin",
        model_path="model.gguf",
        model_class="test-model",
        out_dir="/tmp/neonpilot-test",
        budget=SweepBudget(total_seconds=total_seconds, reps=reps, prompt_n=prompt_n, gen_n=gen_n),
        cooldown=CooldownPolicy(
            target_temp_c=None,
            max_cooldown_s=max_cooldown_s,
            fixed_delay_s=max_cooldown_s,
            idle_skip=True,
        ),
        timeout_s=30,
        llama_cpp_commit="deadbeef",
    )


def _fake_cooldown(policy):
    return ThermalSnapshot(source="idle-skip", cpu_temp_c=None, throttled=None, cooldown_s=0.0)


def _fake_collect_load():
    """Deterministic fake for feature F-A's injected load collector -- this module's docstring
    promises no real subprocess ever runs here, and the default `collect_load` would otherwise
    shell out to a real `ps`/`os.getloadavg()`."""
    return LoadSnapshot(loadavg_1m=0.5, loadavg_5m=0.4, loadavg_15m=0.3, top_processes=[])


def _m1_max_chip(fixture_text):
    return read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))


def _score(cfg):
    """Deterministic scoring so every stage has an unambiguous winner (PLAN.md section 4.1)."""
    if cfg is None:
        return 50.0, 100.0  # baseline: gen_ts, prefill_ts
    gen = 60.0 + cfg.threads
    if cfg.flash_attn == "on" and cfg.cache_type_k == "q4_0":
        gen += 50.0  # clear Stage B winner
    elif cfg.flash_attn == "on":
        gen += 20.0
    prefill = 100.0
    if (cfg.batch, cfg.ubatch) == (4096, 2048):
        prefill = 200.0  # clear Stage C winner (gen_ts unaffected by batch/ubatch -> no regression)
    elif (cfg.batch, cfg.ubatch) == (2048, 1024):
        prefill = 150.0
    return gen, prefill


class RecordingRunner:
    """Deterministic fake `run_bench`: records every cfg it was called with."""

    def __init__(self, score_fn=_score):
        self.score_fn = score_fn
        self.calls: list = []

    def __call__(self, binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        self.calls.append(cfg)
        gen_ts, prefill_ts = self.score_fn(cfg)
        return [
            BenchSample(
                test_type="pp",
                n_prompt=prompt_n,
                n_gen=0,
                avg_ts=prefill_ts,
                stddev_ts=1.0,
                samples_ts=[prefill_ts],
            ),
            BenchSample(
                test_type="tg",
                n_prompt=0,
                n_gen=gen_n,
                avg_ts=gen_ts,
                stddev_ts=1.0,
                samples_ts=[gen_ts],
            ),
        ]


class TickingClock:
    """A fully deterministic fake `time.monotonic`: advances by `step` on every call."""

    def __init__(self, step: float = 1.0) -> None:
        self._value = 0.0
        self._step = step

    def __call__(self) -> float:
        value = self._value
        self._value += self._step
        return value


def test_full_sweep_stage_ordering_and_winner_selection(fixture_text):
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx()
    search_plan = planner.plan(chip, ctx.budget)
    runner = RecordingRunner()

    result = engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )

    trial_ids = [t.trial_id for t in result.trials]
    assert trial_ids == [
        "A1",
        "A2",
        "A3",
        "A4",
        "B1",
        "B2",
        "B3",
        "B4",
        "B5",
        "B6",
        "C1",
        "C2",
        "C3",
        "confirm-baseline",
        "confirm-best",
    ]
    assert result.budget_truncated is False
    assert result.dropped_stages == []


def test_run_records_load_snapshots_at_sweep_start_and_end(fixture_text):
    """Feature F-A: `collect_load` is called once at sweep start and once at sweep end, and
    both snapshots land in the returned SweepResult."""
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx()
    search_plan = planner.plan(chip, ctx.budget)
    runner = RecordingRunner()
    calls: list[str] = []

    def counting_collect_load():
        calls.append("call")
        return LoadSnapshot(
            loadavg_1m=float(len(calls)), loadavg_5m=0.0, loadavg_15m=0.0, top_processes=[]
        )

    result = engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=counting_collect_load,
    )

    assert len(calls) == 2
    assert result.load_before == LoadSnapshot(
        loadavg_1m=1.0, loadavg_5m=0.0, loadavg_15m=0.0, top_processes=[]
    )
    assert result.load_after == LoadSnapshot(
        loadavg_1m=2.0, loadavg_5m=0.0, loadavg_15m=0.0, top_processes=[]
    )


def test_stage_a_winner_is_highest_threads_for_this_score_fn(fixture_text):
    # Call order (16 total, per test_full_sweep_stage_ordering_and_winner_selection):
    # [0]=baseline(None), [1:5]=Stage A, [5:11]=Stage B, [11:14]=Stage C, [14:16]=confirm.
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx()
    search_plan = planner.plan(chip, ctx.budget)
    runner = RecordingRunner()

    engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )

    stage_a_calls = runner.calls[1:5]
    assert {cfg.threads for cfg in stage_a_calls} == {6, 8, 9, 10}
    # Stage B configs must have threads overridden to Stage A's winner (10, the highest).
    stage_b_calls = runner.calls[5:11]
    assert all(cfg.threads == 10 for cfg in stage_b_calls)


def test_stage_c_configs_inherit_threads_fa_kv_from_a_and_b_winners(fixture_text):
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx()
    search_plan = planner.plan(chip, ctx.budget)
    runner = RecordingRunner()

    engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )

    stage_c_calls = runner.calls[11:14]
    assert len(stage_c_calls) == 3
    for cfg in stage_c_calls:
        assert cfg.threads == 10
        assert cfg.flash_attn == "on"
        assert cfg.cache_type_k == "q4_0"


def test_best_and_speedup_reflect_confirm_pass(fixture_text):
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx()
    search_plan = planner.plan(chip, ctx.budget)
    runner = RecordingRunner()

    result = engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )

    assert result.best.trial_id == "confirm-best"
    assert result.baseline.trial_id == "confirm-baseline"
    # baseline gen_ts=50, best gen_ts = 60+10+50=120 -> speedup = (120-50)/50*100 = 140%
    assert result.speedup_gen_pct == pytest.approx(140.0)
    # baseline prefill=100, best prefill=200 (Stage C winner) -> speedup=100%
    assert result.speedup_prefill_pct == pytest.approx(100.0)


def test_early_stop_prunes_remaining_stage_a_candidates(fixture_text):
    # Stage A candidates for M1 Max are [6, 8, 9, 10] (PLAN.md section 4.1 example). Candidate
    # #1 (threads=6) sets a dominant precedent; candidate #2 (threads=8) fails to beat it, so
    # candidates #3/#4 (threads=9, 10) are pruned without ever being benched.
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx()
    search_plan = planner.plan(chip, ctx.budget)

    def score(cfg):
        if cfg is None:
            return 10.0, 50.0
        if cfg.threads == 6:
            return 1000.0, 100.0
        return 20.0, 100.0

    runner = RecordingRunner(score_fn=score)
    result = engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )

    stage_a_trials = [t for t in result.trials if t.stage == "A"]
    assert [t.status for t in stage_a_trials] == ["ok", "ok", "pruned", "pruned"]
    # Only the baseline + 2 Stage A candidates were actually benched before Stage B begins.
    assert len(runner.calls) < 16  # fewer than the full 16-call worst case (PLAN.md section 4.1)


def test_bench_error_does_not_crash_and_is_recorded(fixture_text):
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx()
    search_plan = planner.plan(chip, ctx.budget)
    call_count = {"n": 0}

    def run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        call_count["n"] += 1
        if call_count["n"] == 2:  # first Stage A candidate errors
            raise BenchRunError("simulated failure")
        gen_ts, prefill_ts = _score(cfg)
        return [
            BenchSample(
                test_type="pp",
                n_prompt=prompt_n,
                n_gen=0,
                avg_ts=prefill_ts,
                stddev_ts=1.0,
                samples_ts=[prefill_ts],
            ),
            BenchSample(
                test_type="tg",
                n_prompt=0,
                n_gen=gen_n,
                avg_ts=gen_ts,
                stddev_ts=1.0,
                samples_ts=[gen_ts],
            ),
        ]

    result = engine.run(
        search_plan,
        ctx,
        run_bench=run_bench,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )
    errored = [t for t in result.trials if t.status == "error"]
    assert len(errored) == 1
    assert errored[0].error == "simulated failure"
    assert result.best.status == "ok"  # engine still finds a winner among the rest


def test_budget_truncation_drops_stage_c_then_confirm(fixture_text, monkeypatch):
    """A moderate budget that comfortably covers baseline+A+B but not C+confirm: isolates the
    "confirm dropped LAST, after C" ordering guarantee (PLAN.md section 4.4's truncation order)
    without also tripping H6's new mid-stage A/B pruning (see
    test_extreme_budget_also_truncates_stage_a_and_b_mid_stage below for that scenario)."""
    monkeypatch.setattr(time, "monotonic", TickingClock(step=1.0))
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx(total_seconds=40, max_cooldown_s=0.0)
    search_plan = planner.plan(chip, ctx.budget)
    runner = RecordingRunner()

    result = engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )

    assert result.budget_truncated is True
    assert result.dropped_stages == ["C", "confirm"]  # confirm dropped LAST, after C
    stage_a_trials = [t for t in result.trials if t.stage == "A"]
    stage_b_trials = [t for t in result.trials if t.stage == "B"]
    assert all(t.status == "ok" for t in stage_a_trials)  # A ran to completion, untouched
    assert all(t.status == "ok" for t in stage_b_trials)  # B ran to completion, untouched
    # H6: Stage C's own budget_tracker also stops starting new candidates mid-stage now, so not
    # every C candidate is necessarily pruned (some may complete before the cutoff) -- what
    # matters is that C didn't finish and confirm never started.
    stage_c_trials = [t for t in result.trials if t.stage == "C"]
    assert any(t.status == "pruned" for t in stage_c_trials)
    assert not any(t.stage == "confirm" for t in result.trials)
    # Degraded case: baseline field falls back to the initial baseline (no confirm pair ran).
    assert result.baseline.trial_id == "baseline"


def test_extreme_budget_also_truncates_stage_a_and_b_mid_stage(fixture_text, monkeypatch):
    """Robustness review H6: with a budget so tiny that even a single trial's estimated cost
    blows it, Stage A and B must ALSO stop starting new candidates (previously they always ran
    to completion regardless of budget -- a measured 7.5x overrun on a 3s budget)."""
    monkeypatch.setattr(time, "monotonic", TickingClock(step=50.0))
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx(total_seconds=10, max_cooldown_s=20.0)  # tiny budget, real cooldown cost
    search_plan = planner.plan(chip, ctx.budget)
    runner = RecordingRunner()

    result = engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )

    assert result.budget_truncated is True
    # H6: A and B are cut short mid-stage too now, not just C/confirm -- confirm is still last.
    assert result.dropped_stages == ["A", "B", "C", "confirm"]
    assert any(t.stage == "A" and t.status == "pruned" for t in result.trials)
    assert not any(t.stage == "confirm" for t in result.trials)
    assert result.baseline.trial_id == "baseline"


def test_generous_budget_never_truncates(fixture_text, monkeypatch):
    monkeypatch.setattr(time, "monotonic", TickingClock(step=0.01))
    chip = _m1_max_chip(fixture_text)
    ctx = _make_ctx(total_seconds=900, max_cooldown_s=20.0)
    search_plan = planner.plan(chip, ctx.budget)
    runner = RecordingRunner()

    result = engine.run(
        search_plan,
        ctx,
        run_bench=runner,
        cooldown_fn=_fake_cooldown,
        collect_load=_fake_collect_load,
    )

    assert result.budget_truncated is False
    assert result.dropped_stages == []
    assert any(t.stage == "confirm" for t in result.trials)
