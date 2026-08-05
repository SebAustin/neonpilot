"""Golden-file test for report/markdown.py against a fixed, synthetic SweepResult."""

from __future__ import annotations

from pathlib import Path

from neonpilot.report.markdown import render_markdown

_GOLDEN_PATH = Path(__file__).parent / "golden" / "report.md"


def test_render_markdown_matches_golden_file(sample_sweep_result, sample_chip_report):
    rendered = render_markdown(sample_sweep_result, sample_chip_report)
    golden = _GOLDEN_PATH.read_text(encoding="utf-8")
    assert rendered == golden


def test_render_markdown_contains_key_sections(sample_sweep_result, sample_chip_report):
    rendered = render_markdown(sample_sweep_result, sample_chip_report)
    assert "# neonpilot report" in rendered
    assert "## Chip ISA features" in rendered
    assert "## Baseline vs. tuned" in rendered
    assert "## Methodology" in rendered
    assert "## All trials" in rendered
    assert "i8mm ABSENT" in rendered  # M1 Max fast-path note, no overclaim


def test_render_markdown_flags_truncation_caveat(sample_sweep_result, sample_chip_report):
    import dataclasses

    truncated = dataclasses.replace(
        sample_sweep_result, budget_truncated=True, dropped_stages=["C", "confirm"]
    )
    rendered = render_markdown(truncated, sample_chip_report)
    assert "Budget truncated" in rendered
    assert "Methodology caveat" in rendered


def test_render_markdown_omits_caveat_when_not_truncated(sample_sweep_result, sample_chip_report):
    rendered = render_markdown(sample_sweep_result, sample_chip_report)
    assert "Methodology caveat" not in rendered


def test_render_markdown_labels_synthetic_winning_config(sample_sweep_result, sample_chip_report):
    """H3: a synthetic (baseline-reconstruction) winning config must never be rendered as a
    concretely-measured one."""
    import dataclasses

    synthetic_best = dataclasses.replace(sample_sweep_result.best, is_synthetic_config=True)
    truncated = dataclasses.replace(sample_sweep_result, best=synthetic_best)
    rendered = render_markdown(truncated, sample_chip_report)
    assert "defaults (as resolved by llama-bench" in rendered
    assert "Winning config: threads=" not in rendered


def test_render_markdown_is_pure_no_live_timestamps(sample_sweep_result, sample_chip_report):
    """Calling twice with the same inputs must produce byte-identical output."""
    first = render_markdown(sample_sweep_result, sample_chip_report)
    second = render_markdown(sample_sweep_result, sample_chip_report)
    assert first == second
