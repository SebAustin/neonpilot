"""Tests for preset/schema.py: schema_version gating, missing-field rejection, round trip."""

from __future__ import annotations

import pytest

from neonpilot.models import SCHEMA_VERSION, Preset
from neonpilot.preset.schema import PresetValidationError, to_dict, validate


def _make_preset(sample_chip_report, **overrides) -> Preset:
    from neonpilot.models import RuntimeConfig

    cfg = RuntimeConfig(
        threads=10,
        cache_type_k="q4_0",
        cache_type_v="q4_0",
        flash_attn="on",
        batch=4096,
        ubatch=2048,
    )
    defaults = {
        "schema_version": SCHEMA_VERSION,
        "chip_id": "apple-m1-max",
        "chip": sample_chip_report,
        "model_class": "smollm2-135m-instruct-q4_k_m",
        "model_file": "SmolLM2-135M-Instruct-Q4_K_M.gguf",
        "config": cfg,
        "llama_cpp_commit": "178a6c44937154dc4c4eff0d166f4a044c4fceba",
        "generated_at": "2026-07-20T00:00:00+00:00",
        "baseline_gen_ts": 40.0,
        "baseline_prefill_ts": 100.0,
        "tuned_gen_ts": 60.0,
        "tuned_prefill_ts": 180.0,
        "tuned_gen_stddev": 1.0,
        "speedup_gen_pct": 50.0,
        "speedup_prefill_pct": 80.0,
        "server_flags": "--threads 10 --cache-type-k q4_0",
        "neonpilot_version": "0.1.0",
        "os_version": "macOS-26.5-arm64",
        "reps": 3,
        "cooldown_s": 0.0,
    }
    defaults.update(overrides)
    return Preset(**defaults)


def test_round_trip_to_dict_then_validate(sample_chip_report):
    preset = _make_preset(sample_chip_report)
    data = to_dict(preset)
    rehydrated = validate(data)
    assert rehydrated == preset


def test_validate_rejects_non_dict():
    with pytest.raises(PresetValidationError, match="must be a JSON object"):
        validate(["not", "a", "dict"])


def test_validate_rejects_schema_version_mismatch(sample_chip_report):
    preset = _make_preset(sample_chip_report)
    data = to_dict(preset)
    data["schema_version"] = "0.0.1"
    with pytest.raises(PresetValidationError, match="unsupported preset schema_version"):
        validate(data)


def test_validate_rejects_missing_required_field(sample_chip_report):
    preset = _make_preset(sample_chip_report)
    data = to_dict(preset)
    del data["config"]
    with pytest.raises(PresetValidationError, match="missing required fields"):
        validate(data)


def test_validate_rejects_malformed_nested_field(sample_chip_report):
    preset = _make_preset(sample_chip_report)
    data = to_dict(preset)
    data["config"] = "not-a-config-object"
    with pytest.raises(PresetValidationError, match="malformed preset"):
        validate(data)


def test_to_dict_is_a_plain_serializable_dict(sample_chip_report):
    preset = _make_preset(sample_chip_report)
    data = to_dict(preset)
    assert isinstance(data, dict)
    assert data["chip_id"] == "apple-m1-max"
    assert isinstance(data["chip"], dict)
    assert isinstance(data["config"], dict)


def test_validate_missing_schema_version_key_entirely(sample_chip_report):
    preset = _make_preset(sample_chip_report)
    data = to_dict(preset)
    del data["schema_version"]
    with pytest.raises(PresetValidationError, match="unsupported preset schema_version"):
        validate(data)
