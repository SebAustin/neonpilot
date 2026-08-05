# Build notes — deviations from PLAN.md (M0-M2)

Recorded per the "if the plan is ambiguous or wrong, make the smallest sensible choice and
record it here" rule. None of these change a dataclass field name/type from PLAN.md section
1.3; they're implementation choices in the gaps the plan leaves open.

1. **`bench/runner.run_bench(cfg=...)` accepts `RuntimeConfig | None`.** PLAN.md's interface
   table types this parameter as `RuntimeConfig` (not `Optional`), but section 3.3 requires the
   baseline trial to use "the same argv minus all tuning flags" -- and `SearchPlan.baseline` is
   *already* typed `RuntimeConfig | None` with `None` meaning "no tuning flags applied". Typing
   `run_bench`'s `cfg` the same way is a direct extension of an existing pattern in the same
   plan, not a new concept. `build_argv` omits `-t/-ctk/-ctv/-fa/-b/-ub` entirely when
   `cfg is None`.

2. **`bench/thermal.cooldown()` always returns a `ThermalSnapshot`, never `None`.** The
   interface table types the return as `ThermalSnapshot | None`. Every code path in this
   implementation (idle-skip, adaptive wait, elapsed-fallback) produces a meaningful snapshot,
   so there was no case where returning `None` communicated anything a `ThermalSnapshot` with
   `source="elapsed-fallback"` doesn't already say. The `| None` in the signature is kept for
   forward compatibility (e.g. a future "cooldown disabled entirely" policy) but is unused today.

3. **`probe/linux_cpuinfo.read_chip_report` cannot report real RAM or P/E-core split.** The
   PLAN-specified signature is `read_chip_report(cpuinfo_text, hwcap, hwcap2)` -- no `/proc/
   meminfo` text is passed in, and generic `/proc/cpuinfo` has no per-core performance/
   efficiency tier field (that distinction is Apple-Silicon-specific; Graviton cores are
   homogeneous anyway). Implementation: `ram_gb=0.0` always on Linux, `p_cores=total_cores`,
   `e_cores=0`. This is explicitly non-blocking per REQUIREMENTS.md ("Linux ... designed to
   work, untested"; CI is macOS-only per section 7.1). Follow-up: add an optional `meminfo_text`
   parameter if Linux support is ever hardened past "untested".

4. **`ChipReport.ram_gb` uses binary GiB (`/ 1024**3`), not decimal GB (`/ 1e9`).** M1 Max's
   `hw.memsize = 68719476736` divides to an exact `64.0` in GiB, matching the "~64 GiB" figure
   already used throughout `docs/dev/day1-spikes.md` and `PLAN.md` section 0/33. Decimal GB
   would report `68.72`, which reads as wrong against the documented spec sheet number.

5. **Single combined bench fixture, `tests/fixtures/llama_bench_smollm2.json`**, instead of
   PLAN.md M2's `llama_bench_pp.json` + `llama_bench_tg.json` pair. Per the build brief for this
   milestone, one real `llama-bench -o json` capture (SmolLM2-135M, `-p 64 -n 32 -r 2`) already
   contains both a `pp` row (`n_prompt=64`) and a `tg` row (`n_gen=32`) in a single array, which
   `bench/parser.py` classifies per-row -- no information is lost by keeping it as one file, and
   it matches how a real single `run_bench` call actually returns both rows together.

6. **`fastpath.explain()` tiering algorithm (NEON < DOTPROD < I8MM < SME2) is a designed
   extrapolation**, not verbatim from PLAN.md. The plan gives the M1 Max case exactly (i8mm
   ABSENT -> DOTPROD-tier KleidiAI engaged, docs/dev/day1-spikes.md S3) and says M5 is "expected
   to select SME-tier". This module encodes "highest available tier wins; lower tiers the chip
   also has are reported present-but-superseded" as the general rule connecting those two
   verified/expected data points, so `sysctl_apple_m5_synthetic.txt` (i8mm=1, sme2=1) exercises
   the SME2 path without contradicting the M1 Max fixture's DOTPROD-tier note.

7. **Added `probe/collector.py` and `probe/render.py`**, not named in PLAN.md section 1.2's
   module table (which lists only `macos_sysctl.py`, `linux_cpuinfo.py`, `fastpath.py`,
   `__init__.py` under `probe/`). These are additive, not contract changes: `collector.py` is
   the single subprocess/`ctypes` boundary the design rule already requires ("adapters take
   injected text, never call subprocess themselves" implies *something* does the live read);
   `render.py` keeps `cli.py` a thin Typer/Rich shell per its own stated responsibility
   ("Typer commands, Rich rendering") without importing probe internals inline in `cli.py`.

## M5 fixture status

`tests/fixtures/sysctl_apple_m5_synthetic.txt` is clearly labeled synthetic in its own header
comment and is used *only* to unit-test the SME2 code path in `fastpath.explain`/
`macos_sysctl.read_chip_report`. It must be replaced with a real M5 `sysctl -a` capture during
milestone M5 (ASSUMPTIONS.md #6); it is never presented as measured hardware data.

# Build notes — deviations from PLAN.md (M3-M4)

8. **`search/planner.plan` builds Stage B/C candidates with a *placeholder* thread count
   (the chip's P-core count), not the actual Stage A winner.** PLAN.md section 1.2 types
   `planner.plan(chip, budget) -> SearchPlan` as a pure function of the probe snapshot and the
   budget -- it has no access to *measured* results, so it cannot know Stage A's real winner
   ahead of time. `search/engine.py` uses `dataclasses.replace(cfg, threads=stage_a_winner....)`
   to substitute the real winning thread count (and, for Stage C, the real winning
   flash_attn/cache_type) into each Stage B/C candidate immediately before benching it. This
   is the only way to reconcile "planner is pure" (section 1.2) with "Stage B varies fa/kv
   with threads=A*" (section 4.1) without planner depending on engine internals.

9. **`search/engine.run`'s `run_bench`/`cooldown_fn` are keyword-only injected parameters, not
   part of the frozen `SweepContext`.** This matches `SweepContext`'s own docstring comment in
   PLAN.md section 1.3 ("runner is dependency-injected as a callable so engine is unit-testable
   with a mock") -- a callable can't live in a frozen, JSON-serializable dataclass, so it's
   threaded through as a `run()` keyword argument instead, defaulting to the real
   `bench.runner.run_bench` / `bench.thermal.cooldown`.

10. **Candidate-level early-stop pruning is generalized, not per-knob-monotonic.** PLAN.md
    section 4.3 describes pruning as "the current best dominates a candidate AND the remaining
    candidates are monotonically worse along the swept axis" (a per-stage, per-knob condition).
    This implementation applies a conservative superset of that rule: whenever the running
    incumbent (best trial anywhere in the sweep so far, updated after each trial) statistically
    dominates a just-measured candidate, the *rest of that candidate's stage* is pruned
    immediately, without a separate per-knob monotonicity check. This prunes at least as
    eagerly as the plan's literal rule and never prunes a candidate already benched; it trades
    a small amount of specificity (it could in principle prune a stage slightly earlier than a
    hand-tuned per-knob rule would) for a simple, uniform, fully-tested implementation across
    all three stages. See `search/_stage_runner.py` and `tests/test_stage_runner.py`/
    `tests/test_engine.py` for the exact semantics and worked examples.

11. **Budget truncation only ever drops Stage C and/or the confirm pass, never Stage A/B.**
    PLAN.md section 4.4 states the drop order as "adaptive extras -> Stage C -> confirm pass"
    and separately notes "Stage A and Stage B (the gain-bearing knobs) are dropped last" as a
    theoretical last resort. This implementation stops at "never drop A/B": with the documented
    budgets (180s CI / 900s full-model, section 4.4's worst-case table), Stage A/B never come
    close to needing truncation, so a pathological "budget so tiny even Stage A doesn't fit"
    path is deliberately not implemented. If it's ever hit, the engine still completes Stage A/B
    in full (not silently truncating further) rather than degrading measurement quality beyond
    what `budget_truncated`/`dropped_stages` already communicate honestly.

12. **`cli.py`'s default cooldown is budget-aware** (3s fixed/cap for `--budget <= 300`, 20s
    above that), rather than always using the full-model 20s default from PLAN.md section 4.4.
    Using a flat 20s regardless of `--budget` would make a CI-scale (180s) `optimize` run spend
    ~15 gaps * 20s = 300s on cooldown alone -- more than the entire CI budget -- which
    contradicts the plan's own stated CI cooldown default of 3s (section 4.4: "fixed_delay_s
    (default 20s full-model / 3s CI)"). A `--cooldown-s` override is also exposed for explicit
    control (e.g. `--cooldown-s 0` in the fast CLI unit tests, so they never really sleep).

13. **`neonpilot apply`'s positional argument is dual-purpose**: if it points at an existing,
    loadable preset JSON file, `apply` validates and prints that preset's invocation (FR4:
    "apply can re-emit the exact llama-bench invocation for a stored preset"); otherwise it
    packages `--run-dir`'s (or the latest run's) winning config as a *new* preset under
    `--presets-root` (FR4: "apply writes ... a presets/<chip-id>/<model-class>.json file").
    PLAN.md's CLI stub table doesn't fully disambiguate these two documented `apply` behaviors
    into separate flags/subcommands, so this implementation reconciles them into one command
    with branching logic, documented in the command's own `--help` text.

14. **`Preset.chip.probed_at`/`TrialResult.started_at`/`ended_at` etc. are real wall-clock ISO
    timestamps in production, but golden-file tests (`tests/test_report_*.py`,
    `tests/test_preset_*.py`) use a fixture (`sample_chip_report`, `sample_sweep_result` in
    `tests/conftest.py`) with all timestamps frozen to a fixed string.** `report/markdown.py`
    and `report/html.py` never call `datetime.now()` themselves (they are pure functions of
    their inputs), so this is purely a test-fixture concern, not a production behavior change.

# Test-engineer pass — baseline-credibility investigation (M0-M4 audit)

15. **Investigated: a real 180s-budget `optimize` run on SmolLM2-135M reported
    `speedup_gen_pct=+394.2%`** -- implausible for thread/KV/flash-attn tuning alone (expected
    magnitude per the task brief: single to low-double-digit %). Checked every suspect named in
    the audit brief:
    - **Wrong baseline thread count?** No. `bench/runner.build_argv` omits `-t/-ctk/-ctv/-fa/-b/
      -ub` entirely when `cfg is None` (verified by a new test,
      `test_baseline_argv_omits_every_tuning_flag`), so the baseline call really does let
      llama.cpp resolve its own defaults. Ran the real pinned binary directly with no `-t` flag
      on this machine: `n_threads=8, type_k=type_v=f16, flash_attn=-1 (auto), n_batch=2048,
      n_ubatch=512` -- exactly what `search/_trial.BASELINE_DISPLAY_CONFIG` assumes and exactly
      PLAN.md section 0's verified M1 Max default. No drift found; locked in by
      `tests/test_baseline_credibility.py::test_baseline_display_config_matches_llama_cpp_defaults_on_m1_max`
      and `::test_real_llama_bench_fixture_confirms_m1_max_defaults`.
    - **pp/tg row mix-up in the parser?** No. `bench/parser._classify` and
      `search/_trial.execute_trial`'s `next(s for s in samples if s.test_type == "pp"/"tg")`
      selection are type-based, not index-based, and produce the same `(prefill, generation)`
      assignment regardless of which order llama-bench emits the two rows in -- verified with a
      new test that feeds both orderings (`test_execute_trial_never_mixes_up_pp_and_tg_regardless_of_row_order`)
      plus pp-only/tg-only response tests that assert the *other* field stays `None` rather than
      falling back to the wrong sample.
    - **Cold-start/model-load included in the first measurement?** Partially relevant, but not a
      code defect: `search/engine._run_confirm_or_fallback` DOES re-measure the baseline
      back-to-back with the winner in the confirm pass specifically to cancel out cold-start/
      warm-cache bias (PLAN.md section 9); this ran to completion (no truncation) on the
      reproduction below.
    - **Actual root cause, reproduced on real hardware:** ran
      `uv run neonpilot optimize --budget 180 --reps 2` against the real pinned llama-bench
      binary and the real SmolLM2-135M-Instruct-Q4_K_M model twice. Both real runs completed
      the full sweep (`budget_truncated=False`) and finished under budget
      (`elapsed_s≈148s`), so this was not a confirm-pass-truncation artifact. The captured
      per-config samples show **enormous intra-config variance** on this dev laptop, e.g. one
      Stage A trial's two reps for the *same* config were `[18.9114, 5.95587]` t/s (a 3.2x
      spread) and a different Stage A trial's generation throughput dropped from 76.6 t/s
      (threads=6, run first) to 13.1 t/s (threads=8, run seconds later) -- a swing far larger
      than any thread-count effect could plausibly produce, consistent with thermal/CPU-
      frequency or background-process contention noise on the shared dev machine, not a
      configuration difference. With `--reps 2` (below PLAN.md section 4.3's documented "reps
      >= 3" minimum) a single unlucky baseline rep paired with a single lucky candidate rep is
      arithmetically sufficient to produce a 300-400% "speedup" that is pure sampling noise.
      Neither engine nor parser logic is at fault; the tool simply had no guard against
      presenting a noise-dominated ratio as an authoritative headline number.
    - **Fix applied (minimal, no measurement-math change):** reused the exact same
      `bench.stats.dominates()` statistical-dominance test the engine already uses for
      early-stopping (PLAN.md section 4.3, k=1.0) as a **reporting-time credibility guard**:
      `report/markdown.py` and `report/html.py` now append a "Statistical caution" caveat
      whenever `not dominates(result.best, result.baseline)`, and `cli.py`'s console summary
      prints the same warning plus a separate warning whenever `--reps` is below the
      documented minimum of 3. This makes an implausible/noisy headline number impossible to
      miss without changing how baseline or candidates are measured. Golden report fixtures
      are unaffected (`sample_sweep_result`'s confirm pass, 40->60 t/s at stddev=1.0, clearly
      dominates, so the caveat does not fire on the existing golden files).
    - **Re-run after the fix:** re-ran `uv run neonpilot optimize --budget 180 --reps 2`
      against the real binary/model a third time; result was `speedup_gen_pct=+54.9%` with
      `budget_truncated=False` (full sweep + confirm pass ran) -- still elevated for a
      thread/KV-tuning story (a 135M model's decode throughput is small-enough-magnitude that
      Stage A/B/C's own variance across trials was itself double-digit-percent on this noisy
      machine), and the new caveat correctly fired given the underlying samples' overlapping
      confidence bands. **Recommendation for the M5 real-hardware run (Qwen2.5-3B, the actual
      SC2 reference model): use `--reps >= 3` (the documented/CLI default) and run on an
      otherwise-idle machine** -- the 135M CI model at `--reps 2` is a stress-test of the
      credibility guard, not evidence of a code defect, and is not the model SC2 is measured
      against.

# Robustness-review pass 1 (Phase 1: fixes) — external review, reproduced with stub binaries

16. **Fixed all CRITICAL/HIGH/MEDIUM findings from an independent robustness review of
    `src/neonpilot/`, plus two LOW findings.** Each item below is a separate, small commit;
    every fix ships with a regression test that mirrors the reviewer's stub-binary/synthetic-
    artifact reproduction setup. Two changes extend PLAN.md section 1.3's dataclass contract
    (documented here per that section's own instruction to log deviations):

    - **`TrialResult.is_synthetic_config: bool = False`** -- True only for the baseline/
      confirm-baseline trial's `.config`, which is a *reconstruction* of what llama.cpp is
      expected to resolve to (no `-t/-ctk/-ctv/-fa` flags are passed for that call, so nothing
      in `BenchSample` actually carries the resolved values) -- never a measured, appliable
      config. Additive with a default, so it hydrates cleanly from every pre-existing
      `result.json` via `_hydrate.from_dict`'s now-lenient-default behavior (see below).
    - **`SweepContext.baseline_threads: int = 8`** -- the thread count llama.cpp is expected to
      resolve to (the chip's own P-core count) when no `-t` flag is given; used only to build
      the baseline trial's *display* config, never its argv. `cli.py` now passes the real
      probed `chip.p_cores` instead of the previously-hardcoded `8`.

    Fix summary (C1/H1-H6/M1-M6, one bullet per reviewer finding ID):

    - **C1 (critical):** a sweep where every trial errors previously exited 0 and printed a
      bogus `best: confirm-baseline gen_ts=n/a` success line; `apply` would then happily
      package the never-measured synthetic baseline config as a "winning" preset. `optimize`
      now checks `result.best.status != "ok" or result.best.generation is None` after writing
      artifacts (for post-mortem debugging) and exits 1 with every distinct trial error printed
      first; `apply`'s preset-packaging path (`_build_preset_from_run`) independently refuses
      the same condition, plus (H3) refuses whenever `best.is_synthetic_config` is True.
    - **H1:** `bench/runner.run_bench` only caught `FileNotFoundError`; widened to `OSError` so
      `PermissionError` (binary exists, missing +x) and "Exec format error" (wrong-arch binary)
      produce a clean `BenchRunError` instead of a raw traceback.
    - **H2:** `artifacts.new_run_dir` no longer touches the `latest` symlink at all; a new
      `artifacts.mark_latest(run_dir)` is called from `cli.py` only *after* `result.json` is
      written and only when the sweep produced a usable `best` (i.e. C1's check passed) --
      repointing `latest` atomically via a temp-named symlink + `os.replace`, warning (not
      silently passing) on `OSError`.
    - **H3:** see the two new dataclass fields above; both report emitters
      (`report/markdown.py`, `report/html.py`, via a new shared `report/_shared.py` helper)
      render "defaults (as resolved by llama-bench; tuning did not beat the baseline)" instead
      of a fabricated `threads=.../cache_type=...` line whenever `best.is_synthetic_config`.
    - **H4:** `report`/`apply --run-dir`'s artifact loading is now centralized in
      `cli._load_run_artifacts`, which translates `JSONDecodeError`/`TypeError`/`OSError` into
      a friendly stderr message + `Exit(1)`, mirroring the pre-existing preset-load handler.
      `report`'s `report.md`/`report.html` writes are similarly guarded against `OSError`.
    - **H5:** `--budget`/`--reps`/`--cooldown-s` gained `typer.Option(min=..., max=...)` bounds
      (`--reps`'s upper bound reuses `preset.schema.MAX_REPS`, renamed from `_MAX_REPS` to be
      importable, so the CLI and the preset schema it eventually feeds can't drift apart).
    - **H6:** `search/_stage_runner.run_stage` gained an optional `budget_tracker` parameter
      (a `typing.Protocol`, to avoid a circular import with `search/engine.py`); when given, it
      stops *starting* new Stage A/B/C candidates once the tracker projects the remainder won't
      fit the budget (an in-flight trial always finishes; only the next one is skipped) and
      returns a new `budget_exceeded` flag. `cli.py` prints a warning whenever
      `result.elapsed_s > budget` and gained a `--timeout-s` option (default 120, previously a
      hardcoded constant) for large models needing a longer per-invocation timeout.
    - **M1:** `bench/parser.py` now rejects non-finite (`NaN`/`Infinity`/`-Infinity`, which
      `json.loads` accepts by default despite RFC 8259 disallowing them) or negative
      `avg_ts`/`stddev_ts`/`samples_ts` values with a `BenchParseError`, instead of letting them
      propagate into a non-RFC-8259 `result.json` and an SVG `<rect width="nan">`.
    - **M2:** `cli.optimize` installs a SIGTERM handler (for the duration of `engine.run` only)
      that raises `KeyboardInterrupt`. CPython's own `subprocess.run` already kills its child
      and re-raises on `KeyboardInterrupt` during `communicate()` -- that machinery only ever
      fired on SIGINT before this fix, since Python's default SIGTERM disposition is silent
      termination with no exception at all, orphaning the `llama-bench` child. No change needed
      in `bench/runner.py`.
    - **M3:** every CLI command now wraps its implementation in
      `try/except typer.Exit: raise / except (OSError, RuntimeError, NotImplementedError):
      cli._handle_top_level_error(...)`, printing a one-line stderr message + `Exit(1)` instead
      of a raw traceback; a new `--debug` flag (set via `ctx.obj` in the app's `@app.callback`)
      opts back into the full exception for troubleshooting. Note: `typer.Exit`/click's `Exit`
      is (surprisingly) a `RuntimeError` subclass, so the `except typer.Exit: raise` guard
      must come first, or every intentional `Exit` raised deeper in the call stack gets
      re-wrapped as if it were a genuine error -- caught by this work's own new regression
      tests before it shipped.
    - **M4:** `optimize` now requires `model.is_file()` (not just `.exists()`, which accepted a
      directory or a 0-byte file) and sniffs the first 4 bytes for the `GGUF` magic, both
      before a sweep starts; `model_class` (derived from the filename) is validated with
      `preset.io.sanitize_slug` (renamed from `_sanitize_slug` to be reusable across modules)
      before the sweep starts too, instead of only failing at `apply` time after the sweep
      already ran.
    - **M5:** added a `--target-temp-c` option (default `None`, preserving the previous
      fallback behavior) wired into `CooldownPolicy.target_temp_c`, making the already-
      implemented and already-tested adaptive-cooldown branch in `bench/thermal.py` reachable
      from the CLI for the first time.
    - **M6:** `_hydrate.from_dict`'s dict-typed-field branch (e.g. `ChipReport.isa`) now
      validates the value is actually a dict and recursively validates every key/value against
      the declared types, instead of skipping validation entirely (previously
      `"isa": "not-a-dict"` was accepted and only failed later, deep inside a report renderer,
      with an obscure `AttributeError`). Independently, `from_dict` now falls back to a
      dataclass field's own declared `default`/`default_factory` when a key is missing from the
      source dict, instead of always raising -- this is the mechanism that lets
      `is_synthetic_config`/`baseline_threads` (and Phase 2's additive fields) hydrate cleanly
      from an artifact that predates them. Both branches had **zero** test coverage before this
      pass despite backing every backward-compatibility guarantee in the codebase; both are
      directly covered now.
    - **LOW (apply typo'd-path misreport):** `apply <typo'd-path>` previously fell through to
      `_resolve_run_dir`'s "run directory not found" message, which is misleading when the
      user's intent was clearly a preset file (not a directory). `_apply_impl` now
      distinguishes "not a file and not a directory" (typo -> new, clearer message) from "is an
      existing directory" (the pre-existing, undocumented dual-mode fallback to run-dir
      resolution, left unchanged).
    - **LOW (unbounded `capture_output`):** documented (not fixed) in `bench/runner.py`:
      `subprocess.run(capture_output=True, ...)` has no cap on stdout/stderr size, so a
      misbehaving `llama-bench` build flooding stdout could grow memory unbounded before
      `timeout_s` fires. Accepted for the same reason as the existing rlimit note in that file
      (local, single-user, no privilege boundary) rather than replacing it with a custom
      bounded-read `Popen` loop.

# Phase 2 (approved scope): load telemetry (F-A) + compare command (F-B)

17. **F-A load telemetry.** New `bench/sysload.py` mirrors `probe/collector.py`'s split: a
    pure `parse_ps_output()` parser for `ps -Ao pcpu,comm -r` (skips the header row by
    checking whether each line's first token parses as a float, not a fixed line count;
    handles `comm` values containing spaces, e.g. a macOS app-bundle path with a
    parenthesized helper-process suffix) and a thin `collect_load_snapshot()` collector
    (`os.getloadavg()` + the top-3 `ps` rows) that degrades to an empty process list on a
    `ps` failure rather than raising -- this telemetry is a report-caveat nice-to-have, never
    worth failing a sweep over. New frozen dataclasses `ProcessSample`/`LoadSnapshot`;
    `SweepResult.load_before`/`load_after: LoadSnapshot | None = None` are additive (both
    default `None`), so `tests/test_artifacts.py`'s new backward-compat test confirms the
    already-committed `docs/results/m1-max-loaded-20260720/result.json` (which predates this
    field, `is_synthetic_config`, and `baseline_threads` entirely) still hydrates cleanly.
    `search/engine.run()` gains an injected `collect_load` callable (same DI pattern as
    `run_bench`/`cooldown_fn`, defaulting to the real collector), called once before the
    baseline trial and once after the confirm pass. `cli.optimize` preflights
    `loadavg_1m / chip.total_cores`: above 0.5 it warns (citing the exact ratio); a new
    `--strict-idle` flag aborts with `Exit(1)` instead, before any run directory is created.
    Both report emitters render a "Measurement conditions" methodology line (via a new
    shared `report/_shared.py:measurement_conditions_text()`) whenever `load_before` was
    recorded, omitting the line entirely otherwise (no blank/misleading placeholder).

18. **F-B compare command.** `neonpilot compare <run_dir_a> <run_dir_b>` writes `compare.md` +
    a self-contained `compare.html` (into `run_dir_a` by default, `--out` to override; the
    target directory is created if it doesn't exist yet -- caught by a regression test before
    it shipped, since `report`/`apply` never needed this, always writing into an
    already-existing run dir). Both artifact loads go through the same
    `cli._load_run_artifacts` helper `report`/`apply --run-dir` use, so a missing/truncated
    artifact on *either* side gets the same friendly message + `Exit(1)`, not a raw
    traceback, from day one. `report/compare.py` renders: a chip ISA feature table with
    delta-highlighted rows (a CSS class in HTML, a "Differs" column in Markdown) for any
    feature present on only one side; each machine's own baseline-vs-tuned throughput
    charts, reusing `report/_shared.py`'s SVG bar-chart helpers (extracted from `report/
    html.py` in a preceding pure-refactor commit -- `_esc`/`_bar`/`_comparison_chart`/
    `_CHART_WIDTH` etc. became `report/_shared.py`'s public `esc`/`bar`/`comparison_chart`,
    with zero behavior change, confirmed by the unchanged-except-for-one-new-CSS-rule golden
    `report.html` diff); a winning-config field-by-field diff table (threads, KV cache
    type(s), flash-attn, batch/ubatch); and each side's F-A measurement conditions when
    recorded. Golden-file tests use two synthetic `SweepResult`s: the existing M1-like
    `sample_sweep_result` and a new M5-like `sample_sweep_result_m5` (paired with
    `sample_chip_report_m5`, itself derived from the already-committed, clearly-labeled-
    synthetic `sysctl_apple_m5_synthetic.txt` fixture -- never presented as a real
    measurement, consistent with that fixture's own header comment).
