"""Map detected Arm ISA features to the llama.cpp/KleidiAI kernel that activates.

Verified ground truth (docs/dev/day1-spikes.md S3, Apple M1 Max): KleidiAI selects a kernel
*tier* per available ISA feature. From lowest to highest tier: NEON (generic dot-product) ->
DOTPROD (KleidiAI DOTPROD q4/q8 GEMM) -> I8MM (KleidiAI I8MM q4/q8 GEMM) -> SME2 (SME-tier
kernel, Apple M5+). A chip engages the *highest* tier its ISA supports; lower tiers it also
has are reported as present-but-superseded, not double-counted as "active".
"""

from __future__ import annotations

from neonpilot.models import FastPathNote

_DOTPROD_KERNEL = "KleidiAI DOTPROD q4/q8 GEMM"
_I8MM_KERNEL = "KleidiAI I8MM q4/q8 GEMM"
_SME2_KERNEL = "SME2 kernel (M5)"
_NEON_KERNEL = "NEON generic dot-product kernel (CPU_REPACK, no KleidiAI micro-kernel)"


def explain(isa: dict[str, bool]) -> list[FastPathNote]:
    """Return one FastPathNote per relevant ISA feature, explaining kernel activation.

    :param isa: feature-name -> present map, e.g. ``{"neon": True, "dotprod": True, ...}``.
        Missing keys default to ``False`` (fail-safe: never claim a feature we didn't detect).
    :return: notes for ``neon``, ``dotprod``, ``i8mm``, ``sme``, and ``sme2``, in that order.
    """
    has_neon = isa.get("neon", False)
    has_dotprod = isa.get("dotprod", False)
    has_i8mm = isa.get("i8mm", False)
    has_sme = isa.get("sme", False)
    has_sme2 = isa.get("sme2", False)

    notes = [_neon_note(has_neon, has_dotprod)]
    notes.append(_dotprod_note(has_dotprod, has_i8mm, has_sme2))
    notes.append(_i8mm_note(has_i8mm, has_sme2))
    notes.append(_sme_note(has_sme))
    notes.append(_sme2_note(has_sme2))
    return notes


def _neon_note(has_neon: bool, has_dotprod: bool) -> FastPathNote:
    if not has_neon:
        return FastPathNote(
            feature="neon",
            kernel=_NEON_KERNEL,
            active=False,
            why="NEON absent -> no Arm SIMD fast path available; falls back to scalar C++.",
        )
    active = not has_dotprod  # NEON-only tier engages iff no higher tier supersedes it.
    why = (
        "NEON present but superseded by a higher KleidiAI tier (dotprod/i8mm/sme2)."
        if has_dotprod
        else "dotprod absent -> falls back to generic NEON dot-product kernel (CPU_REPACK)."
    )
    return FastPathNote(feature="neon", kernel=_NEON_KERNEL, active=active, why=why)


def _dotprod_note(has_dotprod: bool, has_i8mm: bool, has_sme2: bool) -> FastPathNote:
    if not has_dotprod:
        return FastPathNote(
            feature="dotprod",
            kernel=_DOTPROD_KERNEL,
            active=False,
            why="dotprod absent -> DOTPROD-tier KleidiAI kernels unavailable.",
        )
    if has_i8mm or has_sme2:
        return FastPathNote(
            feature="dotprod",
            kernel=_DOTPROD_KERNEL,
            active=False,
            why="dotprod present but superseded by a higher-tier kernel (i8mm/sme2).",
        )
    return FastPathNote(
        feature="dotprod",
        kernel=_DOTPROD_KERNEL,
        active=True,
        why=(
            "i8mm ABSENT -> DOTPROD-tier KleidiAI kernels engaged; SME disabled; "
            "other quant types via CPU_REPACK q6_K_8x4."
        ),
    )


def _i8mm_note(has_i8mm: bool, has_sme2: bool) -> FastPathNote:
    if not has_i8mm:
        return FastPathNote(
            feature="i8mm",
            kernel=_I8MM_KERNEL,
            active=False,
            why="i8mm ABSENT -> falls back to a lower KleidiAI tier (dotprod) or CPU_REPACK.",
        )
    if has_sme2:
        return FastPathNote(
            feature="i8mm",
            kernel=_I8MM_KERNEL,
            active=False,
            why="i8mm present but superseded by SME2, the higher-tier kernel on this chip.",
        )
    return FastPathNote(
        feature="i8mm",
        kernel=_I8MM_KERNEL,
        active=True,
        why="i8mm present -> I8MM-tier KleidiAI kernels engage for q4/q8 weights.",
    )


def _sme_note(has_sme: bool) -> FastPathNote:
    if has_sme:
        return FastPathNote(
            feature="sme",
            kernel="SME (non-SME2) kernel",
            active=True,
            why="SME present -> SME kernels available (tier below SME2 if SME2 absent).",
        )
    return FastPathNote(
        feature="sme",
        kernel="SME (non-SME2) kernel",
        active=False,
        why="SME absent -> no SME-family kernels available on this chip.",
    )


def _sme2_note(has_sme2: bool) -> FastPathNote:
    if has_sme2:
        return FastPathNote(
            feature="sme2",
            kernel=_SME2_KERNEL,
            active=True,
            why="SME2 present -> SME-tier KleidiAI kernels engage for q4/q8 GEMM (Apple M5+).",
        )
    return FastPathNote(
        feature="sme2",
        kernel=_SME2_KERNEL,
        active=False,
        why="SME2 absent -> SME-tier KleidiAI kernels do not engage on this chip.",
    )
