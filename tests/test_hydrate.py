"""Tests for _hydrate.py: dict -> dataclass round trip via dataclasses.asdict / from_dict."""

from __future__ import annotations

import dataclasses

import pytest

from neonpilot._hydrate import from_dict
from neonpilot.probe.macos_sysctl import read_chip_report


def test_round_trips_chip_report(fixture_text):
    original = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    data = dataclasses.asdict(original)
    rehydrated = from_dict(type(original), data)
    assert rehydrated == original


def test_round_trips_nested_lists_of_dataclasses(fixture_text):
    original = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    data = dataclasses.asdict(original)
    rehydrated = from_dict(type(original), data)
    assert len(rehydrated.fast_paths) == len(original.fast_paths)
    assert all(isinstance(note.active, bool) for note in rehydrated.fast_paths)


def test_from_dict_returns_none_for_none_input():
    from neonpilot.models import ThermalSnapshot

    assert from_dict(ThermalSnapshot, None) is None


def test_from_dict_passes_through_non_dataclass_types():
    assert from_dict(str, "hello") == "hello"
    assert from_dict(int, 42) == 42


def test_from_dict_raises_on_missing_field():
    from neonpilot.models import ThermalSnapshot

    with pytest.raises(TypeError, match="missing required field"):
        from_dict(ThermalSnapshot, {"source": "idle-skip"})


def test_from_dict_raises_on_non_dict_input():
    from neonpilot.models import ThermalSnapshot

    with pytest.raises(TypeError, match="expected a dict"):
        from_dict(ThermalSnapshot, "not a dict")


def test_from_dict_rejects_string_in_int_field():
    """SECURITY.md F1: a preset/artifact is untrusted input -- a string smuggled into a
    declared `int` field (e.g. `threads`) must be rejected during hydration, not silently
    accepted or coerced."""
    from neonpilot.models import RuntimeConfig

    data = {
        "threads": "8; rm -rf /",
        "cache_type_k": "f16",
        "cache_type_v": "f16",
        "flash_attn": "auto",
        "batch": 2048,
        "ubatch": 512,
    }
    with pytest.raises(TypeError, match="expected int"):
        from_dict(RuntimeConfig, data)


def test_from_dict_rejects_bool_in_int_field():
    """`bool` is a subclass of `int` in Python -- a naive `isinstance(value, int)` check would
    silently accept `True`/`False` in an int field. Must be rejected explicitly."""
    from neonpilot.models import RuntimeConfig

    data = {
        "threads": True,
        "cache_type_k": "f16",
        "cache_type_v": "f16",
        "flash_attn": "auto",
        "batch": 2048,
        "ubatch": 512,
    }
    with pytest.raises(TypeError, match="expected int"):
        from_dict(RuntimeConfig, data)


def test_from_dict_rejects_int_in_str_field():
    from neonpilot.models import RuntimeConfig

    data = {
        "threads": 8,
        "cache_type_k": 16,
        "cache_type_v": "f16",
        "flash_attn": "auto",
        "batch": 2048,
        "ubatch": 512,
    }
    with pytest.raises(TypeError, match="expected str"):
        from_dict(RuntimeConfig, data)


def test_from_dict_rejects_string_in_float_field():
    from neonpilot.models import BenchSample

    data = {
        "test_type": "tg",
        "n_prompt": 0,
        "n_gen": 32,
        "avg_ts": "fast",
        "stddev_ts": 1.0,
        "samples_ts": [1.0],
    }
    with pytest.raises(TypeError, match="expected float"):
        from_dict(BenchSample, data)


def test_from_dict_accepts_int_for_float_field():
    """A hand-authored preset writing `40` instead of `40.0` for a float field is common and
    JSON-legal; widening int -> float is accepted (only the reverse direction is unsafe)."""
    from neonpilot.models import BenchSample

    data = {
        "test_type": "tg",
        "n_prompt": 0,
        "n_gen": 32,
        "avg_ts": 40,
        "stddev_ts": 1,
        "samples_ts": [40],
    }
    sample = from_dict(BenchSample, data)
    assert sample.avg_ts == 40.0
    assert isinstance(sample.avg_ts, float)


def test_from_dict_rejects_non_bool_in_bool_field():
    from neonpilot.models import ThermalSnapshot

    data = {"source": "idle-skip", "cpu_temp_c": None, "throttled": "yes", "cooldown_s": 0.0}
    with pytest.raises(TypeError, match="expected bool"):
        from_dict(ThermalSnapshot, data)


def test_from_dict_rejects_non_list_value_for_list_field():
    from neonpilot.models import BenchSample

    data = {
        "test_type": "tg",
        "n_prompt": 0,
        "n_gen": 32,
        "avg_ts": 1.0,
        "stddev_ts": 1.0,
        "samples_ts": "not-a-list",
    }
    with pytest.raises(TypeError, match="expected a list"):
        from_dict(BenchSample, data)


def test_from_dict_fills_missing_field_from_plain_default():
    """Robustness review H3/backward-compat: a JSON payload predating an additive field (e.g.
    an old result.json written before `TrialResult.is_synthetic_config` existed) must still
    hydrate, using the dataclass's own declared default rather than raising."""
    from neonpilot.models import RuntimeConfig, ThermalSnapshot, TrialResult

    cfg = RuntimeConfig(
        threads=8, cache_type_k="f16", cache_type_v="f16", flash_attn="auto", batch=2048, ubatch=512
    )
    trial = TrialResult(
        trial_id="A1",
        stage="A",
        config=cfg,
        prefill=None,
        generation=None,
        reps=3,
        started_at="2026-07-20T00:00:00Z",
        ended_at="2026-07-20T00:00:01Z",
        thermal=ThermalSnapshot(
            source="idle-skip", cpu_temp_c=None, throttled=None, cooldown_s=0.0
        ),
        status="ok",
        error=None,
    )
    data = dataclasses.asdict(trial)
    del data["is_synthetic_config"]  # simulate a pre-H3 artifact that predates this field

    rehydrated = from_dict(TrialResult, data)
    assert rehydrated.is_synthetic_config is False


def test_from_dict_fills_missing_field_from_default_factory():
    """Same lenient-default mechanism as above, but for a `default_factory=` field (none of
    neonpilot's real dataclasses currently use one, so this exercises the branch directly with
    a local fixture dataclass to keep it covered by regression tests)."""

    @dataclasses.dataclass(frozen=True)
    class _WithFactoryDefault:
        name: str
        tags: list[str] = dataclasses.field(default_factory=list)

    rehydrated = from_dict(_WithFactoryDefault, {"name": "x"})
    assert rehydrated.tags == []


def test_from_dict_rejects_non_dict_value_for_dict_field():
    """M6: a dict-typed field (e.g. ChipReport.isa) must reject a non-dict value outright,
    instead of accepting it and failing later with an obscure AttributeError deep inside a
    report renderer that assumes `.items()` works."""
    from neonpilot.models import ChipReport

    data = {
        "schema_version": "1.0.0",
        "probed_at": "2026-07-20T00:00:00Z",
        "platform": "darwin",
        "chip_name": "Apple M1 Max",
        "chip_id": "apple-m1-max",
        "cpu_brand": "Apple M1 Max",
        "p_cores": 8,
        "e_cores": 2,
        "total_cores": 10,
        "ram_gb": 64.0,
        "isa": "not-a-dict",
        "fast_paths": [],
        "raw": {},
    }
    with pytest.raises(TypeError, match="expected a dict"):
        from_dict(ChipReport, data)


def test_from_dict_validates_dict_value_types():
    """M6: not just the dict's own shape, but every value inside it, must match the declared
    value type -- a forged `"isa": {"i8mm": "yes"}` (string instead of bool) is rejected here."""
    from neonpilot.models import ChipReport

    data = {
        "schema_version": "1.0.0",
        "probed_at": "2026-07-20T00:00:00Z",
        "platform": "darwin",
        "chip_name": "Apple M1 Max",
        "chip_id": "apple-m1-max",
        "cpu_brand": "Apple M1 Max",
        "p_cores": 8,
        "e_cores": 2,
        "total_cores": 10,
        "ram_gb": 64.0,
        "isa": {"i8mm": "yes"},
        "fast_paths": [],
        "raw": {},
    }
    with pytest.raises(TypeError, match="expected bool"):
        from_dict(ChipReport, data)


def test_from_dict_accepts_well_formed_dict_field(fixture_text):
    original = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    data = dataclasses.asdict(original)
    rehydrated = from_dict(type(original), data)
    assert rehydrated.isa == original.isa
    assert isinstance(rehydrated.isa, dict)
    assert all(isinstance(v, bool) for v in rehydrated.isa.values())


def test_from_dict_handles_optional_nested_dataclass_field():
    from neonpilot.models import RuntimeConfig, ThermalSnapshot, TrialResult

    cfg = RuntimeConfig(
        threads=8, cache_type_k="f16", cache_type_v="f16", flash_attn="auto", batch=2048, ubatch=512
    )
    trial = TrialResult(
        trial_id="A1",
        stage="A",
        config=cfg,
        prefill=None,
        generation=None,
        reps=3,
        started_at="2026-07-20T00:00:00Z",
        ended_at="2026-07-20T00:00:01Z",
        thermal=ThermalSnapshot(
            source="idle-skip", cpu_temp_c=None, throttled=None, cooldown_s=0.0
        ),
        status="ok",
        error=None,
    )
    data = dataclasses.asdict(trial)
    rehydrated = from_dict(TrialResult, data)
    assert rehydrated == trial
    assert rehydrated.thermal.source == "idle-skip"
