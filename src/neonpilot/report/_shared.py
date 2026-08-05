"""Small helpers shared by report/markdown.py and report/html.py.

Kept in one place so both emitters describe the same underlying data identically, and so a
future consumer (e.g. an `F-B compare` command) can reuse this logic instead of re-deriving it.
"""

from __future__ import annotations

from neonpilot.models import LoadSnapshot, TrialResult

#: Robustness review H3: shown instead of a concrete threads=.../cache_type=... line whenever
#: the winning trial's config is a synthetic reconstruction (see `winning_config_text` below),
#: so a report never implies a measured, appliable config was found when tuning simply didn't
#: beat the baseline.
_SYNTHETIC_CONFIG_TEXT = "defaults (as resolved by llama-bench; tuning did not beat the baseline)"


def winning_config_text(best: TrialResult) -> str:
    """Describe `best.config` for a report's methodology section.

    Robustness review H3: `best.is_synthetic_config` is True only when the sweep's "best" trial
    is actually the baseline/confirm-baseline trial itself (tuning never legitimately beat it).
    That trial's `.config` is a *reconstruction* of what llama.cpp is expected to resolve to,
    not parsed from the measured response (`BenchSample` carries no n_threads/type_k/type_v/
    flash_attn) -- so it must be labeled as such rather than presented as a concretely-measured,
    appliable winning configuration.
    """
    if best.is_synthetic_config:
        return _SYNTHETIC_CONFIG_TEXT
    cfg = best.config
    return (
        f"threads={cfg.threads}, cache_type={cfg.cache_type_k}/{cfg.cache_type_v}, "
        f"flash_attn={cfg.flash_attn}, batch/ubatch={cfg.batch}/{cfg.ubatch}"
    )


def measurement_conditions_text(load_before: LoadSnapshot | None) -> str | None:
    """Describe host ambient-load conditions at sweep start for a report's methodology section
    (feature F-A). Returns `None` when no telemetry was recorded -- an artifact predating this
    field, or the collector degrading silently (`bench/sysload.py`'s best-effort `ps` handling)
    -- so callers can omit the line entirely rather than render a blank/misleading one.
    """
    if load_before is None:
        return None
    if load_before.top_processes:
        top = load_before.top_processes[0]
        top_text = f"{top.comm} ({top.pcpu:.1f}% CPU)"
    else:
        top_text = "n/a"
    return (
        f"loadavg(1m/5m/15m)={load_before.loadavg_1m:.2f}/{load_before.loadavg_5m:.2f}/"
        f"{load_before.loadavg_15m:.2f}, top process: {top_text}"
    )
