"""Tests for preset/io.py: save/load registry layout, llama-bench invocation re-emission."""

from __future__ import annotations

import json

import pytest

from neonpilot.models import SCHEMA_VERSION, Preset, RuntimeConfig
from neonpilot.preset.io import invocation, load, save
from neonpilot.preset.schema import PresetValidationError


def _make_preset(sample_chip_report, **overrides) -> Preset:
    cfg = overrides.pop(
        "config",
        RuntimeConfig(
            threads=10,
            cache_type_k="q4_0",
            cache_type_v="q4_0",
            flash_attn="on",
            batch=4096,
            ubatch=2048,
        ),
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


def test_save_writes_chip_id_model_class_json(tmp_path, sample_chip_report):
    preset = _make_preset(sample_chip_report)
    path = save(preset, tmp_path)
    assert path == tmp_path / "apple-m1-max" / "smollm2-135m-instruct-q4_k_m.json"
    assert path.exists()


def test_save_output_is_stable_two_space_indent_sorted_keys(tmp_path, sample_chip_report):
    preset = _make_preset(sample_chip_report)
    path = save(preset, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    lines = text.splitlines()
    assert lines[0] == "{"
    data = json.loads(text)
    assert data["chip_id"] == "apple-m1-max"


def test_load_round_trips_a_saved_preset(tmp_path, sample_chip_report):
    preset = _make_preset(sample_chip_report)
    save(preset, tmp_path)
    loaded = load("apple-m1-max", "smollm2-135m-instruct-q4_k_m", tmp_path)
    assert loaded == preset


def test_load_raises_file_not_found_for_missing_preset(tmp_path):
    with pytest.raises(FileNotFoundError):
        load("nonexistent-chip", "nonexistent-model", tmp_path)


def test_load_rejects_a_saved_but_tampered_schema_version(tmp_path, sample_chip_report):
    preset = _make_preset(sample_chip_report)
    path = save(preset, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = "9.9.9"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PresetValidationError):
        load("apple-m1-max", "smollm2-135m-instruct-q4_k_m", tmp_path)


def test_invocation_emits_exact_llama_bench_command_line(sample_chip_report):
    cfg = RuntimeConfig(
        threads=6,
        cache_type_k="q8_0",
        cache_type_v="q8_0",
        flash_attn="off",
        batch=2048,
        ubatch=1024,
    )
    preset = _make_preset(sample_chip_report, config=cfg, reps=5)
    line = invocation(preset)
    assert line == (
        "llama-bench -m SmolLM2-135M-Instruct-Q4_K_M.gguf -o json -t 6 -ctk q8_0 -ctv q8_0 "
        "-fa off -b 2048 -ub 1024 -r 5"
    )


def test_invocation_shell_quotes_paths_with_spaces(sample_chip_report):
    preset = _make_preset(sample_chip_report, model_file="my model with spaces.gguf")
    line = invocation(preset)
    assert "'my model with spaces.gguf'" in line
