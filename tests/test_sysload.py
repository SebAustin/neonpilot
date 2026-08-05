"""Tests for bench/sysload.py: the ps -Ao pcpu,comm -r parser + collector (feature F-A)."""

from __future__ import annotations

import subprocess

import pytest

from neonpilot.bench.sysload import (
    SysloadError,
    collect_load_snapshot,
    parse_ps_output,
    read_ps_text,
)
from neonpilot.models import LoadSnapshot, ProcessSample


def test_parses_real_captured_ps_output(fixture_text):
    samples = parse_ps_output(fixture_text("ps_pcpu_comm_sample.txt"))

    assert len(samples) == 7  # header row skipped, 7 process rows kept
    assert samples[0] == ProcessSample(
        pcpu=136.4,
        comm="/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/"
        "Metadata.framework/Versions/A/Support/corespotlightd",
    )


def test_preserves_ps_r_descending_sort_order(fixture_text):
    samples = parse_ps_output(fixture_text("ps_pcpu_comm_sample.txt"))
    pcpu_values = [sample.pcpu for sample in samples]
    assert pcpu_values == sorted(pcpu_values, reverse=True)


def test_handles_comm_with_embedded_spaces(fixture_text):
    """A macOS app bundle path (e.g. a parenthesized helper-process suffix) contains spaces;
    only the first whitespace run (between %CPU and COMM) must be treated as the delimiter."""
    samples = parse_ps_output(fixture_text("ps_pcpu_comm_sample.txt"))
    renderer = next(s for s in samples if "Renderer" in s.comm)
    assert renderer.comm == (
        "/Applications/Claude.app/Contents/Frameworks/Claude Helper (Renderer).app/"
        "Contents/MacOS/Claude Helper (Renderer)"
    )


def test_skips_header_row_regardless_of_wording():
    text = "%CPU   COMMAND\n 12.0 some-proc\n"
    samples = parse_ps_output(text)
    assert samples == [ProcessSample(pcpu=12.0, comm="some-proc")]


def test_empty_ps_output_raises():
    with pytest.raises(SysloadError, match="empty"):
        parse_ps_output("")


def test_whitespace_only_ps_output_raises():
    with pytest.raises(SysloadError, match="empty"):
        parse_ps_output("   \n\n  \n")


def test_read_ps_text_raises_on_nonzero_exit(monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, returncode=1, stdout="", stderr="denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SysloadError, match="ps exited"):
        read_ps_text()


def test_read_ps_text_raises_on_oserror(monkeypatch):
    def fake_run(argv, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SysloadError, match="failed to run ps"):
        read_ps_text()


def test_collect_load_snapshot_degrades_to_empty_processes_on_ps_failure(monkeypatch):
    """Telemetry is best-effort: a `ps` failure must not raise out of collect_load_snapshot,
    only degrade the process list to empty -- loadavg is still real."""
    import neonpilot.bench.sysload as sysload_module

    monkeypatch.setattr(sysload_module.os, "getloadavg", lambda: (1.0, 2.0, 3.0))

    def fake_read_ps_text():
        raise SysloadError("simulated ps failure")

    monkeypatch.setattr(sysload_module, "read_ps_text", fake_read_ps_text)

    snapshot = collect_load_snapshot()
    assert snapshot == LoadSnapshot(
        loadavg_1m=1.0, loadavg_5m=2.0, loadavg_15m=3.0, top_processes=[]
    )


def test_collect_load_snapshot_caps_to_top_n_processes(monkeypatch):
    import neonpilot.bench.sysload as sysload_module

    monkeypatch.setattr(sysload_module.os, "getloadavg", lambda: (0.1, 0.2, 0.3))
    monkeypatch.setattr(
        sysload_module,
        "read_ps_text",
        lambda: "%CPU COMM\n 90.0 a\n 80.0 b\n 70.0 c\n 60.0 d\n",
    )

    snapshot = collect_load_snapshot()
    assert len(snapshot.top_processes) == 3
    assert [p.comm for p in snapshot.top_processes] == ["a", "b", "c"]
