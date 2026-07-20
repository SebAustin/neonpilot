"""Build staged benchmark candidate sets from a probed chip (PLAN.md section 4.1).

Pure function of `(ChipReport, SweepBudget)` -- no subprocess calls, no measurement. Stage B
and Stage C candidates are built with a placeholder thread count (the chip's P-core count,
matching llama.cpp's own default); `search/engine.py` overrides `.threads` (and, for Stage C,
`.flash_attn`/`.cache_type_k`/`.cache_type_v`) with the actual winning value from the prior
stage before benching, via `dataclasses.replace` (see docs/dev/build-notes.md for why planner
can't know the *measured* winner up front).
"""

from __future__ import annotations

from neonpilot.models import ChipReport, RuntimeConfig, SearchPlan, SweepBudget

_DEFAULT_CACHE = "f16"
_DEFAULT_FLASH_ATTN = "auto"
_DEFAULT_BATCH = 2048
_DEFAULT_UBATCH = 512

#: Stage B: flash-attention on/off x KV-cache type (k=v), PLAN.md section 4.1.
_STAGE_B_FLASH_ATTN = ("off", "on")
_STAGE_B_CACHE_TYPES = ("f16", "q8_0", "q4_0")

#: Stage C: (batch, ubatch) pairs, PLAN.md section 4.1. First pair is llama.cpp's own default.
_STAGE_C_BATCH_UBATCH = ((2048, 512), (2048, 1024), (4096, 2048))

#: Minimum distinct thread candidates (FR2: "at minimum 2 candidate configs").
_MIN_THREAD_CANDIDATES = 2
#: Cap on Stage A candidate count (PLAN.md section 4.1: "cap 4").
_MAX_THREAD_CANDIDATES = 4


def _thread_candidates(chip: ChipReport) -> list[int]:
    """`sorted(set([p, p-2, total, max(1, total-1)]))`, clamped >=1 (PLAN.md section 4.1)."""
    p = max(chip.p_cores, 1)
    total = max(chip.total_cores, p)
    raw = {p, max(1, p - 2), total, max(1, total - 1)}
    candidates = sorted(count for count in raw if count >= 1)
    if len(candidates) < _MIN_THREAD_CANDIDATES:
        candidates = sorted({1, total}) if total > 1 else [1]
    return candidates[:_MAX_THREAD_CANDIDATES]


def _build_stage_a(chip: ChipReport) -> list[RuntimeConfig]:
    return [
        RuntimeConfig(
            threads=threads,
            cache_type_k=_DEFAULT_CACHE,
            cache_type_v=_DEFAULT_CACHE,
            flash_attn=_DEFAULT_FLASH_ATTN,
            batch=_DEFAULT_BATCH,
            ubatch=_DEFAULT_UBATCH,
        )
        for threads in _thread_candidates(chip)
    ]


def _build_stage_b(chip: ChipReport) -> list[RuntimeConfig]:
    placeholder_threads = max(chip.p_cores, 1)
    return [
        RuntimeConfig(
            threads=placeholder_threads,
            cache_type_k=cache_type,
            cache_type_v=cache_type,
            flash_attn=flash_attn,
            batch=_DEFAULT_BATCH,
            ubatch=_DEFAULT_UBATCH,
        )
        for flash_attn in _STAGE_B_FLASH_ATTN
        for cache_type in _STAGE_B_CACHE_TYPES
    ]


def _build_stage_c(chip: ChipReport) -> list[RuntimeConfig]:
    placeholder_threads = max(chip.p_cores, 1)
    return [
        RuntimeConfig(
            threads=placeholder_threads,
            cache_type_k=_DEFAULT_CACHE,
            cache_type_v=_DEFAULT_CACHE,
            flash_attn=_DEFAULT_FLASH_ATTN,
            batch=batch,
            ubatch=ubatch,
        )
        for batch, ubatch in _STAGE_C_BATCH_UBATCH
    ]


def plan(chip: ChipReport, budget: SweepBudget) -> SearchPlan:
    """Build the staged candidate sets for `chip` (PLAN.md section 4.1).

    :param budget: not currently used to size candidate counts (the staged sweep is fixed-size
        per PLAN.md section 4.1); accepted per the PLAN.md section 1.2 interface and threaded
        through so future budget-aware planning has a stable call site.
    """
    stage_a = _build_stage_a(chip)
    stage_b = _build_stage_b(chip)
    stage_c = _build_stage_c(chip)
    notes = [
        f"Stage A (threads): candidates derived from topology "
        f"(p_cores={chip.p_cores}, total_cores={chip.total_cores}) -> "
        f"{[cfg.threads for cfg in stage_a]}; winner by generation t/s, ties broken by "
        f"prefill t/s then fewer threads.",
        "Stage B (flash-attention x KV-cache): flash_attn in {off, on} x "
        "cache_type in {f16, q8_0, q4_0}, threads fixed to Stage A's winner; winner by "
        "generation t/s, ties broken by prefill t/s then smaller KV cache.",
        "Stage C (batch/ubatch): (b, ub) in {(2048,512), (2048,1024), (4096,2048)}, threads/"
        "flash_attn/cache_type fixed to Stage A/B winners; winner by prefill t/s among "
        "candidates that do not statistically regress generation t/s vs Stage B's winner.",
        f"Budget: {budget.total_seconds}s wall-clock, {budget.reps} reps/config, "
        f"prompt_n={budget.prompt_n}, gen_n={budget.gen_n}.",
    ]
    return SearchPlan(stage_a=stage_a, stage_b=stage_b, stage_c=stage_c, baseline=None, notes=notes)
