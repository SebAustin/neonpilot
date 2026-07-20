"""Parse macOS `sysctl -a` output into a ChipReport.

Pure parser: takes injected text, never shells out itself (PLAN.md section 1.2 design rule).
The live `sysctl -a` call happens in `neonpilot.probe.collector`, which is the sole
subprocess boundary for this adapter.

Ground truth verified on Apple M1 Max (docs/dev/day1-spikes.md S1):
neon=true, dotprod=true, fp16=true, i8mm=FALSE, bf16=false, sme=false, sme2=false,
8 P-cores + 2 E-cores. Apple Silicon does not implement SVE/SVE2 at all (no sysctl key
exists for it), so those two ISA flags are always reported False on this platform.
"""

from __future__ import annotations

from datetime import UTC, datetime

from neonpilot.models import SCHEMA_VERSION, ChipReport
from neonpilot.probe.fastpath import explain

_BYTES_PER_GIB = 1024**3

# sysctl key -> isa dict key, for the boolean "hw.optional.arm.*" feature flags we care about.
_ISA_KEYS: dict[str, str] = {
    "hw.optional.arm.AdvSIMD": "neon",
    "hw.optional.arm.FEAT_DotProd": "dotprod",
    "hw.optional.arm.FEAT_I8MM": "i8mm",
    "hw.optional.arm.FEAT_BF16": "bf16",
    "hw.optional.arm.FEAT_FP16": "fp16",
    "hw.optional.arm.FEAT_SME": "sme",
    "hw.optional.arm.FEAT_SME2": "sme2",
}

# Apple Silicon never implements SVE/SVE2; there is no corresponding sysctl key.
_SVE_ISA_DEFAULTS: dict[str, bool] = {"sve": False, "sve2": False}


def _parse_lines(sysctl_text: str) -> dict[str, str]:
    """Split `key: value` lines into a dict. Blank/malformed lines are skipped, not fatal."""
    parsed: dict[str, str] = {}
    for line in sysctl_text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key:
            parsed[key] = value
    return parsed


def _to_bool(raw: dict[str, str], key: str) -> bool:
    """`sysctl` booleans are rendered as "1"/"0"; missing/unknown keys default to False."""
    return raw.get(key, "0").strip() == "1"


def _to_int(raw: dict[str, str], key: str, default: int = 0) -> int:
    value = raw.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _slugify(chip_name: str) -> str:
    return chip_name.strip().lower().replace(" ", "-")


def read_chip_report(sysctl_text: str) -> ChipReport:
    """Parse `sysctl -a` output (injected text) into a validated, immutable ChipReport.

    :param sysctl_text: raw stdout of `sysctl -a` (or a captured fixture). Untrusted input:
        missing keys default rather than raising, per the probe trust boundary (PLAN.md 1.4).
    :return: a fully populated ChipReport for this host.
    """
    raw = _parse_lines(sysctl_text)

    isa: dict[str, bool] = {
        isa_key: _to_bool(raw, sysctl_key) for sysctl_key, isa_key in _ISA_KEYS.items()
    }
    isa.update(_SVE_ISA_DEFAULTS)

    chip_name = raw.get("machdep.cpu.brand_string", "Unknown Apple Silicon")
    p_cores = _to_int(raw, "hw.perflevel0.physicalcpu")
    e_cores = _to_int(raw, "hw.perflevel1.physicalcpu")
    total_cores = _to_int(raw, "hw.physicalcpu", default=p_cores + e_cores)
    mem_bytes = _to_int(raw, "hw.memsize")
    ram_gb = round(mem_bytes / _BYTES_PER_GIB, 2) if mem_bytes else 0.0

    provenance = {key: raw[key] for key in list(_ISA_KEYS) if key in raw}
    provenance.update(
        {
            key: raw[key]
            for key in (
                "machdep.cpu.brand_string",
                "hw.perflevel0.physicalcpu",
                "hw.perflevel1.physicalcpu",
                "hw.physicalcpu",
                "hw.memsize",
            )
            if key in raw
        }
    )

    return ChipReport(
        schema_version=SCHEMA_VERSION,
        probed_at=datetime.now(UTC).isoformat(),
        platform="darwin",
        chip_name=chip_name,
        chip_id=_slugify(chip_name),
        cpu_brand=chip_name,
        p_cores=p_cores,
        e_cores=e_cores,
        total_cores=total_cores,
        ram_gb=ram_gb,
        isa=isa,
        fast_paths=explain(isa),
        raw=provenance,
    )
