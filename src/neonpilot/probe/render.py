"""Rich/JSON rendering of a ChipReport for `neonpilot probe`.

Pure presentation: takes an already-computed ChipReport and a Rich Console to write to. No
subprocess calls, no platform dispatch -- keeps `neonpilot probe --json` trivially testable
without a live host.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from rich.console import Console
from rich.table import Table

from neonpilot.models import ChipReport


def render_json(report: ChipReport, console: Console) -> None:
    """Print the ChipReport as pretty-printed JSON (schema per PLAN.md section 1.3)."""
    console.print_json(json.dumps(asdict(report), indent=2, sort_keys=True))


def render_table(report: ChipReport, console: Console) -> None:
    """Print a human-readable summary: chip/topology header, ISA table, fast-path notes."""
    console.print(f"[bold]{report.chip_name}[/bold] ({report.platform}, chip_id={report.chip_id})")
    console.print(
        f"Cores: {report.p_cores} performance + {report.e_cores} efficiency "
        f"= {report.total_cores} total  |  RAM: {report.ram_gb:g} GB"
    )

    isa_table = Table(title="ISA features")
    isa_table.add_column("Feature")
    isa_table.add_column("Present")
    for feature, present in report.isa.items():
        style = "green" if present else "dim"
        isa_table.add_row(feature, f"[{style}]{present}[/{style}]")
    console.print(isa_table)

    fastpath_table = Table(title="llama.cpp fast-path activation")
    fastpath_table.add_column("Feature")
    fastpath_table.add_column("Kernel")
    fastpath_table.add_column("Active")
    fastpath_table.add_column("Why")
    for note in report.fast_paths:
        style = "green" if note.active else "dim"
        fastpath_table.add_row(
            note.feature, note.kernel, f"[{style}]{note.active}[/{style}]", note.why
        )
    console.print(fastpath_table)
