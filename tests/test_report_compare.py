"""Golden-file + behavior tests for report/compare.py (feature F-B).

Uses two synthetic (SweepResult, ChipReport) pairs -- an M1-like one (sample_sweep_result /
sample_chip_report) and an M5-like one (sample_sweep_result_m5 / sample_chip_report_m5, the
latter derived from the clearly-labeled-synthetic sysctl_apple_m5_synthetic.txt fixture).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from neonpilot.report.compare import render_compare_html, render_compare_markdown

_GOLDEN_MD = Path(__file__).parent / "golden" / "compare.md"
_GOLDEN_HTML = Path(__file__).parent / "golden" / "compare.html"


def test_render_compare_markdown_matches_golden_file(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    rendered = render_compare_markdown(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert rendered == _GOLDEN_MD.read_text(encoding="utf-8")


def test_render_compare_html_matches_golden_file(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    rendered = render_compare_html(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert rendered == _GOLDEN_HTML.read_text(encoding="utf-8")


def test_compare_markdown_highlights_feature_deltas(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    """M1 Max lacks i8mm/sme/sme2/bf16; the synthetic M5 fixture has them -- each such feature
    must be flagged as differing."""
    rendered = render_compare_markdown(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    for line in rendered.splitlines():
        if line.startswith("| i8mm ") or line.startswith("| sme "):
            assert line.rstrip().endswith("| yes |")
    # a feature both chips agree on (neon) must NOT be flagged
    neon_line = next(line for line in rendered.splitlines() if line.startswith("| neon "))
    assert neon_line.rstrip().endswith("|  |")


def test_compare_html_applies_delta_highlight_class_only_to_differing_rows(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    rendered = render_compare_html(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert '<tr class="delta-highlight"><td>i8mm</td>' in rendered
    assert '<tr class="delta-highlight"><td>sme2</td>' in rendered
    assert "<tr><td>neon</td>" in rendered  # agreed-upon feature, no highlight class


def test_compare_config_diff_table_flags_differing_fields(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    rendered = render_compare_markdown(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert "| threads | 10 | 14 | yes |" in rendered
    assert "| flash_attn | on | on |  |" in rendered  # both sides chose "on" -- no delta


def test_compare_markdown_shows_measurement_conditions_when_present(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    from neonpilot.models import LoadSnapshot, ProcessSample

    loaded_a = dataclasses.replace(
        sample_sweep_result,
        load_before=LoadSnapshot(
            loadavg_1m=2.0,
            loadavg_5m=1.5,
            loadavg_15m=1.0,
            top_processes=[ProcessSample(pcpu=55.0, comm="stress-ng")],
        ),
    )
    rendered = render_compare_markdown(
        loaded_a, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert "Measurement conditions: loadavg(1m/5m/15m)=2.00/1.50/1.00" in rendered
    assert "stress-ng (55.0% CPU)" in rendered


def test_compare_html_is_a_well_formed_self_contained_document(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    rendered = render_compare_html(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert rendered.startswith("<!DOCTYPE html>")
    assert "<svg" in rendered
    assert "<script" not in rendered.lower()


def test_compare_html_escapes_untrusted_process_name(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    """F-B respects the same escaping discipline as report/html.py (SECURITY.md F9)."""
    from neonpilot.models import LoadSnapshot, ProcessSample

    loaded_a = dataclasses.replace(
        sample_sweep_result,
        load_before=LoadSnapshot(
            loadavg_1m=1.0,
            loadavg_5m=1.0,
            loadavg_15m=1.0,
            top_processes=[ProcessSample(pcpu=1.0, comm="<script>evil</script>")],
        ),
    )
    rendered = render_compare_html(
        loaded_a, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert "<script>evil</script>" not in rendered
    assert "&lt;script&gt;evil&lt;/script&gt;" in rendered


def test_compare_labels_use_chip_name_by_default(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    rendered = render_compare_markdown(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert "compare: Apple M1 Max vs. Apple M5" in rendered


def test_compare_accepts_custom_labels(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    rendered = render_compare_markdown(
        sample_sweep_result,
        sample_chip_report,
        sample_sweep_result_m5,
        sample_chip_report_m5,
        label_a="Dev laptop",
        label_b="M5 (projected)",
    )
    assert "compare: Dev laptop vs. M5 (projected)" in rendered
