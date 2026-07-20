"""Tests for probe/__init__.py's platform dispatch (probe_host)."""

from __future__ import annotations

import platform

import pytest

from neonpilot import probe


def test_probe_host_dispatches_to_macos(monkeypatch, fixture_text):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        probe.collector, "read_sysctl_text", lambda: fixture_text("sysctl_apple_m1_max.txt")
    )
    report = probe.probe_host()
    assert report.platform == "darwin"
    assert report.chip_name == "Apple M1 Max"


def test_probe_host_dispatches_to_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(probe.collector, "read_cpuinfo_text", lambda: "processor\t: 0\n")
    monkeypatch.setattr(probe.collector, "read_hwcaps", lambda: (0, 0))
    report = probe.probe_host()
    assert report.platform == "linux"


def test_probe_host_raises_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    with pytest.raises(NotImplementedError, match="Windows"):
        probe.probe_host()


def test_probe_host_runs_fast_on_this_machine():
    """FR1: probe must run in < 2 seconds with no model loaded."""
    import time

    start = time.monotonic()
    probe.probe_host()
    assert time.monotonic() - start < 2.0
