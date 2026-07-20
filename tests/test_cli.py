"""CLI wiring tests: help/version (M0, SC9) plus real optimize/report/apply behavior (M3/M4).

`optimize` end-to-end tests use a tiny fake llama-bench script (not the real pinned binary --
that's covered by the gated tests/test_optimize_integration.py) so they run fast and
deterministically in the default `pytest` invocation.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from neonpilot import __version__, artifacts
from neonpilot.cli import app
from neonpilot.models import SCHEMA_VERSION, RuntimeConfig
from neonpilot.preset.io import save as save_preset

runner = CliRunner()

_FAKE_LLAMA_BENCH = """#!/usr/bin/env python3
import json
import sys


def get(flag, default, cast):
    if flag in sys.argv:
        return cast(sys.argv[sys.argv.index(flag) + 1])
    return default


n_prompt = get("-p", 0, int)
n_gen = get("-n", 0, int)
rows = []
if n_prompt:
    pp_row = {"n_prompt": n_prompt, "n_gen": 0, "avg_ts": 50.0}
    pp_row.update({"stddev_ts": 1.0, "samples_ts": [50.0]})
    rows.append(pp_row)
if n_gen:
    tg_row = {"n_prompt": 0, "n_gen": n_gen, "avg_ts": 20.0}
    tg_row.update({"stddev_ts": 1.0, "samples_ts": [20.0]})
    rows.append(tg_row)
print(json.dumps(rows))
"""


@pytest.fixture
def fake_llama_bin(tmp_path) -> Path:
    script = tmp_path / "fake-llama-bench"
    script.write_text(_FAKE_LLAMA_BENCH, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_top_level_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "neonpilot" in result.stdout.lower()


@pytest.mark.parametrize("command", ["probe", "optimize", "report", "apply"])
def test_subcommand_help_exits_zero(command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_version_flag_prints_version_and_exits_zero():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_optimize_missing_model_exits_nonzero(tmp_path):
    result = runner.invoke(app, ["optimize", str(tmp_path / "does-not-exist.gguf")])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_optimize_missing_binary_exits_nonzero(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")
    result = runner.invoke(
        app,
        [
            "optimize",
            str(model),
            "--llama-bin",
            str(tmp_path / "no-such-binary"),
            "--out",
            str(tmp_path / "runs"),
        ],
    )
    assert result.exit_code != 0
    assert "llama-bench binary not found" in result.output.lower()


def test_optimize_end_to_end_writes_artifacts(tmp_path, fake_llama_bin):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")
    out_dir = tmp_path / "runs"

    result = runner.invoke(
        app,
        [
            "optimize",
            str(model),
            "--llama-bin",
            str(fake_llama_bin),
            "--out",
            str(out_dir),
            "--budget",
            "180",
            "--reps",
            "1",
            "--prompt-n",
            "8",
            "--gen-n",
            "8",
            "--cooldown-s",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "run dir:" in result.stdout

    run_dirs = [p for p in out_dir.iterdir() if p.is_dir() and p.name != "latest"]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    for filename in ("chip.json", "plan.json", "trials.json", "result.json", "run.log"):
        assert (run_dir / filename).exists(), filename

    result_data = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert result_data["schema_version"] == SCHEMA_VERSION
    assert result_data["model_class"] == "model"


def test_optimize_warns_when_reps_below_recommended_minimum(tmp_path, fake_llama_bin):
    """docs/dev/build-notes.md item 15: --reps below 3 is a documented risk factor for a
    noise-dominated, implausible speedup number -- the CLI must say so up front."""
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")

    result = runner.invoke(
        app,
        [
            "optimize",
            str(model),
            "--llama-bin",
            str(fake_llama_bin),
            "--out",
            str(tmp_path / "runs"),
            "--budget",
            "180",
            "--reps",
            "1",
            "--prompt-n",
            "8",
            "--gen-n",
            "8",
            "--cooldown-s",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "below the recommended minimum" in result.output


def test_optimize_does_not_warn_about_reps_when_at_recommended_minimum(tmp_path, fake_llama_bin):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")

    result = runner.invoke(
        app,
        [
            "optimize",
            str(model),
            "--llama-bin",
            str(fake_llama_bin),
            "--out",
            str(tmp_path / "runs"),
            "--budget",
            "180",
            "--reps",
            "3",
            "--prompt-n",
            "8",
            "--gen-n",
            "8",
            "--cooldown-s",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "below the recommended minimum" not in result.output


def test_optimize_warns_when_speedup_not_statistically_significant(tmp_path, fake_llama_bin):
    """The fake llama-bench script returns the same t/s regardless of config, so baseline and
    best are statistically tied -- the CLI must flag the speedup as unproven, not print a bare
    (and here, 0%) percentage as if it were a confident result."""
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")

    result = runner.invoke(
        app,
        [
            "optimize",
            str(model),
            "--llama-bin",
            str(fake_llama_bin),
            "--out",
            str(tmp_path / "runs"),
            "--budget",
            "180",
            "--reps",
            "3",
            "--prompt-n",
            "8",
            "--gen-n",
            "8",
            "--cooldown-s",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "may not be statistically significant" in result.output


def test_report_missing_run_dir_exits_nonzero(tmp_path):
    result = runner.invoke(app, ["report", "--run-dir", str(tmp_path / "nope")])
    assert result.exit_code != 0


def test_report_renders_markdown_and_html_from_existing_artifacts(
    tmp_path, sample_chip_report, sample_sweep_result
):
    run_dir = tmp_path / "a-run"
    run_dir.mkdir()
    artifacts.dump(sample_chip_report, run_dir / "chip.json")
    artifacts.dump(sample_sweep_result, run_dir / "result.json")

    result = runner.invoke(app, ["report", "--run-dir", str(run_dir)])
    assert result.exit_code == 0, result.stdout
    assert (run_dir / "report.md").exists()
    assert (run_dir / "report.html").exists()
    assert "neonpilot report" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_apply_with_valid_existing_preset_prints_invocation(tmp_path, sample_chip_report):
    from neonpilot.models import Preset

    cfg = RuntimeConfig(
        threads=10,
        cache_type_k="q4_0",
        cache_type_v="q4_0",
        flash_attn="on",
        batch=4096,
        ubatch=2048,
    )
    preset = Preset(
        schema_version=SCHEMA_VERSION,
        chip_id="apple-m1-max",
        chip=sample_chip_report,
        model_class="smollm2-135m-instruct-q4_k_m",
        model_file="SmolLM2-135M-Instruct-Q4_K_M.gguf",
        config=cfg,
        llama_cpp_commit="178a6c44937154dc4c4eff0d166f4a044c4fceba",
        generated_at="2026-07-20T00:00:00+00:00",
        baseline_gen_ts=40.0,
        baseline_prefill_ts=100.0,
        tuned_gen_ts=60.0,
        tuned_prefill_ts=180.0,
        tuned_gen_stddev=1.0,
        speedup_gen_pct=50.0,
        speedup_prefill_pct=80.0,
        server_flags="--threads 10",
        neonpilot_version="0.1.0",
        os_version="test",
        reps=3,
        cooldown_s=0.0,
    )
    path = save_preset(preset, tmp_path)

    result = runner.invoke(app, ["apply", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "schema_version: 1.0.0 (OK)" in result.stdout
    assert "llama-bench -m" in result.stdout


def test_apply_rejects_invalid_preset_schema(tmp_path):
    bad_preset = tmp_path / "bad.json"
    bad_preset.write_text(json.dumps({"schema_version": "0.0.1"}), encoding="utf-8")

    result = runner.invoke(app, ["apply", str(bad_preset)])
    assert result.exit_code != 0
    assert "invalid preset" in result.output.lower()


def test_apply_packages_a_run_as_new_preset(tmp_path, sample_chip_report, sample_sweep_result):
    run_dir = tmp_path / "a-run"
    run_dir.mkdir()
    artifacts.dump(sample_chip_report, run_dir / "chip.json")
    artifacts.dump(sample_sweep_result, run_dir / "result.json")
    presets_root = tmp_path / "presets"

    result = runner.invoke(
        app, ["apply", "--run-dir", str(run_dir), "--presets-root", str(presets_root)]
    )
    assert result.exit_code == 0, result.stdout

    saved = presets_root / "apple-m1-max" / "smollm2-135m-instruct-q4_k_m.json"
    assert saved.exists()
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["speedup_gen_pct"] == pytest.approx(50.0)


def test_apply_no_args_and_no_latest_run_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = runner.invoke(app, ["apply"])
    assert result.exit_code != 0


def test_apply_rejects_forged_chip_id_path_traversal(
    tmp_path, sample_chip_report, sample_sweep_result
):
    """SECURITY.md F2: a forged chip_id (e.g. from a shared/tampered run directory) must not
    let `apply` escape --presets-root; it should fail cleanly, not write outside the root."""
    import dataclasses

    forged_chip = dataclasses.replace(sample_chip_report, chip_id="../../etc")
    run_dir = tmp_path / "a-run"
    run_dir.mkdir()
    artifacts.dump(forged_chip, run_dir / "chip.json")
    artifacts.dump(sample_sweep_result, run_dir / "result.json")
    presets_root = tmp_path / "presets"
    presets_root.mkdir()

    result = runner.invoke(
        app, ["apply", "--run-dir", str(run_dir), "--presets-root", str(presets_root)]
    )

    assert result.exit_code != 0
    assert "refusing to save preset" in result.output.lower()
    # nothing escaped the tmp_path sandbox
    assert not (tmp_path.parent / "etc").exists()
    assert list(presets_root.iterdir()) == []


def test_apply_existing_preset_prints_server_flags_without_markup_injection(
    tmp_path, sample_chip_report
):
    """SECURITY.md F5: `server_flags` is untrusted preset content -- Rich markup/hyperlink
    syntax in it must be printed literally, never interpreted."""
    from neonpilot.models import Preset

    cfg = RuntimeConfig(
        threads=10,
        cache_type_k="q4_0",
        cache_type_v="q4_0",
        flash_attn="on",
        batch=4096,
        ubatch=2048,
    )
    injected = "[bold red]INJECTED[/bold red] [link=file:///etc/passwd]click me[/link]"
    preset = Preset(
        schema_version=SCHEMA_VERSION,
        chip_id="apple-m1-max",
        chip=sample_chip_report,
        model_class="smollm2-135m-instruct-q4_k_m",
        model_file="SmolLM2-135M-Instruct-Q4_K_M.gguf",
        config=cfg,
        llama_cpp_commit="178a6c44937154dc4c4eff0d166f4a044c4fceba",
        generated_at="2026-07-20T00:00:00+00:00",
        baseline_gen_ts=40.0,
        baseline_prefill_ts=100.0,
        tuned_gen_ts=60.0,
        tuned_prefill_ts=180.0,
        tuned_gen_stddev=1.0,
        speedup_gen_pct=50.0,
        speedup_prefill_pct=80.0,
        server_flags=injected,
        neonpilot_version="0.1.0",
        os_version="test",
        reps=3,
        cooldown_s=0.0,
    )
    path = save_preset(preset, tmp_path)

    result = runner.invoke(app, ["apply", str(path)])
    # Rich may soft-wrap long lines at the captured terminal width; normalize before matching
    # so the assertion isn't sensitive to exactly where a wrap lands.
    flat_output = result.output.replace("\n", "")

    assert result.exit_code == 0, result.output
    # the raw markup tokens must survive verbatim in the rendered output (never stripped or
    # interpreted as styling/hyperlink directives)
    assert "[bold red]INJECTED[/bold red]" in flat_output
    assert "[link=file:///etc/passwd]click me[/link]" in flat_output
