"""Host CPU load telemetry: a pure parser for `ps -Ao pcpu,comm -r` output, plus a thin
collector for the live values (feature F-A, docs/dev/build-notes.md).

Split the same way `probe/collector.py` splits "shell out" from "parse" so the parser stays a
pure, fixture-testable function (PLAN.md section 1.2 design rule) and the collector below is
the only place this module talks to the OS.
"""

from __future__ import annotations

import os
import subprocess

from neonpilot.models import LoadSnapshot, ProcessSample

_PS_TIMEOUT_S = 5
_TOP_N_PROCESSES = 3
_PS_ARGV = ["ps", "-Ao", "pcpu,comm", "-r"]


class SysloadError(Exception):
    """Raised when `ps` can't be run, or its output can't be parsed at all."""


def parse_ps_output(text: str) -> list[ProcessSample]:
    """Parse `ps -Ao pcpu,comm -r` stdout into `ProcessSample`s, highest %CPU first.

    `-r` already sorts descending by %CPU, so this preserves that order rather than
    re-sorting -- a caller only needs `[:N]` for "top N". The header row (`%CPU COMM`, exact
    spelling/spacing varies by platform) is skipped by checking whether each line's first
    whitespace-delimited token parses as a float, not by assuming a fixed number of header
    lines. `comm` may itself contain spaces (e.g. an app bundle path with a parenthesized
    suffix), so each line is split on only the *first* run of whitespace.

    :raises SysloadError: if `text` has no non-blank lines at all (a completely empty/failed
        `ps` invocation, not just "no processes above some threshold").
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise SysloadError("ps output was empty")

    samples: list[ProcessSample] = []
    for line in lines:
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pcpu_text, comm = parts
        try:
            pcpu = float(pcpu_text)
        except ValueError:
            continue  # header row (e.g. "%CPU COMM") or a malformed line -- skip, don't fail
        samples.append(ProcessSample(pcpu=pcpu, comm=comm))
    return samples


def read_ps_text() -> str:
    """Run `ps -Ao pcpu,comm -r` and return its stdout.

    :raises SysloadError: on a non-zero exit or a failure to spawn `ps` at all.
    """
    try:
        result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, read-only system command
            _PS_ARGV,
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT_S,
            check=False,
        )
    except OSError as exc:
        raise SysloadError(f"failed to run ps: {exc}") from exc
    if result.returncode != 0:
        raise SysloadError(f"ps exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def read_loadavg() -> tuple[float, float, float]:
    """Return `(loadavg_1m, loadavg_5m, loadavg_15m)` via `os.getloadavg()`.

    :raises OSError: `os.getloadavg()` itself raises `OSError` when the load average is
        unobtainable (documented CPython behavior) -- reproducible today in restricted/
        sandboxed containers that don't expose `/proc/loadavg` or the equivalent syscall, even
        on an otherwise-supported macOS/Linux host. Deliberately left unguarded here (a thin
        pass-through, per this module's own "collector talks to the OS, parser doesn't" split);
        callers decide how to degrade -- see `collect_load_snapshot` below and `cli.py`'s
        preflight check.
    """
    return os.getloadavg()


def collect_load_snapshot() -> LoadSnapshot | None:
    """Best-effort host load snapshot for a sweep's start/end (feature F-A).

    Returns `None` (not a partially-populated `LoadSnapshot`) if `os.getloadavg()` itself
    raises `OSError` (e.g. a restricted/sandboxed container without `/proc/loadavg`) --
    `report/_shared.py:measurement_conditions_text` already treats `None` as "no telemetry
    recorded" and omits the report line entirely, which is the right degrade for advisory
    telemetry: never worth failing a sweep over. The top-N process list is separately
    best-effort and degrades to an empty list if `ps` is unavailable/unparseable.
    """
    try:
        loadavg_1m, loadavg_5m, loadavg_15m = read_loadavg()
    except OSError:
        return None
    try:
        processes = parse_ps_output(read_ps_text())[:_TOP_N_PROCESSES]
    except SysloadError:
        processes = []
    return LoadSnapshot(
        loadavg_1m=loadavg_1m,
        loadavg_5m=loadavg_5m,
        loadavg_15m=loadavg_15m,
        top_processes=processes,
    )
