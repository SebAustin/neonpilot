"""neonpilot Typer CLI: probe / optimize / report / apply.

This module owns argument parsing, Rich rendering, and exit codes only. No other module in
the package imports this one (PLAN.md section 1.2), so `probe/`, `bench/`, `search/`,
`report/`, and `preset/` stay independently testable.
"""

from __future__ import annotations

import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from neonpilot import __version__, artifacts
from neonpilot._llama_pin import LLAMA_CPP_COMMIT
from neonpilot.bench.stats import dominates
from neonpilot.models import (
    SCHEMA_VERSION,
    CooldownPolicy,
    Preset,
    RuntimeConfig,
    SweepBudget,
    SweepContext,
)
from neonpilot.preset import io as preset_io
from neonpilot.preset.schema import PresetValidationError
from neonpilot.preset.schema import validate as validate_preset
from neonpilot.probe import probe_host
from neonpilot.report.html import render_html
from neonpilot.report.markdown import render_markdown
from neonpilot.search import engine, planner

app = typer.Typer(
    name="neonpilot",
    help="Probe Arm CPUs, auto-tune llama.cpp runtime flags, and ship reproducible presets.",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)

#: Full-model defaults (PLAN.md section 4.4): 15-minute budget, prompt_n=512, gen_n=128.
_DEFAULT_BUDGET_SECONDS = 900
_DEFAULT_REPS = 3
_DEFAULT_PROMPT_N = 512
_DEFAULT_GEN_N = 128
_DEFAULT_TIMEOUT_S = 120
_DEFAULT_PRESETS_ROOT = Path("presets")

#: Baseline-credibility guard (docs/dev/build-notes.md item 15): PLAN.md section 4.3/FR2 say
#: "reps >= 3"; below that, a single unlucky/lucky rep can dominate the reported average on a
#: noisy machine, producing an implausible headline speedup number.
_MIN_RECOMMENDED_REPS = 3

#: Cooldown defaults (PLAN.md section 4.4): 20s cap for a full-model run, 3s for a CI-scale
#: budget. `_CI_BUDGET_THRESHOLD_S` picks the CI default whenever --budget looks CI-sized,
#: rather than always paying the full-model 20s cooldown regardless of workload size.
_FULL_MODEL_COOLDOWN_S = 20.0
_CI_COOLDOWN_S = 3.0
_CI_BUDGET_THRESHOLD_S = 300


def _default_cooldown_s(budget_total_seconds: int) -> float:
    return (
        _CI_COOLDOWN_S if budget_total_seconds <= _CI_BUDGET_THRESHOLD_S else _FULL_MODEL_COOLDOWN_S
    )


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"neonpilot {__version__}")
        raise typer.Exit(code=0)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the neonpilot version and exit.",
        ),
    ] = False,
) -> None:
    """neonpilot: Arm-native llama.cpp tuning, explained and reproducible."""


@app.command()
def probe(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the ChipReport as machine-readable JSON.")
    ] = False,
) -> None:
    """Detect this host's Arm chip, ISA features, and which llama.cpp fast paths activate."""
    from neonpilot.probe.render import render_json, render_table

    report = probe_host()
    if json_output:
        render_json(report, console)
    else:
        render_table(report, console)


def _discover_llama_bin() -> str:
    """Resolve the llama-bench binary path: `NEONPILOT_LLAMA_BIN` env var, else the
    repo-relative default `vendor/llama.cpp/build/bin/llama-bench` (PLAN.md section 3.2)."""
    env_override = os.environ.get("NEONPILOT_LLAMA_BIN")
    if env_override:
        return env_override
    repo_root = Path(__file__).resolve().parent.parent.parent
    return str(repo_root / "vendor" / "llama.cpp" / "build" / "bin" / "llama-bench")


def _infer_model_class(model: Path) -> str:
    """Slug used for preset/artifact filenames, e.g. `SmolLM2-135M-Q4_K_M.gguf` ->
    `smollm2-135m-q4_k_m`."""
    return model.stem.lower()


@app.command()
def optimize(
    model: Annotated[Path, typer.Argument(help="Path to a .gguf model file to benchmark.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Run-directory parent (default: ~/.neonpilot/runs)."),
    ] = None,
    budget: Annotated[
        int, typer.Option("--budget", help="Total wall-clock budget in seconds.")
    ] = _DEFAULT_BUDGET_SECONDS,
    reps: Annotated[
        int, typer.Option("--reps", help="Repetitions per config (>=3 recommended).")
    ] = _DEFAULT_REPS,
    prompt_n: Annotated[
        int, typer.Option("--prompt-n", help="Prefill workload token count.")
    ] = _DEFAULT_PROMPT_N,
    gen_n: Annotated[
        int, typer.Option("--gen-n", help="Generation workload token count.")
    ] = _DEFAULT_GEN_N,
    llama_bin: Annotated[
        Path | None,
        typer.Option("--llama-bin", help="Override the discovered llama-bench binary path."),
    ] = None,
    cooldown_s: Annotated[
        float | None,
        typer.Option(
            "--cooldown-s",
            help="Fixed cooldown cap in seconds "
            "(default: 3s for budgets <=300s, else 20s, PLAN.md section 4.4).",
        ),
    ] = None,
) -> None:
    """Run a staged, thermally guarded benchmark sweep to find the fastest runtime flags."""
    if not model.exists():
        error_console.print(f"[red]model not found: {model}[/red]")
        raise typer.Exit(code=1)

    binary = str(llama_bin) if llama_bin is not None else _discover_llama_bin()
    if not Path(binary).exists():
        error_console.print(
            f"[red]llama-bench binary not found at {binary}; run `make fetch-llama` first.[/red]"
        )
        raise typer.Exit(code=1)

    chip = probe_host()
    sweep_budget = SweepBudget(total_seconds=budget, reps=reps, prompt_n=prompt_n, gen_n=gen_n)
    search_plan = planner.plan(chip, sweep_budget)
    run_dir = artifacts.new_run_dir(out)
    resolved_cooldown_s = cooldown_s if cooldown_s is not None else _default_cooldown_s(budget)
    ctx = SweepContext(
        binary=binary,
        model_path=str(model),
        model_class=_infer_model_class(model),
        out_dir=str(run_dir),
        budget=sweep_budget,
        cooldown=CooldownPolicy(
            target_temp_c=None,
            max_cooldown_s=resolved_cooldown_s,
            fixed_delay_s=resolved_cooldown_s,
            idle_skip=True,
        ),
        timeout_s=_DEFAULT_TIMEOUT_S,
        llama_cpp_commit=LLAMA_CPP_COMMIT,
    )

    console.print(
        f"[bold]neonpilot optimize[/bold]: {chip.chip_name}, budget={budget}s, reps={reps}"
    )
    if reps < _MIN_RECOMMENDED_REPS:
        console.print(
            f"[yellow]warning: --reps={reps} is below the recommended minimum of "
            f"{_MIN_RECOMMENDED_REPS}; measurements may be noisy "
            "(see PLAN.md section 4.3).[/yellow]"
        )
    result = engine.run(search_plan, ctx)

    artifacts.dump(chip, run_dir / "chip.json")
    artifacts.dump(search_plan, run_dir / "plan.json")
    artifacts.dump(result.trials, run_dir / "trials.json")
    artifacts.dump(result, run_dir / "result.json")
    artifacts.write_run_log(run_dir / "run.log", result)

    gen_ts = f"{result.best.generation.avg_ts:.2f}" if result.best.generation else "n/a"
    console.print(f"best: {result.best.trial_id}  gen_ts={gen_ts}")
    console.print(
        f"speedup_gen_pct={result.speedup_gen_pct:+.1f}%  "
        f"speedup_prefill_pct={result.speedup_prefill_pct:+.1f}%"
    )
    if result.budget_truncated:
        console.print(
            f"[yellow]budget truncated -- dropped stages: {result.dropped_stages}[/yellow]"
        )
    if not dominates(result.best, result.baseline):
        console.print(
            "[yellow]warning: speedup may not be statistically significant -- baseline/tuned "
            "confidence bands overlap (see report methodology).[/yellow]"
        )
    console.print(f"run dir: {run_dir}")


def _resolve_run_dir(run_dir: Path | None) -> Path:
    if run_dir is not None:
        if not run_dir.exists():
            error_console.print(f"[red]run directory not found: {run_dir}[/red]")
            raise typer.Exit(code=1)
        return run_dir
    latest = Path.home() / ".neonpilot" / "runs" / "latest"
    if not latest.exists():
        error_console.print(
            "[red]no run directory given and no ~/.neonpilot/runs/latest found.[/red]"
        )
        raise typer.Exit(code=1)
    return latest


@app.command()
def report(
    run_dir: Annotated[
        Path | None,
        typer.Option("--run-dir", help="Run directory to render (default: latest)."),
    ] = None,
) -> None:
    """Render a Markdown + self-contained HTML report from a completed optimize run."""
    resolved_dir = _resolve_run_dir(run_dir)
    result_path = resolved_dir / "result.json"
    chip_path = resolved_dir / "chip.json"
    if not result_path.exists() or not chip_path.exists():
        error_console.print(
            f"[red]{resolved_dir} is missing chip.json/result.json "
            "(run `neonpilot optimize` first).[/red]"
        )
        raise typer.Exit(code=1)

    result = artifacts.load_sweep_result(result_path)
    chip = artifacts.load_chip_report(chip_path)

    md_path = resolved_dir / "report.md"
    html_path = resolved_dir / "report.html"
    md_path.write_text(render_markdown(result, chip), encoding="utf-8")
    html_path.write_text(render_html(result, chip), encoding="utf-8")
    console.print(f"wrote {md_path}")
    console.print(f"wrote {html_path}")


def _server_flags_text(cfg: RuntimeConfig) -> str:
    """Plain-text llama-server equivalent flags (no binary dependency, PLAN.md section 3.2)."""
    return (
        f"--threads {cfg.threads} --cache-type-k {cfg.cache_type_k} "
        f"--cache-type-v {cfg.cache_type_v} --flash-attn {cfg.flash_attn} "
        f"--batch-size {cfg.batch} --ubatch-size {cfg.ubatch}"
    )


def _build_preset_from_run(run_dir: Path) -> Preset:
    chip_path, result_path = run_dir / "chip.json", run_dir / "result.json"
    if not chip_path.exists() or not result_path.exists():
        error_console.print(
            f"[red]{run_dir} is missing chip.json/result.json "
            "(run `neonpilot optimize` first).[/red]"
        )
        raise typer.Exit(code=1)

    chip = artifacts.load_chip_report(chip_path)
    result = artifacts.load_sweep_result(result_path)
    baseline, best = result.baseline, result.best
    return Preset(
        schema_version=SCHEMA_VERSION,
        chip_id=chip.chip_id,
        chip=chip,
        model_class=result.model_class,
        model_file=result.model_file,
        config=best.config,
        llama_cpp_commit=result.llama_cpp_commit,
        generated_at=datetime.now(UTC).isoformat(),
        baseline_gen_ts=baseline.generation.avg_ts if baseline.generation else 0.0,
        baseline_prefill_ts=baseline.prefill.avg_ts if baseline.prefill else 0.0,
        tuned_gen_ts=best.generation.avg_ts if best.generation else 0.0,
        tuned_prefill_ts=best.prefill.avg_ts if best.prefill else 0.0,
        tuned_gen_stddev=best.generation.stddev_ts if best.generation else 0.0,
        speedup_gen_pct=result.speedup_gen_pct,
        speedup_prefill_pct=result.speedup_prefill_pct,
        server_flags=_server_flags_text(best.config),
        neonpilot_version=__version__,
        os_version=platform.platform(),
        reps=result.budget.reps,
        cooldown_s=best.thermal.cooldown_s if best.thermal else 0.0,
    )


@app.command()
def apply(
    preset_path: Annotated[
        Path | None,
        typer.Argument(
            help="An existing preset JSON to load, validate, and print the invocation for. "
            "Omit to package a completed run (see --run-dir) as a new preset instead."
        ),
    ] = None,
    run_dir: Annotated[
        Path | None,
        typer.Option("--run-dir", help="Run directory whose winner to package (default: latest)."),
    ] = None,
    presets_root: Annotated[
        Path, typer.Option("--presets-root", help="Root of the in-tree preset registry.")
    ] = _DEFAULT_PRESETS_ROOT,
) -> None:
    """Print the llama-bench invocation for a preset, or package a run's winner as one.

    Two modes: `neonpilot apply presets/apple-m1-max/foo.json` loads and validates an existing
    preset and prints its invocation. `neonpilot apply --run-dir <run>` packages that run's
    winning config as a new preset under `--presets-root` and prints its invocation.
    """
    if preset_path is not None and preset_path.is_file():
        try:
            data = json.loads(preset_path.read_text(encoding="utf-8"))
            preset = validate_preset(data)
        except (json.JSONDecodeError, PresetValidationError) as exc:
            error_console.print(f"[red]invalid preset: {exc}[/red]")
            raise typer.Exit(code=1) from exc
        console.print(f"schema_version: {preset.schema_version} (OK)")
        console.print(preset_io.invocation(preset))
        console.print(f"server_flags: {preset.server_flags}")
        return

    resolved_run_dir = _resolve_run_dir(run_dir or preset_path)
    preset = _build_preset_from_run(resolved_run_dir)
    saved_path = preset_io.save(preset, presets_root)
    console.print(f"wrote {saved_path}")
    console.print(preset_io.invocation(preset))
    console.print(f"server_flags: {preset.server_flags}")


if __name__ == "__main__":
    app()
