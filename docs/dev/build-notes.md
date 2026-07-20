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
