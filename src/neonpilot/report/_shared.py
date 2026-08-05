"""Small helpers shared by report/markdown.py, report/html.py, and report/compare.py.

Kept in one place so every emitter describes the same underlying data identically (escaping,
SVG bar charts, CSS) instead of re-deriving or duplicating it.
"""

from __future__ import annotations

import html

from neonpilot.models import LoadSnapshot, TrialResult

#: Shared inline-SVG bar-chart geometry (feature F-B: reused by report/compare.py so a
#: baseline/tuned comparison chart looks identical whether it's inside a single-run report or
#: a two-machine compare report).
_CHART_WIDTH = 440
_BAR_HEIGHT = 26
_BAR_GAP = 10
_LABEL_OFFSET = 8

#: Shared inline CSS (feature F-B: report/compare.py reuses this verbatim rather than
#: maintaining a second, drifting copy of the same dark theme/table/bar-chart styles).
CSS = """
:root {
  --bg: #0b0d12; --fg: #e8e8ec; --accent: #4fd1c5; --accent2: #f6ad55;
  --muted: #9aa0ab; --border: #242832; --surface: #161a22;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg); margin: 0; padding: 2rem; line-height: 1.5;
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
}
h1, h2 { font-weight: 600; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border: 1px solid var(--border); padding: 0.4rem 0.6rem; text-align: left; \
font-size: 0.9rem; }
th { background: var(--surface); }
.bar-baseline { fill: var(--muted); }
.bar-tuned { fill: var(--accent); }
.chart-title { fill: var(--fg); font-size: 13px; }
.bar-label { fill: var(--fg); font-size: 12px; }
.caveat { color: var(--accent2); border-left: 3px solid var(--accent2); padding-left: 0.75rem; }
.delta-highlight { background: rgba(246, 173, 85, 0.18); }
section { margin-bottom: 2rem; }
code { color: var(--accent); }
"""


def esc(value: object) -> str:
    """`html.escape(str(value))` for *every* interpolated value, numeric/bool included
    (SECURITY.md F9). `_hydrate.py`'s strict scalar typing (F1) already guarantees these are
    real `int`/`bool` by the time they reach a renderer, but escaping unconditionally is cheap
    and removes any future dependence on that guarantee holding for HTML safety."""
    return html.escape(str(value))


def bar(y: int, value: float, max_value: float, css_class: str, label: str) -> str:
    """One horizontal `<rect>` + label `<text>` inside a `_comparison_chart`-shaped SVG."""
    plot_width = _CHART_WIDTH - 150
    width = 0.0 if max_value <= 0 else (value / max_value) * plot_width
    width = max(width, 1.0)
    return (
        f'<rect x="0" y="{y}" width="{width:.1f}" height="{_BAR_HEIGHT}" '
        f'class="{css_class}"></rect>'
        f'<text x="{width + _LABEL_OFFSET:.1f}" y="{y + _BAR_HEIGHT - 8}" class="bar-label">'
        f"{esc(label)}</text>"
    )


def comparison_chart(title: str, baseline_value: float, tuned_value: float, unit: str) -> str:
    """A 2-bar (baseline vs. tuned) inline SVG chart, self-contained (no external assets)."""
    max_value = max(baseline_value, tuned_value, 1e-9)
    height = _BAR_HEIGHT * 2 + _BAR_GAP + 34
    baseline_bar = bar(
        24, baseline_value, max_value, "bar-baseline", f"Baseline: {baseline_value:.2f} {unit}"
    )
    tuned_bar = bar(
        24 + _BAR_HEIGHT + _BAR_GAP,
        tuned_value,
        max_value,
        "bar-tuned",
        f"Tuned: {tuned_value:.2f} {unit}",
    )
    return (
        f'<svg viewBox="0 0 {_CHART_WIDTH} {height}" role="img" '
        f'aria-label="{esc(title)} comparison chart">'
        f'<text x="0" y="14" class="chart-title">{esc(title)}</text>'
        f"{baseline_bar}{tuned_bar}</svg>"
    )


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
