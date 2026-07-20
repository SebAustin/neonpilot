"""SC8: the HTML report must be self-contained -- zero external `http(s)://` asset fetches,
no CDN, no external fonts/scripts, so it opens correctly via `file://` with no network access.
"""

from __future__ import annotations

import re

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
