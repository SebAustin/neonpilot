"""Unit tests for probe/collector.py: the sole subprocess/ctypes boundary in probe/.

subprocess.run and ctypes are monkeypatched -- this module is intentionally the only place
that talks to the live host, so these tests verify its error handling, not real hardware.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from neonpilot.probe import collector


def test_read_sysctl_text_returns_stdout(monkeypatch):
    def fake_run(argv, **kwargs):
        assert argv == ["sysctl", "-a"]
        assert kwargs.get("timeout") == collector._SYSCTL_TIMEOUT_S
        return SimpleNamespace(returncode=0, stdout="hw.physicalcpu: 10\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert collector.read_sysctl_text() == "hw.physicalcpu: 10\n"


def test_read_sysctl_text_raises_on_nonzero_exit(monkeypatch):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="permission denied"):
        collector.read_sysctl_text()


def test_read_cpuinfo_text_reads_proc_cpuinfo(tmp_path, monkeypatch):
    fake_cpuinfo = tmp_path / "cpuinfo"
    fake_cpuinfo.write_text("processor\t: 0\n")
    real_open = open

    def fake_open(path, *args, **kwargs):
        if path == "/proc/cpuinfo":
            return real_open(fake_cpuinfo, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    assert collector.read_cpuinfo_text() == "processor\t: 0\n"


def test_read_hwcaps_returns_zero_when_libc_not_found(monkeypatch):
    monkeypatch.setattr(collector.ctypes.util, "find_library", lambda name: None)
    assert collector.read_hwcaps() == (0, 0)


def test_read_hwcaps_returns_zero_on_missing_symbol(monkeypatch):
    class FakeLibc:
        def __getattr__(self, name):
            raise AttributeError(name)

    monkeypatch.setattr(collector.ctypes.util, "find_library", lambda name: "libc.fake")
    monkeypatch.setattr(collector.ctypes, "CDLL", lambda path: FakeLibc())
    assert collector.read_hwcaps() == (0, 0)
