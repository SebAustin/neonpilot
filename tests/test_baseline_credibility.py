"""Regression tests for the baseline-credibility investigation (docs/dev/build-notes.md item 15).

A real 180s CI-scale run reported `speedup_gen_pct=+394.2%` on SmolLM2-135M -- implausible for
thread/KV/flash-attn tuning alone (expected magnitude: single to low-double-digit %). This file
locks in the specific bug classes that investigation ruled out, plus the credibility guard added
as a result:

1. The baseline trial's displayed `RuntimeConfig` must match llama.cpp's OWN resolved defaults
   for the M1 Max reference machine (threads = P-core count, kv f16, flash_attn auto, batch
   2048/512) -- a "wrong thread count" bug (e.g. baseline pinned to 1 thread) would make any
   comparison meaningless.
2. `search/_trial.execute_trial` must classify `pp` rows into `.prefill` and `tg` rows into
   `.generation` regardless of the ORDER llama-bench returns them in -- an index-based mix-up
   would silently swap prefill/generation throughput and fabricate a speedup number.
3. When the sweep's own statistical-dominance test (the same one used for early-stopping,
   PLAN.md section 4.3) says the measured speedup does NOT clear the noise band, the report and
   CLI must say so instead of presenting a bare, authoritative-looking percentage.

Root-cause finding (see build-notes.md item 15 for the full writeup): no defect was found in the
baseline measurement or pp/tg parsing logic itself (both verified against a real llama-bench
invocation and the existing test suite). The reproducible mechanism is measurement noise: with
`--reps` below the documented minimum of 3, and/or thermal or system-load variance on the dev
laptop, a single unlucky baseline rep or lucky candidate rep can differ by 3x+ within one config
(see the real captured samples in build-notes.md), which arithmetically produces a triple-digit
"speedup" that is pure noise, not signal. The fix is a credibility guard, not a math fix: never
present that number without a caveat.
"""

from __future__ import annotations

import dataclasses

import pytest

from neonpilot.bench.stats import dominates
from neonpilot.models import (
    BenchSample,
    CooldownPolicy,
    SweepBudget,
    SweepContext,
)
from neonpilot.probe.macos_sysctl import read_chip_report
from neonpilot.report.html import render_html
from neonpilot.report.markdown import render_markdown
from neonpilot.search._trial import BASELINE_DISPLAY_CONFIG, execute_trial


def _m1_max_chip(fixture_text):
    return read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))


def _ctx(**overrides) -> SweepContext:
    defaults = {
        "binary": "fake-bin",
        "model_path": "model.gguf",
        "model_class": "test-model",
        "out_dir": "/tmp/neonpilot-test",
        "budget": SweepBudget(total_seconds=180, reps=2, prompt_n=64, gen_n=32),
        "cooldown": CooldownPolicy(
            target_temp_c=None, max_cooldown_s=0.0, fixed_delay_s=0.0, idle_skip=True
        ),
        "timeout_s": 30,
        "llama_cpp_commit": "deadbeef",
    }
    defaults.update(overrides)
    return SweepContext(**defaults)


def _pp(avg_ts: float, stddev_ts: float = 1.0) -> BenchSample:
    return BenchSample(
        test_type="pp",
        n_prompt=64,
        n_gen=0,
        avg_ts=avg_ts,
        stddev_ts=stddev_ts,
        samples_ts=[avg_ts],
    )


def _tg(avg_ts: float, stddev_ts: float = 1.0) -> BenchSample:
    return BenchSample(
        test_type="tg",
        n_prompt=0,
        n_gen=32,
        avg_ts=avg_ts,
        stddev_ts=stddev_ts,
        samples_ts=[avg_ts],
    )


# --- 1. Baseline RuntimeConfig must equal llama.cpp's real, verified defaults -----------------


def test_baseline_display_config_matches_llama_cpp_defaults_on_m1_max(fixture_text):
    """PLAN.md section 0/3.3/9: llama-bench with no tuning flags resolves to threads=8 (the
    M1 Max P-core count), kv f16, flash_attn auto, batch 2048, ubatch 512 -- verified directly
    against the real pinned binary (spike S4). A regression here (e.g. threads silently pinned
    to 1) would invalidate every baseline-vs-tuned comparison."""
    chip = _m1_max_chip(fixture_text)

    assert BASELINE_DISPLAY_CONFIG.threads == chip.p_cores == 8
    assert BASELINE_DISPLAY_CONFIG.cache_type_k == "f16"
    assert BASELINE_DISPLAY_CONFIG.cache_type_v == "f16"
    assert BASELINE_DISPLAY_CONFIG.flash_attn == "auto"
    assert BASELINE_DISPLAY_CONFIG.batch == 2048
    assert BASELINE_DISPLAY_CONFIG.ubatch == 512


def test_baseline_argv_omits_every_tuning_flag():
    """The baseline call must omit -t/-ctk/-ctv/-fa/-b/-ub entirely (PLAN.md section 3.3) so
    llama.cpp resolves its own defaults -- passing e.g. `-t 1` for "baseline" would understate
    real-world default performance and inflate the tuned speedup artificially."""
    from neonpilot.bench.runner import build_argv

    argv = build_argv("bin", "model.gguf", None, reps=3, prompt_n=512, gen_n=128)

    for flag in ("-t", "-ctk", "-ctv", "-fa", "-b", "-ub"):
        assert flag not in argv, f"baseline argv must omit {flag}: {argv}"


# --- 2. pp/tg classification must never mix up prefill and generation -------------------------


def test_execute_trial_never_mixes_up_pp_and_tg_regardless_of_row_order(fixture_text):
    """A pp row (n_prompt>0) must always land in `.prefill`, a tg row (n_gen>0) in
    `.generation` -- checked with BOTH row orderings, since an index-based (not type-based)
    assignment bug would silently swap them and fabricate a speedup number."""
    ctx = _ctx()

    def run_bench_pp_first(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        return [_pp(100.0), _tg(20.0)]

    def run_bench_tg_first(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        return [_tg(20.0), _pp(100.0)]

    for run_bench in (run_bench_pp_first, run_bench_tg_first):
        trial, _duration = execute_trial(
            ctx=ctx,
            cfg=None,
            stage="baseline",
            trial_id="baseline",
            run_bench=run_bench,
            thermal_snapshot=None,
        )
        assert trial.prefill is not None
        assert trial.prefill.test_type == "pp"
        assert trial.prefill.avg_ts == pytest.approx(100.0)
        assert trial.generation is not None
        assert trial.generation.test_type == "tg"
        assert trial.generation.avg_ts == pytest.approx(20.0)


def test_execute_trial_a_pp_only_response_never_populates_generation(fixture_text):
    """A response containing only a pp row must leave `.generation` as None, never fall back to
    the prefill sample (which would silently corrupt the primary objective, PLAN.md section 4.2)."""
    ctx = _ctx()

    def run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        return [_pp(100.0)]

    trial, _duration = execute_trial(
        ctx=ctx,
        cfg=None,
        stage="baseline",
        trial_id="baseline",
        run_bench=run_bench,
        thermal_snapshot=None,
    )
    assert trial.prefill is not None
    assert trial.generation is None


def test_execute_trial_a_tg_only_response_never_populates_prefill(fixture_text):
    ctx = _ctx()

    def run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s):
        return [_tg(20.0)]

    trial, _duration = execute_trial(
        ctx=ctx,
        cfg=None,
        stage="baseline",
        trial_id="baseline",
        run_bench=run_bench,
        thermal_snapshot=None,
    )
    assert trial.generation is not None
    assert trial.prefill is None


# --- 3. Statistical-significance guard on the headline speedup number -------------------------


def test_low_confidence_note_appears_when_speedup_is_within_noise(
    sample_sweep_result, sample_chip_report
):
    """When baseline and best have overlapping confidence bands (per the same `dominates()` the
    engine uses for early-stopping), both the Markdown and HTML reports must flag the headline
    speedup as unproven rather than presenting a bare percentage."""
    noisy_baseline = dataclasses.replace(
        sample_sweep_result.baseline,
        generation=_tg(50.0, stddev_ts=40.0),
    )
    noisy_best = dataclasses.replace(
        sample_sweep_result.best,
        generation=_tg(55.0, stddev_ts=40.0),
    )
    noisy_result = dataclasses.replace(
        sample_sweep_result, baseline=noisy_baseline, best=noisy_best
    )
    assert not dominates(noisy_result.best, noisy_result.baseline)

    md = render_markdown(noisy_result, sample_chip_report)
    assert "Statistical caution" in md

    doc = render_html(noisy_result, sample_chip_report)
    assert "Statistical caution" in doc


def test_low_confidence_note_absent_when_speedup_clearly_dominates(
    sample_sweep_result, sample_chip_report
):
    """The default fixture's confirm pass (40 t/s -> 60 t/s, stddev=1.0 each) clearly dominates,
    so neither report should carry the low-confidence caveat -- it must not fire on every run."""
    assert dominates(sample_sweep_result.best, sample_sweep_result.baseline)

    md = render_markdown(sample_sweep_result, sample_chip_report)
    assert "Statistical caution" not in md

    doc = render_html(sample_sweep_result, sample_chip_report)
    assert "Statistical caution" not in doc


# --- 4. Real llama.cpp defaults, captured directly from the pinned binary (fixture) -----------


def test_real_llama_bench_fixture_confirms_m1_max_defaults(fixture_text):
    """Cross-check against the real captured `llama-bench -o json` fixture (spike S4): even
    when a config IS passed (`-t 8 -ctk f16 ...`), the resolved JSON fields must match what
    BASELINE_DISPLAY_CONFIG assumes for "no flags passed" on this exact reference machine --
    otherwise the display config and the real resolved config could silently diverge."""
    import json

    rows = json.loads(fixture_text("llama_bench_smollm2.json"))
    for row in rows:
        assert row["n_threads"] == BASELINE_DISPLAY_CONFIG.threads
        assert row["type_k"] == BASELINE_DISPLAY_CONFIG.cache_type_k
        assert row["type_v"] == BASELINE_DISPLAY_CONFIG.cache_type_v
        assert row["n_batch"] == BASELINE_DISPLAY_CONFIG.batch
        assert row["n_ubatch"] == BASELINE_DISPLAY_CONFIG.ubatch
