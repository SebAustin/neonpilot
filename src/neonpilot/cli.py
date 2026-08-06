"""neonpilot Typer CLI: probe / optimize / report / apply.

This module owns argument parsing, Rich rendering, and exit codes only. No other module in
the package imports this one (PLAN.md section 1.2), so `probe/`, `bench/`, `search/`,
`report/`, and `preset/` stay independently testable.
"""

from __future__ import annotations

import json
import os
import platform
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape as rich_escape

from neonpilot import __version__, artifacts
from neonpilot._llama_pin import LLAMA_CPP_COMMIT
from neonpilot.bench import sysload
from neonpilot.bench.stats import dominates
from neonpilot.models import (
    SCHEMA_VERSION,
    ChipReport,
    CooldownPolicy,
    Preset,
    RuntimeConfig,
    SweepBudget,
    SweepContext,
    SweepResult,
)
from neonpilot.preset import io as preset_io
from neonpilot.preset.io import UnsafePresetPathError
from neonpilot.preset.schema import MAX_REPS, PresetValidationError
from neonpilot.preset.schema import validate as validate_preset
from neonpilot.probe import probe_host
from neonpilot.report.compare import render_compare_html, render_compare_markdown
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

#: GGUF magic bytes (robustness review M4): a directory or a 0-byte/truncated file passing a
#: bare `.exists()` check previously routed straight into a ~15-minute sweep before failing
#: (C1's "every trial errors" path) -- rejecting anything that doesn't even look like a GGUF
#: file up front is cheap and saves that wasted time.
_GGUF_MAGIC = b"GGUF"


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
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the neonpilot version and exit.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Show the full Python traceback on error instead of a one-line message.",
        ),
    ] = False,
) -> None:
    """neonpilot: Arm-native llama.cpp tuning, explained and reproducible."""
    ctx.obj = {"debug": debug}


def _handle_top_level_error(ctx: typer.Context, exc: Exception) -> None:
    """Robustness review M3: translate an otherwise-uncaught OSError/RuntimeError/
    NotImplementedError (e.g. a permission error on `--out`, a disk-full write, or an
    unsupported-platform probe) into a one-line stderr message + `Exit(1)`, instead of a raw
    Python traceback. `--debug` opts back into the raw traceback for troubleshooting.

    :raises typer.Exit: always, with code 1 (unless `--debug`, in which case `exc` is
        re-raised as-is so its traceback is preserved).
    """
    debug = bool(ctx.obj and ctx.obj.get("debug"))
    if debug:
        raise exc
    error_console.print(f"[red]error: {rich_escape(str(exc))}[/red]")
    raise typer.Exit(code=1) from exc


@app.command()
def probe(
    ctx: typer.Context,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the ChipReport as machine-readable JSON.")
    ] = False,
) -> None:
    """Detect this host's Arm chip, ISA features, and which llama.cpp fast paths activate."""
    try:
        _probe_impl(json_output)
    except (typer.Exit, typer.Abort, RecursionError):
        # N4: `typer.Exit`/`typer.Abort` (click's `Exit`/`Abort`) are (surprisingly) both
        # `RuntimeError` subclasses, and `RecursionError` is a builtin `RuntimeError` subclass
        # too -- all three must be let through unmolested rather than re-wrapped as if they
        # were a genuine, recoverable error (M3). Every command below follows this same
        # pattern.
        raise
    except (OSError, RuntimeError, NotImplementedError) as exc:
        _handle_top_level_error(ctx, exc)


def _probe_impl(json_output: bool) -> None:
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


def _looks_like_gguf(model: Path) -> bool:
    """Best-effort GGUF sniff: the first 4 bytes of a real `.gguf` file are the magic `GGUF`.

    Robustness review M4: `model.exists()` alone accepts a directory or a 0-byte/truncated
    file, which previously wasn't caught until the sweep had already burned its full budget
    erroring on every trial. Cheap to check up front.
    """
    try:
        with model.open("rb") as handle:
            return handle.read(len(_GGUF_MAGIC)) == _GGUF_MAGIC
    except OSError:
        return False


def _sigterm_to_keyboard_interrupt(signum: int, frame: object) -> None:
    """Robustness review M2: translate SIGTERM into a `KeyboardInterrupt` so a `llama-bench`
    child spawned via `subprocess.run` is still killed on the way out.

    CPython's own `subprocess.run` already kills its child and re-raises on `KeyboardInterrupt`
    during `communicate()` (see `Popen.communicate`'s `except KeyboardInterrupt` and `run`'s
    bare `except:` -> `process.kill()`) -- that machinery only ever fires today on SIGINT
    (Ctrl-C), because Python's default SIGTERM disposition is silent process termination with
    no exception raised at all, orphaning the child. Installing this handler for the duration
    of a sweep (`optimize`, around `engine.run`) makes SIGTERM behave the same way SIGINT
    already does, with no changes needed to `bench/runner.py`.

    :raises KeyboardInterrupt: always.
    """
    raise KeyboardInterrupt(f"received signal {signum}")


@app.command()
def optimize(
    ctx: typer.Context,
    model: Annotated[Path, typer.Argument(help="Path to a .gguf model file to benchmark.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Run-directory parent (default: ~/.neonpilot/runs)."),
    ] = None,
    budget: Annotated[
        int,
        typer.Option("--budget", min=1, help="Total wall-clock budget in seconds (>=1)."),
    ] = _DEFAULT_BUDGET_SECONDS,
    reps: Annotated[
        int,
        typer.Option(
            "--reps",
            min=1,
            max=MAX_REPS,
            help=f"Repetitions per config (>=3 recommended, 1-{MAX_REPS}).",
        ),
    ] = _DEFAULT_REPS,
    prompt_n: Annotated[
        int, typer.Option("--prompt-n", min=1, help="Prefill workload token count (>=1).")
    ] = _DEFAULT_PROMPT_N,
    gen_n: Annotated[
        int, typer.Option("--gen-n", min=1, help="Generation workload token count (>=1).")
    ] = _DEFAULT_GEN_N,
    llama_bin: Annotated[
        Path | None,
        typer.Option("--llama-bin", help="Override the discovered llama-bench binary path."),
    ] = None,
    cooldown_s: Annotated[
        float | None,
        typer.Option(
            "--cooldown-s",
            min=0.0,
            help="Fixed cooldown cap in seconds, >=0 "
            "(default: 3s for budgets <=300s, else 20s, PLAN.md section 4.4).",
        ),
    ] = None,
    target_temp_c: Annotated[
        float | None,
        typer.Option(
            "--target-temp-c",
            help="Cool until CPU temp drops below this before each trial (default: no sensor "
            "target, use the fixed/idle-skip cooldown instead; see bench/thermal.py).",
        ),
    ] = None,
    timeout_s: Annotated[
        int,
        typer.Option(
            "--timeout-s",
            min=1,
            help="Hard per-invocation timeout for the llama-bench subprocess, in seconds "
            "(raise this for large models).",
        ),
    ] = _DEFAULT_TIMEOUT_S,
    strict_idle: Annotated[
        bool,
        typer.Option(
            "--strict-idle",
            help="Abort instead of warning when the host looks busy before the sweep starts "
            "(feature F-A; see docs/dev/build-notes.md item 15 on noise-dominated speedups).",
        ),
    ] = False,
) -> None:
    """Run a staged, thermally guarded benchmark sweep to find the fastest runtime flags."""
    try:
        _optimize_impl(
            model=model,
            out=out,
            budget=budget,
            reps=reps,
            prompt_n=prompt_n,
            gen_n=gen_n,
            llama_bin=llama_bin,
            cooldown_s=cooldown_s,
            target_temp_c=target_temp_c,
            timeout_s=timeout_s,
            strict_idle=strict_idle,
        )
    except (typer.Exit, typer.Abort, RecursionError):
        raise
    except (OSError, RuntimeError, NotImplementedError) as exc:
        _handle_top_level_error(ctx, exc)


def _validate_model_arg(model: Path) -> None:
    if not model.is_file():
        error_console.print(f"[red]model not found or not a regular file: {model}[/red]")
        raise typer.Exit(code=1)
    if not _looks_like_gguf(model):
        error_console.print(
            f"[red]{model} does not look like a GGUF model file "
            "(missing the 'GGUF' magic bytes at offset 0).[/red]"
        )
        raise typer.Exit(code=1)


def _resolve_model_class(model: Path) -> str:
    model_class = _infer_model_class(model)
    try:
        preset_io.sanitize_slug(model_class, "model_class")
    except UnsafePresetPathError as exc:
        error_console.print(
            f"[red]cannot use {model.name!r} as a model_class slug: {rich_escape(str(exc))}[/red]"
        )
        raise typer.Exit(code=1) from exc
    return model_class


def _print_sweep_failure(result: SweepResult, run_dir: Path) -> None:
    """Robustness review C1: `result.best` has no usable measurement, so there is no
    legitimate "best" to report -- print a message instead of a bogus
    `best: confirm-baseline gen_ts=n/a` line.

    N6: this covers two genuinely different situations, so the message must not conflate
    them. `best.status != "ok"` means every trial (including the baseline) actually errored
    (a `BenchRunError`, e.g. a broken binary) -- distinct underlying errors are printed.
    `best.status == "ok"` but `best.generation is None` means every trial's llama-bench
    invocation *exited cleanly* but never produced a generation-throughput ("tg") sample (e.g.
    `--gen-n` resolved to 0, or a build of llama-bench that only emits prefill rows) -- there's
    no per-trial "error" string to list in that case, so a different, accurate message is
    printed instead of falsely implying every trial errored.
    """
    if result.best.status != "ok":
        error_console.print(
            "[red]optimize failed: no trial completed successfully -- nothing to report.[/red]"
        )
        all_trials = [result.baseline, *result.trials]
        errors = sorted({trial.error for trial in all_trials if trial.error})
        for message in errors:
            error_console.print(f"[red]  - {rich_escape(message)}[/red]")
    else:
        error_console.print(
            "[red]optimize failed: every trial completed but produced no generation-"
            "throughput sample -- nothing to report (check --gen-n is >=1 and that the "
            "llama-bench build actually emits a 'tg' row).[/red]"
        )
    error_console.print(f"[red]see {run_dir / 'run.log'} for full trial-by-trial detail.[/red]")


#: Feature F-A: above this loadavg_1m/physical-cores ratio, the host looks busy enough that a
#: measurement is likely to be noise-dominated (docs/dev/build-notes.md item 15's root-cause
#: writeup: background contention on a shared machine produced a 300-400% "speedup" that was
#: pure sampling noise). 0.5 is a permissive threshold -- a fully idle box is near 0.0, a box
#: with one CPU-bound background process per 2 cores is already at 0.5.
_IDLE_LOAD_RATIO_WARN_THRESHOLD = 0.5


def _check_ambient_load(chip: ChipReport, *, strict_idle: bool) -> None:
    """Feature F-A preflight: warn (or, with `--strict-idle`, abort) when the host looks busy
    before a sweep starts. Uses `sysload.read_loadavg()` directly (not the full
    `collect_load_snapshot()`, which also shells out to `ps` for the top-process list) since
    only the ratio is needed here; `engine.run()` separately records the full snapshot as
    `SweepResult.load_before`.

    N1: `os.getloadavg()` itself raises `OSError` on some restricted/sandboxed containers
    (undocumented-in-behavior but documented-in-signature CPython edge case) even on an
    otherwise-supported macOS/Linux host. That's a platform limitation, not evidence the host
    is busy -- so this degrades to skipping the check with a one-time warning, never aborting
    (even under `--strict-idle`, which would otherwise be a false-positive failure unrelated
    to actual ambient load).
    """
    try:
        loadavg_1m, _loadavg_5m, _loadavg_15m = sysload.read_loadavg()
    except OSError as exc:
        console.print(
            f"[yellow]warning: could not read host load average ({exc}) -- skipping the "
            "ambient-load preflight check.[/yellow]"
        )
        return
    if chip.total_cores <= 0:
        return
    load_ratio = loadavg_1m / chip.total_cores
    if load_ratio <= _IDLE_LOAD_RATIO_WARN_THRESHOLD:
        return

    message = (
        f"host load average ({loadavg_1m:.2f}) is {load_ratio:.1f}x the physical core count "
        f"({chip.total_cores}) -- measurements may be noise-dominated "
        "(see docs/dev/build-notes.md item 15)."
    )
    if strict_idle:
        error_console.print(f"[red]--strict-idle: refusing to start -- {message}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[yellow]warning: {message}[/yellow]")


def _optimize_impl(
    *,
    model: Path,
    out: Path | None,
    budget: int,
    reps: int,
    prompt_n: int,
    gen_n: int,
    llama_bin: Path | None,
    cooldown_s: float | None,
    target_temp_c: float | None,
    timeout_s: int,
    strict_idle: bool,
) -> None:
    _validate_model_arg(model)
    model_class = _resolve_model_class(model)

    binary = str(llama_bin) if llama_bin is not None else _discover_llama_bin()
    if not Path(binary).exists():
        error_console.print(
            f"[red]llama-bench binary not found at {binary}. "
            "In a repo checkout, run `make fetch-llama` first. "
            "If neonpilot was installed as a package (no Makefile available), point at an "
            "existing llama-bench build with `--llama-bin PATH` or the NEONPILOT_LLAMA_BIN "
            "environment variable instead.[/red]"
        )
        raise typer.Exit(code=1)

    chip = probe_host()
    _check_ambient_load(chip, strict_idle=strict_idle)
    sweep_budget = SweepBudget(total_seconds=budget, reps=reps, prompt_n=prompt_n, gen_n=gen_n)
    search_plan = planner.plan(chip, sweep_budget)
    run_dir = artifacts.new_run_dir(out)
    resolved_cooldown_s = cooldown_s if cooldown_s is not None else _default_cooldown_s(budget)
    ctx_sweep = SweepContext(
        binary=binary,
        model_path=str(model),
        model_class=model_class,
        out_dir=str(run_dir),
        budget=sweep_budget,
        cooldown=CooldownPolicy(
            target_temp_c=target_temp_c,
            max_cooldown_s=resolved_cooldown_s,
            fixed_delay_s=resolved_cooldown_s,
            idle_skip=True,
        ),
        timeout_s=timeout_s,
        llama_cpp_commit=LLAMA_CPP_COMMIT,
        baseline_threads=chip.p_cores,
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

    # Robustness review M2: translate SIGTERM -> KeyboardInterrupt for the duration of the
    # sweep only, restoring whatever handler was previously installed afterward.
    previous_handler = signal.signal(signal.SIGTERM, _sigterm_to_keyboard_interrupt)
    try:
        result = engine.run(search_plan, ctx_sweep)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)

    artifacts.dump(chip, run_dir / "chip.json")
    artifacts.dump(search_plan, run_dir / "plan.json")
    artifacts.dump(result.trials, run_dir / "trials.json")
    artifacts.dump(result, run_dir / "result.json")
    artifacts.write_run_log(run_dir / "run.log", result)

    if result.best.status != "ok" or result.best.generation is None:
        _print_sweep_failure(result, run_dir)
        raise typer.Exit(code=1)

    artifacts.mark_latest(run_dir)

    gen_ts = f"{result.best.generation.avg_ts:.2f}"
    console.print(f"best: {result.best.trial_id}  gen_ts={gen_ts}")
    console.print(
        f"speedup_gen_pct={result.speedup_gen_pct:+.1f}%  "
        f"speedup_prefill_pct={result.speedup_prefill_pct:+.1f}%"
    )
    if result.budget_truncated:
        console.print(
            f"[yellow]budget truncated -- dropped stages: {result.dropped_stages}[/yellow]"
        )
    if result.elapsed_s > budget:
        console.print(
            f"[yellow]warning: elapsed {result.elapsed_s:.1f}s exceeded the {budget}s budget "
            "(in-flight trials are never aborted mid-run; see PLAN.md section 4.4).[/yellow]"
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


def _load_run_artifacts(run_dir: Path) -> tuple[ChipReport, SweepResult]:
    """Load `chip.json` + `result.json` from `run_dir`, translating any failure into a
    friendly stderr message + `Exit(1)` (robustness review H4) instead of a raw traceback --
    covers a missing artifact, a truncated/corrupt `result.json` (`JSONDecodeError`), an
    artifact predating a since-added required field (`TypeError`), and an unreadable file
    (`OSError`, e.g. permissions).
    """
    chip_path, result_path = run_dir / "chip.json", run_dir / "result.json"
    if not chip_path.exists() or not result_path.exists():
        error_console.print(
            f"[red]{run_dir} is missing chip.json/result.json "
            "(run `neonpilot optimize` first).[/red]"
        )
        raise typer.Exit(code=1)
    try:
        chip = artifacts.load_chip_report(chip_path)
        result = artifacts.load_sweep_result(result_path)
    except (json.JSONDecodeError, TypeError, OSError) as exc:
        error_console.print(
            f"[red]failed to load run artifacts from {run_dir}: {rich_escape(str(exc))}[/red]"
        )
        raise typer.Exit(code=1) from exc
    return chip, result


@app.command()
def report(
    ctx: typer.Context,
    run_dir: Annotated[
        Path | None,
        typer.Option("--run-dir", help="Run directory to render (default: latest)."),
    ] = None,
) -> None:
    """Render a Markdown + self-contained HTML report from a completed optimize run."""
    try:
        _report_impl(run_dir)
    except (typer.Exit, typer.Abort, RecursionError):
        raise
    except (OSError, RuntimeError, NotImplementedError) as exc:
        _handle_top_level_error(ctx, exc)


def _report_impl(run_dir: Path | None) -> None:
    resolved_dir = _resolve_run_dir(run_dir)
    chip, result = _load_run_artifacts(resolved_dir)

    md_path = resolved_dir / "report.md"
    html_path = resolved_dir / "report.html"
    try:
        md_path.write_text(render_markdown(result, chip), encoding="utf-8")
        html_path.write_text(render_html(result, chip), encoding="utf-8")
    except OSError as exc:
        error_console.print(
            f"[red]failed to write report to {resolved_dir}: {rich_escape(str(exc))}[/red]"
        )
        raise typer.Exit(code=1) from exc
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
    chip, result = _load_run_artifacts(run_dir)
    baseline, best = result.baseline, result.best

    # Robustness review C1: never package a preset from a run where nothing was measured.
    if best.status != "ok" or best.generation is None:
        error_console.print(
            "[red]refusing to package a preset: the run's best trial never completed "
            f"successfully (status={best.status!r}). "
            f"See {run_dir / 'run.log'} for details.[/red]"
        )
        raise typer.Exit(code=1)
    # Robustness review H3: `best.config` here is a *reconstruction* of llama.cpp's own
    # defaults (see search/_trial.py:baseline_display_config), not a measured, appliable
    # config -- packaging it would silently ship placeholder flags as if they were tuned.
    if best.is_synthetic_config:
        error_console.print(
            "[red]refusing to package a preset: tuning never beat the baseline, so there is "
            "no measured winning config to package (see the report's methodology section, "
            "or re-run with a larger --budget/--reps).[/red]"
        )
        raise typer.Exit(code=1)

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
    ctx: typer.Context,
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
    try:
        _apply_impl(preset_path, run_dir, presets_root)
    except (typer.Exit, typer.Abort, RecursionError):
        raise
    except (OSError, RuntimeError, NotImplementedError) as exc:
        _handle_top_level_error(ctx, exc)


def _apply_impl(preset_path: Path | None, run_dir: Path | None, presets_root: Path) -> None:
    if preset_path is not None and not preset_path.is_dir():
        if not preset_path.is_file():
            # Robustness review LOW: previously this fell through to `_resolve_run_dir`, which
            # reported "run directory not found" -- misleading when the user's intent was
            # clearly a preset file (a typo'd path, not a directory).
            error_console.print(
                f"[red]path not found: {preset_path} "
                "(expected a preset .json file or a run directory).[/red]"
            )
            raise typer.Exit(code=1)
        try:
            data = json.loads(preset_path.read_text(encoding="utf-8"))
            preset = validate_preset(data)
        except (json.JSONDecodeError, PresetValidationError) as exc:
            # exc may echo back attacker-controlled field values (SECURITY.md F5) -- escape
            # before interpolating into a line that also carries our own intentional markup.
            error_console.print(f"[red]invalid preset: {rich_escape(str(exc))}[/red]")
            raise typer.Exit(code=1) from exc
        _print_preset_summary(preset)
        return

    resolved_run_dir = _resolve_run_dir(run_dir or preset_path)
    preset = _build_preset_from_run(resolved_run_dir)
    try:
        saved_path = preset_io.save(preset, presets_root)
    except UnsafePresetPathError as exc:
        error_console.print(f"[red]refusing to save preset: {rich_escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    # `wrote {saved_path}` is safe: saved_path came from our own presets_root resolution, not
    # directly from untrusted preset fields.
    console.print(f"wrote {saved_path}")
    _print_preset_summary(preset)


def _print_preset_summary(preset: Preset) -> None:
    """Print a preset's invocation + server_flags with markup disabled (SECURITY.md F5):
    every value here (`preset.schema_version` only after an exact-match check aside) is
    untrusted preset content and must never be interpreted as Rich markup/hyperlink syntax."""
    console.print(f"schema_version: {preset.schema_version} (OK)", markup=False)
    console.print(preset_io.invocation(preset), markup=False)
    console.print(f"server_flags: {preset.server_flags}", markup=False)


@app.command()
def compare(
    ctx: typer.Context,
    run_dir_a: Annotated[Path, typer.Argument(help="First run directory to compare.")],
    run_dir_b: Annotated[Path, typer.Argument(help="Second run directory to compare.")],
    out: Annotated[
        Path | None,
        typer.Option(
            "--out", help="Directory to write compare.md/compare.html into (default: run_dir_a)."
        ),
    ] = None,
) -> None:
    """Render a side-by-side Markdown + HTML comparison of two completed optimize runs."""
    try:
        _compare_impl(run_dir_a, run_dir_b, out)
    except (typer.Exit, typer.Abort, RecursionError):
        raise
    except (OSError, RuntimeError, NotImplementedError) as exc:
        _handle_top_level_error(ctx, exc)


def _compare_impl(run_dir_a: Path, run_dir_b: Path, out: Path | None) -> None:
    # Feature F-B: respect H4-style error handling on both artifact loads from day one, by
    # reusing the exact same helper `report`/`apply --run-dir` already use.
    chip_a, result_a = _load_run_artifacts(run_dir_a)
    chip_b, result_b = _load_run_artifacts(run_dir_b)

    out_dir = out if out is not None else run_dir_a
    md_path = out_dir / "compare.md"
    html_path = out_dir / "compare.html"
    label_a, label_b = chip_a.chip_name, chip_b.chip_name
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            render_compare_markdown(
                result_a, chip_a, result_b, chip_b, label_a=label_a, label_b=label_b
            ),
            encoding="utf-8",
        )
        html_path.write_text(
            render_compare_html(
                result_a, chip_a, result_b, chip_b, label_a=label_a, label_b=label_b
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        error_console.print(
            f"[red]failed to write compare report to {out_dir}: {rich_escape(str(exc))}[/red]"
        )
        raise typer.Exit(code=1) from exc
    console.print(f"wrote {md_path}")
    console.print(f"wrote {html_path}")


if __name__ == "__main__":
    app()
