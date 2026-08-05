"""Tests for artifacts.py: run-dir creation, JSON (de)serialization, latest symlink."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neonpilot import artifacts
from neonpilot.probe.macos_sysctl import read_chip_report


def test_new_run_dir_creates_directory_without_touching_latest(tmp_path):
    """H2: `new_run_dir` must NOT repoint `latest` -- that only happens once the caller has
    finished writing the run's artifacts, via a separate `mark_latest()` call."""
    run_dir = artifacts.new_run_dir(tmp_path)
    assert run_dir.exists()
    assert run_dir.is_dir()
    assert run_dir.parent == tmp_path
    assert not (tmp_path / "latest").exists()


def test_mark_latest_creates_symlink_to_run_dir(tmp_path):
    run_dir = artifacts.new_run_dir(tmp_path)
    artifacts.mark_latest(run_dir)

    latest = tmp_path / "latest"
    assert latest.is_symlink()
    assert latest.resolve() == run_dir.resolve()


def test_mark_latest_repoints_atomically_from_a_prior_run(tmp_path):
    first = artifacts.new_run_dir(tmp_path)
    artifacts.mark_latest(first)
    second = artifacts.new_run_dir(tmp_path)
    artifacts.mark_latest(second)

    latest = tmp_path / "latest"
    assert latest.resolve() == second.resolve()
    # no leftover temp-named symlink from the atomic-replace dance
    assert not any(p.name.startswith(".latest.tmp.") for p in tmp_path.iterdir())


def test_mark_latest_warns_instead_of_silently_swallowing_oserror(tmp_path, monkeypatch):
    """H2: a symlink failure must be visible (RuntimeWarning), not a bare `except: pass`."""
    run_dir = artifacts.new_run_dir(tmp_path)

    def fake_symlink_to(self, *args, **kwargs):
        raise OSError("simulated symlink failure")

    monkeypatch.setattr("pathlib.Path.symlink_to", fake_symlink_to)
    with pytest.warns(RuntimeWarning, match="failed to update 'latest'"):
        artifacts.mark_latest(run_dir)


def test_new_run_dir_avoids_collisions_within_the_same_second(tmp_path, monkeypatch):
    import neonpilot.artifacts as artifacts_module

    class FrozenDatetime:
        @staticmethod
        def now(tz=None):
            import datetime as real_datetime

            return real_datetime.datetime(2026, 7, 20, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(artifacts_module, "datetime", FrozenDatetime)
    first = artifacts.new_run_dir(tmp_path)
    second = artifacts.new_run_dir(tmp_path)
    assert first != second
    assert first.exists()
    assert second.exists()


def test_dump_and_load_round_trip_a_dataclass(tmp_path, fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    path = tmp_path / "chip.json"
    artifacts.dump(chip, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["chip_name"] == "Apple M1 Max"
    assert path.read_text(encoding="utf-8").endswith("\n")

    rehydrated = artifacts.load_chip_report(path)
    assert rehydrated == chip


def test_dump_handles_a_list_of_dataclasses(tmp_path, fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    path = tmp_path / "fast_paths.json"
    artifacts.dump(chip.fast_paths, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert raw[0]["feature"] in {"neon", "dotprod", "i8mm", "sme", "sme2"}


def test_dump_output_is_stable_sorted_keys_two_space_indent(tmp_path, fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    path = tmp_path / "chip.json"
    artifacts.dump(chip, path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "{"
    assert any(line.startswith('  "chip_id"') for line in lines)


def test_load_returns_plain_dict(tmp_path, fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    path = tmp_path / "chip.json"
    artifacts.dump(chip, path)
    data = artifacts.load(path)
    assert isinstance(data, dict)
    assert data["chip_name"] == "Apple M1 Max"


def test_load_sweep_result_round_trips(tmp_path, sample_sweep_result):
    path = tmp_path / "result.json"
    artifacts.dump(sample_sweep_result, path)
    rehydrated = artifacts.load_sweep_result(path)
    assert rehydrated == sample_sweep_result


def test_load_sweep_result_hydrates_a_pre_load_telemetry_artifact():
    """Feature F-A backward-compat: a real, committed result.json written before
    `is_synthetic_config`/`baseline_threads`/`load_before`/`load_after` existed must still
    hydrate cleanly, defaulting the additive fields rather than raising."""
    path = (
        Path(__file__).parent.parent / "docs" / "results" / "m1-max-loaded-20260720" / "result.json"
    )
    result = artifacts.load_sweep_result(path)

    assert result.load_before is None
    assert result.load_after is None
    assert result.baseline.is_synthetic_config is False
    assert result.best.is_synthetic_config is False


def test_write_run_log_one_json_line_per_trial(tmp_path, sample_sweep_result):
    path = tmp_path / "run.log"
    artifacts.write_run_log(path, sample_sweep_result)
    lines = path.read_text(encoding="utf-8").splitlines()
    # baseline + every entry in .trials
    assert len(lines) == 1 + len(sample_sweep_result.trials)
    first_entry = json.loads(lines[0])
    assert first_entry["trial_id"] == sample_sweep_result.baseline.trial_id
    assert first_entry["gen_ts"] == sample_sweep_result.baseline.generation.avg_ts


def test_write_run_log_handles_pruned_trials_without_samples(tmp_path, sample_sweep_result):
    path = tmp_path / "run.log"
    artifacts.write_run_log(path, sample_sweep_result)
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    pruned = next(e for e in entries if e["status"] == "pruned")
    assert pruned["gen_ts"] is None
    assert pruned["prefill_ts"] is None
