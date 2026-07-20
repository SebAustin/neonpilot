"""Platform dispatch for host CPU probing."""

from __future__ import annotations

import platform

from neonpilot.models import ChipReport
from neonpilot.probe import collector
from neonpilot.probe.linux_cpuinfo import read_chip_report as _read_linux_chip_report
from neonpilot.probe.macos_sysctl import read_chip_report as _read_macos_chip_report

__all__ = ["probe_host"]


def probe_host() -> ChipReport:
    """Detect the current platform and return a fully populated ChipReport.

    :raises NotImplementedError: on an unsupported platform (anything but Darwin/Linux).
    """
    system = platform.system()
    if system == "Darwin":
        return _read_macos_chip_report(collector.read_sysctl_text())
    if system == "Linux":
        hwcap, hwcap2 = collector.read_hwcaps()
        return _read_linux_chip_report(collector.read_cpuinfo_text(), hwcap, hwcap2)
    raise NotImplementedError(
        f"neonpilot probe supports macOS and Linux only (detected: {system!r})"
    )
