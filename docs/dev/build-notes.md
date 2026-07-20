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
