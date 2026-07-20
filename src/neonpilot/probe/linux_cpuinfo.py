"""Parse Linux `/proc/cpuinfo` + AT_HWCAP/AT_HWCAP2 into a ChipReport.

Pure parser: takes injected text and pre-read hwcap integers, never shells out or calls
`ctypes.getauxval` itself (that lives in `neonpilot.probe.collector`, the sole subprocess/FFI
boundary for this adapter).

Linux/Graviton is "designed to work, untested" (REQUIREMENTS.md non-goals) -- macOS is the
authoritative target. Bit positions below are taken from the upstream Linux kernel UAPI header
`arch/arm64/include/uapi/asm/hwcap.h`, which is the canonical source for these values.

Known limitation (see docs/dev/build-notes.md): generic `/proc/cpuinfo` cannot distinguish
performance vs. efficiency cores, and this adapter's fixed signature (cpuinfo_text, hwcap,
hwcap2) carries no memory source, so `e_cores` and `ram_gb` are best-effort placeholders on
this platform.
"""

from __future__ import annotations

from datetime import UTC, datetime

from neonpilot.models import SCHEMA_VERSION, ChipReport
from neonpilot.probe.fastpath import explain

# --- AT_HWCAP bits (arch/arm64/include/uapi/asm/hwcap.h) ---
_HWCAP_ASIMD = 1 << 1  # NEON
_HWCAP_FPHP = 1 << 9  # half-precision float ops
_HWCAP_ASIMDDP = 1 << 20  # dot product
_HWCAP_SVE = 1 << 22

# --- AT_HWCAP2 bits ---
_HWCAP2_SVE2 = 1 << 1
_HWCAP2_I8MM = 1 << 13
_HWCAP2_BF16 = 1 << 14
_HWCAP2_SME = 1 << 23
_HWCAP2_SME2 = 1 << 37

# Known Arm implementer 0x41 "CPU part" IDs worth naming explicitly (Graviton-class Neoverse
# cores). Falls back to a generic "implementer/part" label for anything unrecognized.
_KNOWN_ARM_PARTS: dict[str, str] = {
    "0xd0c": "Neoverse N1",
    "0xd40": "Neoverse V1",
    "0xd49": "Neoverse N2",
    "0xd4f": "Neoverse V2",
}


def _parse_cpuinfo_fields(cpuinfo_text: str) -> dict[str, str]:
    """Parse the first `key\t: value` block and count `processor` lines."""
    fields: dict[str, str] = {}
    for line in cpuinfo_text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key and key not in fields:
            fields[key] = value
    return fields


def _count_processors(cpuinfo_text: str) -> int:
    return sum(1 for line in cpuinfo_text.splitlines() if line.strip().startswith("processor"))


def _chip_name(fields: dict[str, str]) -> str:
    if "model name" in fields:
        return fields["model name"]
    implementer = fields.get("CPU implementer", "").lower()
    part = fields.get("CPU part", "").lower()
    if implementer == "0x41" and part in _KNOWN_ARM_PARTS:
        return f"Arm {_KNOWN_ARM_PARTS[part]}"
    if implementer or part:
        return f"Arm CPU (implementer={implementer or '?'}, part={part or '?'})"
    return "Unknown Arm CPU"


def _slugify(chip_name: str) -> str:
    return (
        chip_name.strip()
        .lower()
        .replace(" ", "-")
        .replace("(", "")
        .replace(")", "")
        .replace(",", "")
        .replace("=", "-")
    )


def read_chip_report(cpuinfo_text: str, hwcap: int, hwcap2: int) -> ChipReport:
    """Parse `/proc/cpuinfo` text plus AT_HWCAP/AT_HWCAP2 ints into a validated ChipReport.

    :param cpuinfo_text: raw contents of `/proc/cpuinfo` (or a captured fixture).
    :param hwcap: value of `getauxval(AT_HWCAP)`.
    :param hwcap2: value of `getauxval(AT_HWCAP2)`.
    :return: a fully populated ChipReport for this host. Untrusted input: unknown/missing
        fields default rather than raising, per the probe trust boundary (PLAN.md 1.4).
    """
    fields = _parse_cpuinfo_fields(cpuinfo_text)
    total_cores = _count_processors(cpuinfo_text)

    isa = {
        "neon": bool(hwcap & _HWCAP_ASIMD),
        "dotprod": bool(hwcap & _HWCAP_ASIMDDP),
        "i8mm": bool(hwcap2 & _HWCAP2_I8MM),
        "sve": bool(hwcap & _HWCAP_SVE),
        "sve2": bool(hwcap2 & _HWCAP2_SVE2),
        "sme": bool(hwcap2 & _HWCAP2_SME),
        "sme2": bool(hwcap2 & _HWCAP2_SME2),
        "bf16": bool(hwcap2 & _HWCAP2_BF16),
        "fp16": bool(hwcap & _HWCAP_FPHP),
    }

    chip_name = _chip_name(fields)

    return ChipReport(
        schema_version=SCHEMA_VERSION,
        probed_at=datetime.now(UTC).isoformat(),
        platform="linux",
        chip_name=chip_name,
        chip_id=_slugify(chip_name),
        cpu_brand=fields.get("model name", chip_name),
        # generic /proc/cpuinfo cannot distinguish P/E cores; see module docstring.
        p_cores=total_cores,
        e_cores=0,
        total_cores=total_cores,
        ram_gb=0.0,  # no meminfo source in this adapter's signature; see module docstring.
        isa=isa,
        fast_paths=explain(isa),
        raw={
            **{
                k: v
                for k, v in fields.items()
                if k in ("model name", "CPU implementer", "CPU part")
            },
            "hwcap": hex(hwcap),
            "hwcap2": hex(hwcap2),
        },
    )
