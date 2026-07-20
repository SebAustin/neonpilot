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


def test_render_html_escapes_numeric_and_bool_fields(sample_sweep_result, sample_chip_report):
    """SECURITY.md F9: numeric/bool fields (config.threads, ISA `present`, fast-path `active`)
    must be escaped too, not just string fields -- belt-and-braces on top of F1's hydration
    type-checking. Dataclasses don't enforce field types at construction time, so a directly
    constructed (not hydrated-from-JSON) object with markup smuggled into a declared bool/int
    field is exactly the scenario F1 closes at the hydration boundary; this proves the
    renderer itself is *also* safe even if that boundary were ever bypassed."""
    import dataclasses

    from neonpilot.models import FastPathNote

    hostile_isa = dict(sample_chip_report.isa)
    hostile_isa["neon"] = "<img src=x onerror=alert(1)>"  # type: ignore[assignment]
    hostile_note = FastPathNote(
        feature="dotprod",
        kernel="k",
        active="<b>true</b>",
        why="ok",  # type: ignore[arg-type]
    )
    hostile_chip = dataclasses.replace(
        sample_chip_report, isa=hostile_isa, fast_paths=[hostile_note]
    )

    hostile_trial = dataclasses.replace(
        sample_sweep_result.best,
        config=dataclasses.replace(sample_sweep_result.best.config, threads="<i>8</i>"),  # type: ignore[arg-type]
    )
    hostile_result = dataclasses.replace(
        sample_sweep_result, best=hostile_trial, trials=[hostile_trial]
    )

    rendered = render_html(hostile_result, hostile_chip)

    assert "<img src=x onerror=alert(1)>" not in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "<b>true</b>" not in rendered
    assert "&lt;b&gt;true&lt;/b&gt;" in rendered
    assert "<i>8</i>" not in rendered
    assert "&lt;i&gt;8&lt;/i&gt;" in rendered
