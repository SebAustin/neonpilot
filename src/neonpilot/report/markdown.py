"""Render a Markdown report from a completed sweep (PLAN.md section 1.2, FR3).

Pure function of `(SweepResult, ChipReport)` -- no I/O, no live timestamps generated here (all
dates come from the data itself), so it's golden-file testable.
"""

from __future__ import annotations

from neonpilot.models import ChipReport, SweepResult, TrialResult

_DEGRADED_CONFIRM_NOTE = (
    "**Methodology caveat:** the confirm pass was dropped to fit the time budget, so the "
    "speedup figure below is computed from sweep-phase samples (baseline vs. best candidate), "
    "not a back-to-back confirm measurement. Treat it as a lower-confidence estimate "
    "(PLAN.md section 4.4)."
)


def _fmt_ts(sample) -> str:
    if sample is None:
        return "n/a"
    return f"{sample.avg_ts:.2f} +/- {sample.stddev_ts:.2f} t/s"


def _isa_table(chip: ChipReport) -> str:
    lines = ["| Feature | Present |", "|---|---|"]
    for feature, present in chip.isa.items():
        lines.append(f"| {feature} | {present} |")
    return "\n".join(lines)


def _fastpath_table(chip: ChipReport) -> str:
    lines = ["| Feature | Kernel | Active | Why |", "|---|---|---|---|"]
    for note in chip.fast_paths:
        lines.append(f"| {note.feature} | {note.kernel} | {note.active} | {note.why} |")
    return "\n".join(lines)


def _comparison_table(result: SweepResult) -> str:
    baseline, best = result.baseline, result.best
    lines = [
        "| Metric | Baseline | Tuned | Speedup |",
        "|---|---|---|---|",
        f"| Generation t/s | {_fmt_ts(baseline.generation)} | {_fmt_ts(best.generation)} | "
        f"{result.speedup_gen_pct:+.1f}% |",
        f"| Prefill t/s | {_fmt_ts(baseline.prefill)} | {_fmt_ts(best.prefill)} | "
        f"{result.speedup_prefill_pct:+.1f}% |",
    ]
    return "\n".join(lines)


def _status_counts(trials: list[TrialResult]) -> dict[str, int]:
    counts = {"ok": 0, "pruned": 0, "error": 0}
    for trial in trials:
        counts[trial.status] = counts.get(trial.status, 0) + 1
    return counts


def _methodology_section(result: SweepResult) -> str:
    counts = _status_counts(result.trials)
    lines = [
        f"- Repetitions per config: {result.budget.reps} (`-r {result.budget.reps}`), "
        f"prompt_n={result.budget.prompt_n}, gen_n={result.budget.gen_n}",
        f"- Wall-clock budget: {result.budget.total_seconds}s; actual elapsed: "
        f"{result.elapsed_s:.1f}s",
        f"- Trials: {counts['ok']} measured, {counts['pruned']} pruned (early-stop or budget), "
        f"{counts['error']} errored",
        f"- llama.cpp commit: `{result.llama_cpp_commit}`",
        f"- Winning config: threads={result.best.config.threads}, "
        f"cache_type={result.best.config.cache_type_k}/{result.best.config.cache_type_v}, "
        f"flash_attn={result.best.config.flash_attn}, "
        f"batch/ubatch={result.best.config.batch}/{result.best.config.ubatch}",
    ]
    if result.budget_truncated:
        lines.append(f"- **Budget truncated.** Dropped: {', '.join(result.dropped_stages)}.")
        if "confirm" in result.dropped_stages:
            lines.append(f"- {_DEGRADED_CONFIRM_NOTE}")
    return "\n".join(lines)


def _trials_table(trials: list[TrialResult]) -> str:
    lines = [
        "| Trial | Stage | Status | Threads | KV | FA | Gen t/s | Prefill t/s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for trial in trials:
        gen = f"{trial.generation.avg_ts:.2f}" if trial.generation else "-"
        prefill = f"{trial.prefill.avg_ts:.2f}" if trial.prefill else "-"
        lines.append(
            f"| {trial.trial_id} | {trial.stage} | {trial.status} | {trial.config.threads} | "
            f"{trial.config.cache_type_k} | {trial.config.flash_attn} | {gen} | {prefill} |"
        )
    return "\n".join(lines)


def render_markdown(result: SweepResult, chip: ChipReport) -> str:
    """Render the full Markdown report for a completed sweep."""
    sections = [
        f"# neonpilot report: {chip.chip_name} / {result.model_class}",
        "",
        f"Model file: `{result.model_file}`  |  llama.cpp commit: `{result.llama_cpp_commit}`  |  "
        f"schema: `{result.schema_version}`",
        "",
        "## Chip ISA features",
        "",
        _isa_table(chip),
        "",
        "## llama.cpp fast-path activation",
        "",
        _fastpath_table(chip),
        "",
        "## Baseline vs. tuned",
        "",
        _comparison_table(result),
        "",
        "## Methodology",
        "",
        _methodology_section(result),
        "",
        "## All trials",
        "",
        _trials_table(result.trials),
        "",
    ]
    return "\n".join(sections)
