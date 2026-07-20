"""Render a self-contained single-file HTML report (PLAN.md section 5, FR3, SC8).

Zero external fetches: CSS is inlined in a `<style>` block, charts are hand-rolled inline SVG
(no Chart.js/CDN), no `<script>` tags at all. Opens correctly via `file://` with no network
access and no console errors.
"""

from __future__ import annotations

import html

from neonpilot.models import ChipReport, SweepResult, TrialResult

_CHART_WIDTH = 440
_BAR_HEIGHT = 26
_BAR_GAP = 10
_LABEL_OFFSET = 8

_CSS = """
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
section { margin-bottom: 2rem; }
code { color: var(--accent); }
"""


def _bar(y: int, value: float, max_value: float, css_class: str, label: str) -> str:
    plot_width = _CHART_WIDTH - 150
    width = 0.0 if max_value <= 0 else (value / max_value) * plot_width
    width = max(width, 1.0)
    return (
        f'<rect x="0" y="{y}" width="{width:.1f}" height="{_BAR_HEIGHT}" '
        f'class="{css_class}"></rect>'
        f'<text x="{width + _LABEL_OFFSET:.1f}" y="{y + _BAR_HEIGHT - 8}" class="bar-label">'
        f"{html.escape(label)}</text>"
    )


def _comparison_chart(title: str, baseline_value: float, tuned_value: float, unit: str) -> str:
    max_value = max(baseline_value, tuned_value, 1e-9)
    height = _BAR_HEIGHT * 2 + _BAR_GAP + 34
    baseline_bar = _bar(
        24, baseline_value, max_value, "bar-baseline", f"Baseline: {baseline_value:.2f} {unit}"
    )
    tuned_bar = _bar(
        24 + _BAR_HEIGHT + _BAR_GAP,
        tuned_value,
        max_value,
        "bar-tuned",
        f"Tuned: {tuned_value:.2f} {unit}",
    )
    return (
        f'<svg viewBox="0 0 {_CHART_WIDTH} {height}" role="img" '
        f'aria-label="{html.escape(title)} comparison chart">'
        f'<text x="0" y="14" class="chart-title">{html.escape(title)}</text>'
        f"{baseline_bar}{tuned_bar}</svg>"
    )


def _trial_row(trial: TrialResult) -> str:
    gen = f"{trial.generation.avg_ts:.2f}" if trial.generation else "-"
    prefill = f"{trial.prefill.avg_ts:.2f}" if trial.prefill else "-"
    return (
        f"<tr><td>{html.escape(trial.trial_id)}</td><td>{html.escape(trial.stage)}</td>"
        f"<td>{html.escape(trial.status)}</td><td>{trial.config.threads}</td>"
        f"<td>{html.escape(trial.config.cache_type_k)}</td><td>{html.escape(trial.config.flash_attn)}</td>"
        f"<td>{gen}</td><td>{prefill}</td></tr>"
    )


def _caveat_html(result: SweepResult) -> str:
    if not result.budget_truncated:
        return ""
    dropped = ", ".join(result.dropped_stages)
    text = f"Budget truncated -- dropped: {html.escape(dropped)}."
    if "confirm" in result.dropped_stages:
        text += (
            " Confirm pass skipped: the speedup figures below use sweep-phase samples, "
            "not a back-to-back confirm measurement."
        )
    return f'<p class="caveat">{text}</p>'


def render_html(result: SweepResult, chip: ChipReport) -> str:
    """Render the full self-contained HTML report for a completed sweep."""
    baseline_gen = result.baseline.generation.avg_ts if result.baseline.generation else 0.0
    tuned_gen = result.best.generation.avg_ts if result.best.generation else 0.0
    baseline_prefill = result.baseline.prefill.avg_ts if result.baseline.prefill else 0.0
    tuned_prefill = result.best.prefill.avg_ts if result.best.prefill else 0.0

    isa_rows = "".join(
        f"<tr><td>{html.escape(feature)}</td><td>{present}</td></tr>"
        for feature, present in chip.isa.items()
    )
    fastpath_rows = "".join(
        f"<tr><td>{html.escape(note.feature)}</td><td>{html.escape(note.kernel)}</td>"
        f"<td>{note.active}</td><td>{html.escape(note.why)}</td></tr>"
        for note in chip.fast_paths
    )
    trial_rows = "".join(_trial_row(trial) for trial in result.trials)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>neonpilot report: {html.escape(chip.chip_name)} / {html.escape(result.model_class)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>neonpilot report: {html.escape(chip.chip_name)} / {html.escape(result.model_class)}</h1>
<p>Model file: <code>{html.escape(result.model_file)}</code> | llama.cpp commit: \
<code>{html.escape(result.llama_cpp_commit)}</code> | schema: \
<code>{html.escape(result.schema_version)}</code></p>
{_caveat_html(result)}
<section>
<h2>Baseline vs. tuned</h2>
{_comparison_chart("Generation throughput", baseline_gen, tuned_gen, "t/s")}
{_comparison_chart("Prefill throughput", baseline_prefill, tuned_prefill, "t/s")}
<p>Generation speedup: {result.speedup_gen_pct:+.1f}% | \
Prefill speedup: {result.speedup_prefill_pct:+.1f}%</p>
</section>
<section>
<h2>Chip ISA features</h2>
<table><thead><tr><th>Feature</th><th>Present</th></tr></thead><tbody>{isa_rows}</tbody></table>
</section>
<section>
<h2>llama.cpp fast-path activation</h2>
<table><thead><tr><th>Feature</th><th>Kernel</th><th>Active</th><th>Why</th></tr></thead>\
<tbody>{fastpath_rows}</tbody></table>
</section>
<section>
<h2>Methodology</h2>
<ul>
<li>Repetitions per config: {result.budget.reps} \
(prompt_n={result.budget.prompt_n}, gen_n={result.budget.gen_n})</li>
<li>Wall-clock budget: {result.budget.total_seconds}s; actual elapsed: {result.elapsed_s:.1f}s</li>
</ul>
</section>
<section>
<h2>All trials</h2>
<table><thead><tr><th>Trial</th><th>Stage</th><th>Status</th><th>Threads</th><th>KV</th><th>FA</th>\
<th>Gen t/s</th><th>Prefill t/s</th></tr></thead><tbody>{trial_rows}</tbody></table>
</section>
</body>
</html>
"""
