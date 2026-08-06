"""Render a side-by-side comparison report between two completed sweep runs (feature F-B).

Pure functions of `(SweepResult, ChipReport)` pairs -- no I/O, so golden-file testable, same
discipline as report/markdown.py and report/html.py. Reuses report/_shared.py's escaping and
SVG bar-chart helpers so a compare report's charts render identically to a single-run report's
"Baseline vs. tuned" charts, just once per machine.
"""

from __future__ import annotations

from collections.abc import Callable

from neonpilot.models import ChipReport, RuntimeConfig, SweepResult, TrialResult
from neonpilot.report._shared import CSS, comparison_chart, esc, measurement_conditions_text
from neonpilot.report._shared import winning_config_text as _winning_config_text

#: (field label, getter) pairs for the config-choice diff table -- covers every field PLAN.md
#: section 4.1 tunes (threads, KV cache type, flash-attn, batch/ubatch).
_CONFIG_FIELDS: list[tuple[str, Callable[[RuntimeConfig], object]]] = [
    ("threads", lambda cfg: cfg.threads),
    ("cache_type_k", lambda cfg: cfg.cache_type_k),
    ("cache_type_v", lambda cfg: cfg.cache_type_v),
    ("flash_attn", lambda cfg: cfg.flash_attn),
    ("batch", lambda cfg: cfg.batch),
    ("ubatch", lambda cfg: cfg.ubatch),
]

#: N2: shown per-cell (not the fabricated defaults value) whenever that side's winning trial
#: is synthetic (H3) -- see `_config_diff_rows` below.
_SYNTHETIC_CELL_TEXT = "defaults (not measured)"

_ConfigDiffRow = tuple[str, str, str, bool]


def _all_isa_features(chip_a: ChipReport, chip_b: ChipReport) -> list[str]:
    """Union of both chips' ISA feature keys, sorted for a stable table order -- a compare
    report must not silently drop a feature present on only one side."""
    return sorted(set(chip_a.isa) | set(chip_b.isa))


def _config_diff_rows(best_a: TrialResult, best_b: TrialResult) -> list[_ConfigDiffRow]:
    """Return `(field_label, value_a, value_b, differs)` for every tuned config field.

    N2 (follow-up to H3): `best.config` is a *fabricated* reconstruction of llama.cpp's own
    defaults whenever `best.is_synthetic_config` is True (tuning never beat that side's
    baseline) -- rendering it as a plain measured value, with a "differs: yes" marker against
    the other side's real winning config, would misleadingly present a placeholder as data.
    When either side is synthetic, that side's cell reads `_SYNTHETIC_CELL_TEXT` instead of
    the fabricated field value, and the differs marker is suppressed for the whole row (a
    synthetic-vs-measured comparison isn't a meaningful "delta" to highlight).
    """
    any_synthetic = best_a.is_synthetic_config or best_b.is_synthetic_config
    rows = []
    for label, getter in _CONFIG_FIELDS:
        cell_a = _config_cell_text(best_a, getter)
        cell_b = _config_cell_text(best_b, getter)
        differs = False if any_synthetic else getter(best_a.config) != getter(best_b.config)
        rows.append((label, cell_a, cell_b, differs))
    return rows


def _config_cell_text(best: TrialResult, getter: Callable[[RuntimeConfig], object]) -> str:
    if best.is_synthetic_config:
        return _SYNTHETIC_CELL_TEXT
    return str(getter(best.config))


# --- Markdown -----------------------------------------------------------------------------


def _feature_table_markdown(
    chip_a: ChipReport, chip_b: ChipReport, label_a: str, label_b: str
) -> str:
    lines = [f"| Feature | {label_a} | {label_b} | Differs |", "|---|---|---|---|"]
    for feature in _all_isa_features(chip_a, chip_b):
        present_a = chip_a.isa.get(feature, False)
        present_b = chip_b.isa.get(feature, False)
        differs = "yes" if present_a != present_b else ""
        lines.append(f"| {feature} | {present_a} | {present_b} | {differs} |")
    return "\n".join(lines)


def _config_diff_table_markdown(result_a: SweepResult, result_b: SweepResult) -> str:
    lines = ["| Field | A | B | Differs |", "|---|---|---|---|"]
    for label, value_a, value_b, differs in _config_diff_rows(result_a.best, result_b.best):
        lines.append(f"| {label} | {value_a} | {value_b} | {'yes' if differs else ''} |")
    return "\n".join(lines)


def _throughput_section_markdown(label: str, result: SweepResult) -> str:
    baseline, best = result.baseline, result.best
    baseline_gen = baseline.generation.avg_ts if baseline.generation else 0.0
    tuned_gen = best.generation.avg_ts if best.generation else 0.0
    baseline_prefill = baseline.prefill.avg_ts if baseline.prefill else 0.0
    tuned_prefill = best.prefill.avg_ts if best.prefill else 0.0
    lines = [
        f"### {label}",
        "",
        "| Metric | Baseline | Tuned | Speedup |",
        "|---|---|---|---|",
        f"| Generation t/s | {baseline_gen:.2f} | {tuned_gen:.2f} | "
        f"{result.speedup_gen_pct:+.1f}% |",
        f"| Prefill t/s | {baseline_prefill:.2f} | {tuned_prefill:.2f} | "
        f"{result.speedup_prefill_pct:+.1f}% |",
        "",
        f"Winning config: {_winning_config_text(best)}",
    ]
    conditions = measurement_conditions_text(result.load_before)
    if conditions is not None:
        lines.append(f"Measurement conditions: {conditions}")
    return "\n".join(lines)


def render_compare_markdown(
    result_a: SweepResult,
    chip_a: ChipReport,
    result_b: SweepResult,
    chip_b: ChipReport,
    *,
    label_a: str | None = None,
    label_b: str | None = None,
) -> str:
    """Render a Markdown side-by-side comparison of two completed sweep runs."""
    label_a = label_a or chip_a.chip_name
    label_b = label_b or chip_b.chip_name
    sections = [
        f"# neonpilot compare: {label_a} vs. {label_b}",
        "",
        f"A: `{result_a.model_class}` on {chip_a.chip_name} | "
        f"B: `{result_b.model_class}` on {chip_b.chip_name}",
        "",
        "## Chip feature comparison",
        "",
        _feature_table_markdown(chip_a, chip_b, label_a, label_b),
        "",
        "## Throughput",
        "",
        _throughput_section_markdown(label_a, result_a),
        "",
        _throughput_section_markdown(label_b, result_b),
        "",
        "## Winning config diff",
        "",
        _config_diff_table_markdown(result_a, result_b),
        "",
    ]
    return "\n".join(sections)


# --- HTML -----------------------------------------------------------------------------------


def _feature_table_html(chip_a: ChipReport, chip_b: ChipReport, label_a: str, label_b: str) -> str:
    rows = []
    for feature in _all_isa_features(chip_a, chip_b):
        present_a = chip_a.isa.get(feature, False)
        present_b = chip_b.isa.get(feature, False)
        row_class = ' class="delta-highlight"' if present_a != present_b else ""
        rows.append(
            f"<tr{row_class}><td>{esc(feature)}</td><td>{esc(present_a)}</td>"
            f"<td>{esc(present_b)}</td></tr>"
        )
    return (
        f"<table><thead><tr><th>Feature</th><th>{esc(label_a)}</th><th>{esc(label_b)}</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _config_diff_table_html(result_a: SweepResult, result_b: SweepResult) -> str:
    rows = []
    for label, value_a, value_b, differs in _config_diff_rows(result_a.best, result_b.best):
        row_class = ' class="delta-highlight"' if differs else ""
        rows.append(
            f"<tr{row_class}><td>{esc(label)}</td><td>{esc(value_a)}</td>"
            f"<td>{esc(value_b)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Field</th><th>A</th><th>B</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _throughput_section_html(label: str, result: SweepResult) -> str:
    baseline, best = result.baseline, result.best
    baseline_gen = baseline.generation.avg_ts if baseline.generation else 0.0
    tuned_gen = best.generation.avg_ts if best.generation else 0.0
    baseline_prefill = baseline.prefill.avg_ts if baseline.prefill else 0.0
    tuned_prefill = best.prefill.avg_ts if best.prefill else 0.0
    conditions = measurement_conditions_text(result.load_before)
    conditions_p = (
        f"<p>Measurement conditions: {esc(conditions)}</p>" if conditions is not None else ""
    )
    return f"""<h3>{esc(label)}</h3>
{comparison_chart("Generation throughput", baseline_gen, tuned_gen, "t/s")}
{comparison_chart("Prefill throughput", baseline_prefill, tuned_prefill, "t/s")}
<p>Generation speedup: {esc(f"{result.speedup_gen_pct:+.1f}")}% | \
Prefill speedup: {esc(f"{result.speedup_prefill_pct:+.1f}")}%</p>
<p>Winning config: {esc(_winning_config_text(best))}</p>
{conditions_p}"""


def render_compare_html(
    result_a: SweepResult,
    chip_a: ChipReport,
    result_b: SweepResult,
    chip_b: ChipReport,
    *,
    label_a: str | None = None,
    label_b: str | None = None,
) -> str:
    """Render a self-contained HTML side-by-side comparison of two completed sweep runs.

    Zero external fetches, same as report/html.py -- inline CSS/SVG, no `<script>` tags.
    """
    label_a = label_a or chip_a.chip_name
    label_b = label_b or chip_b.chip_name

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>neonpilot compare: {esc(label_a)} vs. {esc(label_b)}</title>
<style>{CSS}</style>
</head>
<body>
<h1>neonpilot compare: {esc(label_a)} vs. {esc(label_b)}</h1>
<p>A: <code>{esc(result_a.model_class)}</code> on {esc(chip_a.chip_name)} | \
B: <code>{esc(result_b.model_class)}</code> on {esc(chip_b.chip_name)}</p>
<section>
<h2>Chip feature comparison</h2>
{_feature_table_html(chip_a, chip_b, label_a, label_b)}
</section>
<section>
<h2>Throughput</h2>
{_throughput_section_html(label_a, result_a)}
{_throughput_section_html(label_b, result_b)}
</section>
<section>
<h2>Winning config diff</h2>
{_config_diff_table_html(result_a, result_b)}
</section>
</body>
</html>
"""
