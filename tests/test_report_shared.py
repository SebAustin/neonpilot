"""Tests for report/_shared.py's winning_config_text (H3) and measurement_conditions_text (F-A)."""

from __future__ import annotations

import dataclasses

from neonpilot.models import LoadSnapshot, ProcessSample
from neonpilot.report._shared import measurement_conditions_text, winning_config_text


def test_winning_config_text_describes_a_measured_config(sample_sweep_result):
    text = winning_config_text(sample_sweep_result.best)
    assert text == "threads=10, cache_type=q4_0/q4_0, flash_attn=on, batch/ubatch=4096/2048"


def test_winning_config_text_flags_a_synthetic_config(sample_sweep_result):
    """H3: when tuning never legitimately beat the baseline, `best` is the baseline/confirm-
    baseline trial itself and `is_synthetic_config` is True -- the report must say so instead
    of presenting the reconstructed display config as a concretely-measured winner."""
    synthetic_best = dataclasses.replace(sample_sweep_result.best, is_synthetic_config=True)
    text = winning_config_text(synthetic_best)
    assert text == "defaults (as resolved by llama-bench; tuning did not beat the baseline)"
    assert "threads=" not in text


def test_measurement_conditions_text_returns_none_when_no_telemetry_recorded():
    """F-A: an artifact predating load telemetry (or a degraded best-effort collection) must
    let a report omit the line entirely, not render a blank/misleading one."""
    assert measurement_conditions_text(None) is None


def test_measurement_conditions_text_describes_loadavg_and_top_process():
    snapshot = LoadSnapshot(
        loadavg_1m=4.2,
        loadavg_5m=3.1,
        loadavg_15m=2.0,
        top_processes=[ProcessSample(pcpu=87.5, comm="stress-ng")],
    )
    text = measurement_conditions_text(snapshot)
    assert text == "loadavg(1m/5m/15m)=4.20/3.10/2.00, top process: stress-ng (87.5% CPU)"


def test_measurement_conditions_text_handles_no_top_processes():
    snapshot = LoadSnapshot(loadavg_1m=0.1, loadavg_5m=0.1, loadavg_15m=0.1, top_processes=[])
    text = measurement_conditions_text(snapshot)
    assert text == "loadavg(1m/5m/15m)=0.10/0.10/0.10, top process: n/a"
