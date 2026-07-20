"""neonpilot Typer CLI: probe / optimize / report / apply.

This module owns argument parsing, Rich rendering, and exit codes only. No other module in
the package imports this one (PLAN.md section 1.2), so `probe/`, `bench/`, `search/`,
`report/`, and `preset/` stay independently testable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from neonpilot import __version__
from neonpilot.probe import probe_host

app = typer.Typer(
    name="neonpilot",
    help="Probe Arm CPUs, auto-tune llama.cpp runtime flags, and ship reproducible presets.",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)


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


@app.command()
def optimize(
    model: Annotated[
        Path, typer.Argument(help="Path to a .gguf model file to benchmark.", exists=False)
    ],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Run-directory override (default: ~/.neonpilot/runs/<ts>)."),
    ] = None,
) -> None:
    """Run a staged, thermally guarded benchmark sweep to find the fastest runtime flags."""
    error_console.print(
        "[yellow]neonpilot optimize is not implemented yet (planned for milestone M3).[/yellow]"
    )
    raise typer.Exit(code=1)


@app.command()
def report(
    run_dir: Annotated[
        Path | None,
        typer.Option("--run-dir", help="Run directory to render (default: latest)."),
    ] = None,
) -> None:
    """Render a Markdown + self-contained HTML report from a completed optimize run."""
    error_console.print(
        "[yellow]neonpilot report is not implemented yet (planned for milestone M4).[/yellow]"
    )
    raise typer.Exit(code=1)


@app.command()
def apply(
    run_dir: Annotated[
        Path | None,
        typer.Option("--run-dir", help="Run directory whose winner to package (default: latest)."),
    ] = None,
) -> None:
    """Package the winning config from a run as a versioned, shareable preset."""
    error_console.print(
        "[yellow]neonpilot apply is not implemented yet (planned for milestone M4).[/yellow]"
    )
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
