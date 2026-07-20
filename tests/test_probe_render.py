"""Tests for probe/render.py: --json emits the ChipReport schema; table mode doesn't crash."""

from __future__ import annotations

import json

from rich.console import Console

from neonpilot.probe.macos_sysctl import read_chip_report
from neonpilot.probe.render import render_json, render_table


def test_render_json_emits_full_chip_report_schema(fixture_text):
    report = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    console = Console(record=True, width=200)
    render_json(report, console)
    output = console.export_text()

    payload = json.loads(output)
    assert payload["chip_name"] == "Apple M1 Max"
    assert payload["isa"]["i8mm"] is False
    assert payload["isa"]["dotprod"] is True
    assert "fast_paths" in payload
    assert payload["schema_version"] == report.schema_version


def test_render_table_does_not_raise(fixture_text):
    report = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    console = Console(record=True, width=200)
    render_table(report, console)
    output = console.export_text()

    assert "Apple M1 Max" in output
    assert "dotprod" in output
