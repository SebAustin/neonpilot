"""Unit tests for bench/thermal.py's cooldown policy, using injected probe/sleep functions.

No real sleeping or powermetrics invocation happens here -- probe_temp_c and sleep_fn are
dependency-injected so the adaptive/idle-skip/fallback branches are all deterministic.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from neonpilot.bench.thermal import _adaptive_cooldown, cooldown, default_probe_temp_c
from neonpilot.models import CooldownPolicy


def test_adaptive_cooldown_raises_value_error_when_target_temp_c_is_none():
    """Carried-over LOW: this used to be a bare `assert target is not None` -- stripped
    entirely under `python -O`, silently turning an invariant violation into a confusing
    `TypeError` from comparing against `None` instead of a clear, always-enforced error."""
    policy = CooldownPolicy(
        target_temp_c=None, max_cooldown_s=20.0, fixed_delay_s=20.0, idle_skip=True
    )
    with pytest.raises(ValueError, match="target_temp_c"):
        _adaptive_cooldown(policy, 50.0, lambda: 50.0, lambda s: None)


def test_idle_skip_when_already_below_target():
    policy = CooldownPolicy(
        target_temp_c=60.0, max_cooldown_s=20.0, fixed_delay_s=20.0, idle_skip=True
    )
    snapshot = cooldown(policy, probe_temp_c=lambda: 45.0, sleep_fn=lambda s: None)

    assert snapshot.source == "idle-skip"
    assert snapshot.cooldown_s == 0.0
    assert snapshot.cpu_temp_c == 45.0


def test_adaptive_wait_until_below_target():
    readings = iter([80.0, 70.0, 55.0])
    slept = []

    def fake_probe():
        return next(readings)

    snapshot = cooldown(
        CooldownPolicy(target_temp_c=60.0, max_cooldown_s=20.0, fixed_delay_s=20.0, idle_skip=True),
        probe_temp_c=fake_probe,
        sleep_fn=slept.append,
    )

    assert snapshot.source == "powermetrics"
    assert snapshot.cpu_temp_c == 55.0
    assert snapshot.cooldown_s == 2.0
    assert slept == [1.0, 1.0]


def test_adaptive_wait_hits_max_cooldown_cap():
    def always_hot():
        return 90.0

    snapshot = cooldown(
        CooldownPolicy(target_temp_c=60.0, max_cooldown_s=3.0, fixed_delay_s=20.0, idle_skip=True),
        probe_temp_c=always_hot,
        sleep_fn=lambda s: None,
    )

    assert snapshot.source == "powermetrics"
    assert snapshot.cooldown_s == 3.0
    assert snapshot.cpu_temp_c == 90.0


def test_fixed_fallback_when_no_sensor_available():
    snapshot = cooldown(
        CooldownPolicy(target_temp_c=None, max_cooldown_s=20.0, fixed_delay_s=5.0, idle_skip=True),
        probe_temp_c=lambda: None,
        sleep_fn=lambda s: None,
    )

    assert snapshot.source == "elapsed-fallback"
    assert snapshot.cpu_temp_c is None
    assert snapshot.cooldown_s == 5.0


def test_fixed_fallback_capped_by_max_cooldown():
    snapshot = cooldown(
        CooldownPolicy(target_temp_c=None, max_cooldown_s=2.0, fixed_delay_s=20.0, idle_skip=True),
        probe_temp_c=lambda: None,
        sleep_fn=lambda s: None,
    )
    assert snapshot.cooldown_s == 2.0


def test_probe_returns_none_falls_back_to_fixed_delay():
    """target_temp_c is set but the sensor is unavailable this call -> fixed fallback."""
    snapshot = cooldown(
        CooldownPolicy(target_temp_c=60.0, max_cooldown_s=20.0, fixed_delay_s=4.0, idle_skip=True),
        probe_temp_c=lambda: None,
        sleep_fn=lambda s: None,
    )
    assert snapshot.source == "elapsed-fallback"
    assert snapshot.cooldown_s == 4.0


def test_default_probe_temp_c_returns_none_when_powermetrics_missing(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("powermetrics not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert default_probe_temp_c() is None


def test_default_probe_temp_c_returns_none_on_nonzero_exit(monkeypatch):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="sudo required")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert default_probe_temp_c() is None


def test_default_probe_temp_c_parses_cpu_die_temperature(monkeypatch):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout="CPU die temperature: 42.50 C\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert default_probe_temp_c() == 42.50


def test_default_probe_temp_c_returns_none_when_line_absent(monkeypatch):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout="some other output\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert default_probe_temp_c() is None


def test_default_probe_temp_c_returns_none_on_timeout(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=3)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert default_probe_temp_c() is None
