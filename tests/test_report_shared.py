"""Tests for report/_shared.py's winning_config_text (robustness review H3)."""

from __future__ import annotations

import dataclasses

from neonpilot.report._shared import winning_config_text


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
