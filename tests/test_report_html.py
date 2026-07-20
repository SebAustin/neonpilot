"""Golden-file test for report/html.py against a fixed, synthetic SweepResult."""

from __future__ import annotations

from pathlib import Path

from neonpilot.report.html import render_html

_GOLDEN_PATH = Path(__file__).parent / "golden" / "report.html"


def test_render_html_matches_golden_file(sample_sweep_result, sample_chip_report):
    rendered = render_html(sample_sweep_result, sample_chip_report)
    golden = _GOLDEN_PATH.read_text(encoding="utf-8")
    assert rendered == golden


def test_render_html_is_a_well_formed_document(sample_sweep_result, sample_chip_report):
    rendered = render_html(sample_sweep_result, sample_chip_report)
    assert rendered.startswith("<!DOCTYPE html>")
    assert "<html" in rendered
    assert "</html>" in rendered
    assert "<svg" in rendered
    assert "<style>" in rendered


def test_render_html_has_no_script_tags(sample_sweep_result, sample_chip_report):
    rendered = render_html(sample_sweep_result, sample_chip_report)
    assert "<script" not in rendered.lower()


def test_render_html_flags_truncation_caveat(sample_sweep_result, sample_chip_report):
    import dataclasses

    truncated = dataclasses.replace(
        sample_sweep_result, budget_truncated=True, dropped_stages=["C", "confirm"]
    )
    rendered = render_html(truncated, sample_chip_report)
    assert "Budget truncated" in rendered
    assert "Confirm pass skipped" in rendered


def test_render_html_escapes_untrusted_text_fields(sample_sweep_result, sample_chip_report):
    import dataclasses

    from neonpilot.models import FastPathNote

    hostile_note = FastPathNote(
        feature="neon", kernel="k", active=True, why="<script>alert(1)</script>"
    )
    hostile_chip = dataclasses.replace(sample_chip_report, fast_paths=[hostile_note])

    rendered = render_html(sample_sweep_result, hostile_chip)
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;" in rendered
