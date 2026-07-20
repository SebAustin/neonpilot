"""Live host introspection: the only place probe/ shells out or calls libc.

Keeping this isolated from the parsers (`macos_sysctl.py`, `linux_cpuinfo.py`) is what makes
those parsers pure, fixture-testable functions (PLAN.md section 1.2 design rule). This module
itself is read-only: it never writes to the host and never requires elevated privileges.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import subprocess

_SYSCTL_TIMEOUT_S = 5

# Linux AT_HWCAP / AT_HWCAP2 auxv keys (from <elf.h> / <sys/auxv.h>).
_AT_HWCAP = 16
_AT_HWCAP2 = 26


def read_sysctl_text() -> str:
    """Run `sysctl -a` and return its stdout. Raises `RuntimeError` on non-zero exit."""
    result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, read-only system command
        ["sysctl", "-a"],
        capture_output=True,
        text=True,
        timeout=_SYSCTL_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sysctl -a exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def read_cpuinfo_text() -> str:
    """Return the contents of `/proc/cpuinfo`."""
    with open("/proc/cpuinfo", encoding="utf-8") as handle:
        return handle.read()


def read_hwcaps() -> tuple[int, int]:
    """Return `(getauxval(AT_HWCAP), getauxval(AT_HWCAP2))`, or `(0, 0)` if unavailable.

    Best-effort: some libc implementations (e.g. musl in certain configurations) may not
    expose `getauxval`; a missing symbol degrades to "no ISA features detected" rather than
    crashing the probe.
    """
    libc_path = ctypes.util.find_library("c")
    if libc_path is None:
        return 0, 0
    try:
        libc = ctypes.CDLL(libc_path)
        libc.getauxval.restype = ctypes.c_ulong
        libc.getauxval.argtypes = [ctypes.c_ulong]
        hwcap = int(libc.getauxval(_AT_HWCAP))
        hwcap2 = int(libc.getauxval(_AT_HWCAP2))
    except (AttributeError, OSError):
        return 0, 0
    return hwcap, hwcap2
