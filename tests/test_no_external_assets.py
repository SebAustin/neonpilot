"""SC8: the HTML report must be self-contained -- zero external `http(s)://` asset fetches,
no CDN, no external fonts/scripts, so it opens correctly via `file://` with no network access.
"""

from __future__ import annotations

import re

from neonpilot.report.compare import render_compare_html
from neonpilot.report.html import render_html

_EXTERNAL_URL = re.compile(r"https?://", re.IGNORECASE)


def test_golden_report_has_no_external_urls(sample_sweep_result, sample_chip_report):
    rendered = render_html(sample_sweep_result, sample_chip_report)
    assert not _EXTERNAL_URL.search(rendered)


def test_golden_report_has_no_script_or_link_tags(sample_sweep_result, sample_chip_report):
    rendered = render_html(sample_sweep_result, sample_chip_report).lower()
    assert "<script" not in rendered
    assert "<link" not in rendered  # no external stylesheet/font <link> tags
    assert "cdn." not in rendered


def test_golden_report_css_is_inline_style_block(sample_sweep_result, sample_chip_report):
    rendered = render_html(sample_sweep_result, sample_chip_report)
    assert "<style>" in rendered
    assert rendered.count("<style>") == 1


def test_compare_report_has_no_external_urls(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    """F-B: compare.html must be just as self-contained as report.html (SC8)."""
    rendered = render_compare_html(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    )
    assert not _EXTERNAL_URL.search(rendered)


def test_compare_report_has_no_script_or_link_tags(
    sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
):
    rendered = render_compare_html(
        sample_sweep_result, sample_chip_report, sample_sweep_result_m5, sample_chip_report_m5
    ).lower()
    assert "<script" not in rendered
    assert "<link" not in rendered
    assert "cdn." not in rendered
