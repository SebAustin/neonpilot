"""Tests for search/_stage_runner.py: candidate-level early stopping (PLAN.md section 4.3)."""

from __future__ import annotations

from neonpilot.models import (
    BenchSample,
    CooldownPolicy,
    RuntimeConfig,
    SweepBudget,
    SweepContext,
    ThermalSnapshot,
)
from neonpilot.search._stage_runner import run_stage
from neonpilot.search._trial import execute_trial

_CTX = SweepContext(
    binary="fake-bin",
    model_path="fake.gguf",
    model_class="test",
    out_dir="/tmp/neonpilot-test",
    budget=SweepBudget(total_seconds=900, reps=1, prompt_n=64, gen_n=32),
    cooldown=CooldownPolicy(
        target_temp_c=None, max_cooldown_s=0.0, fixed_delay_s=0.0, idle_skip=True
    ),
    timeout_s=30,
    llama_cpp_commit="deadbeef",
)


def _cfg(threads: int) -> RuntimeConfig:
    return RuntimeConfig(
        threads=threads,
        cache_type_k="f16",
        cache_type_v="f16",
        flash_attn="auto",
        batch=2048,
        ubatch=512,
    )


def _fake_cooldown(policy):
    return ThermalSnapshot(source="idle-skip", cpu_temp_c=None, throttled=None, cooldown_s=0.0)


def _samples(gen_ts: float, stddev: float = 1.0) -> list[BenchSample]:
    return [
        BenchSample(
            test_type="pp", n_prompt=64, n_gen=0, avg_ts=100.0, stddev_ts=1.0, samples_ts=[100.0]
        ),
        BenchSample(
            test_type="tg",
            n_prompt=0,
            n_gen=32,
            avg_ts=gen_ts,
            stddev_ts=stddev,
            samples_ts=[gen_ts],
        ),
    ]


def _baseline_incumbent(gen_ts: float = 10.0):
    trial, _ = execute_trial(
        ctx=_CTX,
        cfg=None,
        stage="baseline",
        trial_id="baseline",
        run_bench=lambda *a, **kw: _samples(gen_ts),
        thermal_snapshot=None,
    )
    return trial


def test_run_stage_benches_every_candidate_when_none_dominate():
    candidates = [_cfg(4), _cfg(6), _cfg(8)]
    calls = []

    def run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        calls.append(cfg)
        return _samples(gen_ts=20.0 + cfg.threads)  # mild, non-dominant spread

    incumbent = _baseline_incumbent(gen_ts=5.0)
    trials, durations, best = run_stage(
        stage_name="A",
        candidates=candidates,
        ctx=_CTX,
        incumbent=incumbent,
        run_bench=run_bench,
        cooldown_fn=_fake_cooldown,
    )

    assert len(calls) == 3
    assert [t.status for t in trials] == ["ok", "ok", "ok"]
    assert best.config.threads == 8  # highest gen_ts (20+8=28)
    assert len(durations) == 3


def test_run_stage_prunes_remaining_after_dominant_candidate():
    """Dominance is checked against the running incumbent *after* each trial updates it: once
    candidate #1 sets a strong precedent and candidate #2 fails to beat it, candidate #3 (and
    beyond) is pruned without ever being benched."""
    candidates = [_cfg(4), _cfg(6), _cfg(8)]
    calls = []

    def run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        calls.append(cfg)
        if cfg.threads == 4:
            return _samples(gen_ts=1000.0, stddev=0.1)  # sets a dominant incumbent
        return _samples(gen_ts=20.0, stddev=0.1)  # clearly beaten by that incumbent

    incumbent = _baseline_incumbent(gen_ts=5.0)
    trials, durations, best = run_stage(
        stage_name="A",
        candidates=candidates,
        ctx=_CTX,
        incumbent=incumbent,
        run_bench=run_bench,
        cooldown_fn=_fake_cooldown,
    )

    assert len(calls) == 2  # candidate #3 was never benched
    assert [t.status for t in trials] == ["ok", "ok", "pruned"]
    assert best.config.threads == 4
    assert len(durations) == 2


def test_run_stage_pruned_trials_are_never_benched_but_retained():
    candidates = [_cfg(4), _cfg(6), _cfg(8)]
    calls = []

    def run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        calls.append(cfg)
        if cfg.threads == 4:
            return _samples(gen_ts=1000.0, stddev=0.01)
        return _samples(gen_ts=20.0, stddev=0.01)

    incumbent = _baseline_incumbent(gen_ts=5.0)
    trials, _, _ = run_stage(
        stage_name="B",
        candidates=candidates,
        ctx=_CTX,
        incumbent=incumbent,
        run_bench=run_bench,
        cooldown_fn=_fake_cooldown,
    )
    assert len(trials) == 3  # every candidate retained, incl. the pruned one
    assert trials[2].status == "pruned"
    assert trials[2].config.threads == 8
    assert trials[2].reps == 0
    assert cfg_threads_never_called(calls, 8)


def cfg_threads_never_called(calls, threads: int) -> bool:
    return all(cfg.threads != threads for cfg in calls)


def test_run_stage_marks_error_status_on_bench_failure():
    from neonpilot.bench.runner import BenchRunError

    def run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        raise BenchRunError("boom")

    incumbent = _baseline_incumbent(gen_ts=5.0)
    trials, durations, best = run_stage(
        stage_name="A",
        candidates=[_cfg(4)],
        ctx=_CTX,
        incumbent=incumbent,
        run_bench=run_bench,
        cooldown_fn=_fake_cooldown,
    )
    assert trials[0].status == "error"
    assert trials[0].error == "boom"
    assert best is incumbent  # incumbent unchanged; the errored trial can't win
    assert len(durations) == 1


def test_run_stage_extras_dropped_uses_zero_cooldown_snapshot():
    calls = {"cooldown_called": False}

    def cooldown_fn(policy):
        calls["cooldown_called"] = True
        return ThermalSnapshot(
            source="powermetrics", cpu_temp_c=50.0, throttled=False, cooldown_s=5.0
        )

    def run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        return _samples(gen_ts=10.0)

    incumbent = _baseline_incumbent(gen_ts=5.0)
    trials, _, _ = run_stage(
        stage_name="A",
        candidates=[_cfg(4)],
        ctx=_CTX,
        incumbent=incumbent,
        run_bench=run_bench,
        cooldown_fn=cooldown_fn,
        extras_dropped=True,
    )
    assert calls["cooldown_called"] is False
    assert trials[0].thermal.source == "idle-skip"
    assert trials[0].thermal.cooldown_s == 0.0
