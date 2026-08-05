# neonpilot

**An on-device LLM auto-tuner for Arm CPUs that tells you *why*, not just *what*.**

[![CI](https://github.com/SebAustin/neonpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/SebAustin/neonpilot/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](./pyproject.toml)

Submission for the **Arm AI Optimization Challenge 2026** (Devpost), **Mobile AI** track.

> Status: milestones M0–M6 (scaffold, probe, bench harness, staged search, report + preset,
> reproducible `make benchmark`) are implemented and tested. A real 900s sweep on the M1 Max
> reference machine has been run end-to-end (see [Results](#results) below) — but under heavy
> ambient system load, so it's documented honestly as an adaptive/loaded-machine case study, not
> the idle-machine SC2 reference number. Re-running `make benchmark` on a quiet machine to
> capture that clean reference, and the separate Apple M5 cross-generation run, remain open.

---

## Project overview

Developers running GGUF models on Arm CPUs (Apple Silicon laptops today, Graviton/mobile
Arm tomorrow) have no easy way to know which `llama.cpp` runtime flags — thread count, KV-cache
quantization, flash-attention, batch/ubatch size — are actually optimal for *their* chip. Manual
sweeps are slow, unscientific, and don't explain *why* one config wins.

**neonpilot** is a Python CLI that wraps a pinned build of `llama.cpp` and does three things:

1. **Probes** the host Arm CPU and explains, in plain English, which `llama.cpp` Arm fast paths
   activate — down to the exact KleidiAI kernel *tier* (NEON → DOTPROD → I8MM → SME2), not just
   "NEON: yes".
2. **Optimizes** runtime flags via a staged, thermally-guarded benchmark sweep that completes in
   under 15 minutes, with early stopping and honest statistics (median ± stddev over ≥3 reps).
3. **Reports and packages** the result as a self-contained HTML/Markdown report and a versioned,
   shareable JSON preset that anyone with the same chip can reuse without re-running the sweep.

### Why this is interesting

- **Verified ISA-aware probing, not guesswork.** On the reference machine (Apple M1 Max),
  `neonpilot probe` reports real `sysctl` truth: `neon=true, dotprod=true, i8mm=false,
  sme=false, sme2=false` (`hw.optional.arm.FEAT_I8MM=0`, captured in
  [`tests/fixtures/sysctl_apple_m1_max.txt`](./tests/fixtures/sysctl_apple_m1_max.txt)). A
  verbose real `llama-bench -v` run on that same machine confirms exactly which kernel tier
  engages:

  ```
  kleidiai: primary q4 kernel feature DOTPROD
  kleidiai: primary q8 kernel feature DOTPROD
  kleidiai: SME disabled
  load_tensors:   CPU_Mapped model buffer size =    98.87 MiB
  load_tensors: CPU_KLEIDIAI model buffer size =    30.26 MiB
  load_tensors:   CPU_REPACK model buffer size =    17.28 MiB
  repack: repack tensor blk.0.ffn_down.weight with q6_K_8x4
  ```
  (full log: [`docs/dev/day1-spikes.md`](./docs/dev/day1-spikes.md) S3). neonpilot's probe copy
  states this precisely — "i8mm ABSENT → DOTPROD-tier KleidiAI kernels engaged; SME disabled;
  other quant types via CPU_REPACK q6_K_8x4" — rather than the generic "NEON: yes" most tools
  stop at.
- **Staged, thermally guarded search**, not a brute-force grid. Threads → flash-attention/KV-cache
  → batch/ubatch, each stage fixing the prior stage's winner, with statistical-dominance early
  stopping and an adaptive cooldown that skips waiting when the CPU is already cool.
- **Statistical honesty.** Every trial is measured with ≥3 repetitions (median/stddev from
  `llama-bench`'s own JSON), the final confirm pass re-measures baseline and winner back-to-back,
  and the report/CLI print an explicit **credibility caveat** whenever the tuned result doesn't
  statistically dominate the baseline — so an implausible or noise-dominated speedup can never be
  presented as a clean headline number (see [Methodology & honesty](#methodology--honesty)).
- **Reusable, versioned per-chip presets.** A preset captures the winning config plus full
  provenance (chip probe snapshot, pinned `llama.cpp` commit, measured t/s) and can re-emit the
  exact `llama-bench` invocation for anyone with the same chip — turning a one-off personal tuning
  run into a shareable community artifact.

---

## How it works

Four commands, one pipeline: `probe` → `optimize` → `report` → `apply`.

### `neonpilot probe`

Read-only host introspection — no model needed, runs in under 2 seconds.

```bash
uv run neonpilot probe            # Rich table: chip, topology, ISA features, fast paths
uv run neonpilot probe --json     # machine-readable ChipReport (schema_version 1.0.0)
```

On macOS this parses `sysctl -a` (`hw.optional.arm.*`, `hw.perflevel*`); on Linux it parses
`/proc/cpuinfo` plus `getauxval(AT_HWCAP/AT_HWCAP2)`. Output includes chip name, P-core/E-core/
total core counts, RAM, the full ISA feature dict (`neon`, `dotprod`, `i8mm`, `sve`, `sve2`,
`sme`, `sme2`, `bf16`, `fp16`), and one `FastPathNote` per feature with a one-line "why".

### `neonpilot optimize <model.gguf>`

Runs the staged sweep and writes a run directory of artifacts.

```bash
uv run neonpilot optimize ~/.neonpilot/models/qwen2.5-3b-instruct-q4_k_m.gguf
# full-model defaults: --budget 900 --reps 3 --prompt-n 512 --gen-n 128

uv run neonpilot optimize tiny.gguf --budget 180 --reps 3   # CI-scale sweep
```

**The staged sweep, A → B → C → confirm** (baseline is measured first):

| Stage | Knob(s) varied | Candidates (M1 Max example) |
|---|---|---|
| Baseline | none — `llama.cpp` defaults | 1 config (`-t/-ctk/-ctv/-fa/-b/-ub` all omitted) |
| A — threads/placement | thread count, derived from probed topology | `[6, 8, 9, 10]` |
| B — flash-attn × KV-cache | `flash_attn ∈ {off,on}` × `cache_type ∈ {f16,q8_0,q4_0}` | 6 pairs |
| C — batching | `(batch, ubatch)` pairs | `(2048,512)`, `(2048,1024)`, `(4096,2048)` |
| Confirm | re-measure baseline vs. final winner back-to-back | 2 configs |

Worst case (no pruning) is 1 + 4 + 6 + 3 + 2 = 16 configs, versus 36+ for a full Cartesian grid.
Each stage fixes the previous stage's winner (highest generation t/s, ties broken by prefill t/s,
then fewer threads) before varying the next knob group. After each fully-measured candidate,
`bench.stats.dominates()` checks whether the running best already beats it outside noise (k=1.0
stddev margin); if so, the rest of that candidate's stage is pruned and marked `status="pruned"`
in the artifacts (never a measurement in progress — pruning only removes future work).

**Budget and truncation guarantees.** The full-model budget is 900s (15 min); CI uses 180s. If
the projected remaining cost would exceed the budget, work is dropped in this strict order:
*adaptive cooldown extras → Stage C → the confirm pass* — Stage A/B (where the gains live) and
the confirm pass (needed for the fair back-to-back baseline comparison) are protected and dropped
last. Any truncation sets `budget_truncated=True` and lists the dropped stages in
`SweepResult.dropped_stages`, and the report states this plainly rather than hiding it.

### `neonpilot report`

```bash
uv run neonpilot report                       # renders from ~/.neonpilot/runs/latest
uv run neonpilot report --run-dir <run-dir>   # render a specific run
```

Writes `report.md` and a self-contained `report.html` (inline SVG bar charts, inline CSS, zero
`<script>` tags, zero external `http(s)://` asset references — opens correctly via `file://` in
Safari/Chrome/Firefox with no network calls). Both contain: chip ISA feature table, fast-path
activation table, baseline-vs-tuned comparison (generation + prefill t/s with stddev), full
methodology (reps, cooldown, budget, truncation notes), and every trial including pruned ones.

### `neonpilot apply`

Dual-purpose: re-emit an existing preset's invocation, or package a completed run as a new preset.

```bash
# Package the latest run's winner as a new preset under ./presets/<chip-id>/<model-class>.json
uv run neonpilot apply --run-dir ~/.neonpilot/runs/latest

# Load an existing preset, validate it, and print the exact llama-bench invocation
uv run neonpilot apply presets/apple-m1-max/qwen2.5-3b-instruct-q4_k_m.json
```

`apply` never executes a loaded preset's flags directly — it validates against the versioned
schema (`schema_version`, enum/range checks on every scalar field) and prints the invocation for
you to review and run yourself.

### Where artifacts land

| Artifact | Location |
|---|---|
| Per-run artifacts (`chip.json`, `plan.json`, `trials.json`, `result.json`, `run.log`, `report.{md,html}`) | `~/.neonpilot/runs/<ISO-timestamp>/`, with a `latest` symlink. `--out DIR` overrides (CI uses `--out ./runs`). |
| Curated, committed presets | `./presets/<chip-id>/<model-class>.json` (in-tree, reviewable diffs) |
| Downloaded/cached GGUF models | `~/.neonpilot/models/` |
| Pinned `llama.cpp` source + build | `vendor/llama.cpp/` (git-ignored — fetched, not vendored) |

Rationale for the split: run artifacts are ephemeral and machine-specific (they'd pollute
`git status` on every clean clone), while presets are small, curated deliverables meant to be
committed and diffed.

---

## Results

<!-- RESULTS:M1MAX -->
### Case study: loaded M1 Max (real-world conditions)

A real 900s `neonpilot optimize` sweep against the reference model (Qwen2.5-3B-Instruct
Q4_K_M, ~2.1 GB) completed on the Apple M1 Max reference machine (64 GB RAM, macOS 26.5,
`llama.cpp` pin `b10069`/`178a6c44`) while the machine was under **heavy ambient load**: Docker
Desktop ~54% CPU, a VM ~19% CPU, Webex, and WindowServer all running concurrently
(`loadavg` 7.6–12.2 on a 10-core machine). The run completed in full (`budget_truncated=False`,
543.9s elapsed of the 900s budget, 3 reps, back-to-back confirm pass):

| Metric | Baseline (llama.cpp defaults, `threads=8`) | Tuned (`threads=6, fa=off, kv=f16, b=4096/2048`) | Speedup |
|---|---|---|---|
| Generation t/s (median ± stddev) | 9.05 ± 1.79 | 22.11 ± 1.04 | **+144.2%** |
| Prefill t/s (median ± stddev) | 137.8 ± 56.6 | 168.0 ± 2.2 | **+21.9%** |

**Why threads=6 beat the "obvious" threads=8 default here:** requesting all 8 P-cores gives
`llama.cpp`'s per-layer thread barrier zero scheduling slack — every layer's compute has to wait
for every thread to be re-scheduled, and under this machine's ambient load (Docker/VM/Webex
competing for the same P-cores) that barrier stalls badly, which is exactly what the baseline's
wild prefill variance (±56.6 t/s) and collapsed generation throughput show. Leaving two P-cores
free (`threads=6`) gives the OS scheduler room to service the other processes without blocking
llama.cpp's own barrier, and the tuner picked it up correctly from the measurements — this is the
staged sweep adapting to the machine *as it actually was*, not a clean-room number. Full evidence
(per-trial samples, methodology, chip probe) is in
[`docs/results/m1-max-loaded-20260720/`](./docs/results/m1-max-loaded-20260720/), clearly labeled
**"measured under ambient load; adaptive result, not an idle-machine reference."**

### Idle-machine reference (reproduce with one command)

The clean, otherwise-idle-machine reference number that SC2's "≥10% speedup" bar is measured
against is **not yet captured** — the run above proves the pipeline and the tuning logic work
end-to-end on real hardware, but an honest idle-machine number requires re-running on a quiet
machine rather than reusing (or worse, hand-adjusting) the loaded-machine figures above. Once
captured, the reference table lands here, generated by:

```bash
make benchmark   # quiet machine, default reference model + budget/reps
```

No numbers are fabricated in the meantime — see [`ASSUMPTIONS.md`](./ASSUMPTIONS.md) #6 and #10
for the project's policy on this.
<!-- /RESULTS:M1MAX -->

<!-- RESULTS:M5 -->
### Apple M5 (SME2)

> **To be measured on a second machine (the user's Apple M5) via `make benchmark`.** Expected to
> show `sme2=true` in the probe output and SME-tier KleidiAI kernel activation (as opposed to
> M1 Max's DOTPROD-tier), demonstrating the cross-generation ISA story. If M5 access slips past
> the submission deadline, this section states that plainly rather than fabricating numbers
> (see [`ASSUMPTIONS.md`](./ASSUMPTIONS.md) #6).

| Metric | Baseline | Tuned | Speedup |
|---|---|---|---|
| Generation t/s | _TBD_ | _TBD_ | _TBD_ |
| Prefill t/s | _TBD_ | _TBD_ | _TBD_ |
<!-- /RESULTS:M5 -->

---

## Setup instructions

### Prerequisites

- macOS arm64 (Apple Silicon) or Linux arm64 — CPU-only by design, no GPU/Metal
- [`uv`](https://docs.astral.sh/uv/)
- `cmake` (macOS: `brew install cmake`)
- Python 3.11+ (managed by `uv`)

### Clean-clone quickstart

```bash
git clone <this-repo-url> neonpilot
cd neonpilot

# 1. Install neonpilot + dev dependencies from the committed lockfile
uv sync --locked --extra dev

# 2. Fetch + build the pinned llama.cpp (tag b10069, CPU-only, llama-bench target only)
bash scripts/fetch_llama.sh

# 3. Download a model
mkdir -p ~/.neonpilot/models
# Tiny model for a fast end-to-end check (101 MB):
curl -L -o ~/.neonpilot/models/SmolLM2-135M-Instruct-Q4_K_M.gguf \
  "https://huggingface.co/unsloth/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q4_K_M.gguf"
# Reference model for the real ≥15-min / ≥10% speedup measurement (~2.1 GB):
curl -L -o ~/.neonpilot/models/qwen2.5-3b-instruct-q4_k_m.gguf \
  "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"

# 4. Run the four commands
uv run neonpilot probe
uv run neonpilot optimize ~/.neonpilot/models/SmolLM2-135M-Instruct-Q4_K_M.gguf --budget 180
uv run neonpilot report
uv run neonpilot apply --run-dir ~/.neonpilot/runs/latest
```

Or, once a model is in place, run the whole pipeline in one shot (SC1):

```bash
make benchmark
```

`make benchmark` builds the pinned `llama.cpp` if needed, then runs the full
`probe → optimize → report → apply` pipeline against the reference model at
`~/.neonpilot/models/qwen2.5-3b-instruct-q4_k_m.gguf` (900s budget, 3 reps — the full-model
defaults from [How it works](#how-it-works)), writing the report and a preset. If that model
file is missing, it fails fast with the exact `curl` command to fetch it rather than a
confusing downstream error. Point it at any other GGUF with `MODEL=`:

```bash
MODEL=~/.neonpilot/models/SmolLM2-135M-Instruct-Q4_K_M.gguf make benchmark   # fast smoke test
```

### Development commands

```bash
make lint    # ruff check + ruff format --check
make format  # ruff format + ruff check --fix
make test    # pytest --cov=neonpilot --cov-report=term-missing (80% floor enforced)
```

Gated integration test (spawns the real pinned `llama-bench` binary against the real tiny model —
not just mocks):

```bash
NEONPILOT_INTEGRATION=1 uv run pytest -m integration
```

---

## Methodology & honesty

- **Baseline definition.** The baseline is `llama-bench -m <model> -p 512 -n 128 -r 3` with **no**
  `-t/-ctk/-ctv/-fa/-b/-ub` overrides at all — i.e. exactly what a developer gets running
  `llama.cpp` out of the box, letting it resolve its own defaults (KV `f16`, `-fa auto` →
  `flash_attn=-1`, `n_threads=8` on M1 Max, `-b 2048`/`-ub 512`). This is not a strawman config;
  it is `llama.cpp`'s real shipped behavior, and the resolved values are recorded from the JSON
  output rather than assumed.
- **Fair comparison.** Baseline and the final winner are re-measured **back-to-back** in the same
  thermal window (the confirm pass) to cancel out cold-start/warm-cache bias, before the headline
  speedup number is computed.
- **Noise handling.** Every config is measured with `-r reps` (≥3 recommended) in a single
  `llama-bench` invocation, using `llama-bench`'s own `avg_ts`/`stddev_ts` — never re-pooled or
  re-derived. A real 180-second run on the noisy dev laptop surfaced 3× intra-config swings from
  thermal/contention noise (see [`docs/dev/build-notes.md`](./docs/dev/build-notes.md) item 15);
  investigating that led directly to the credibility guard below.
- **What the caveat means.** `report/markdown.py`, `report/html.py`, and the `optimize` console
  output all apply the same `bench.stats.dominates()` statistical-dominance test used for
  in-sweep early stopping (best beats candidate by more than 1.0× combined stddev) to the final
  baseline-vs-winner comparison. If the tuned result does **not** statistically dominate the
  baseline, every surface prints an explicit "statistical caution" warning rather than presenting
  a headline percentage that could be noise. `--reps` below 3 triggers a separate, additional
  warning.
- **CPU-only / Metal off, by design.** This project's entire premise is Arm CPU inference
  optimization — the pinned build is configured with `-DGGML_METAL=OFF -DGGML_BLAS=OFF
  -DGGML_CPU_KLEIDIAI=ON`, so every measurement reflects Arm CPU kernel paths (KleidiAI, NEON,
  CPU_REPACK) only, with no GPU acceleration to muddy the comparison.

---

## Differentiation

Two other "armtune"-style entrants in this space do generic Arm64/Graviton auto-tuning. neonpilot
differentiates on four axes, treated as binding requirements rather than polish
(see [`ASSUMPTIONS.md`](./ASSUMPTIONS.md) #12):

1. **Verified ISA-probe depth, not a feature checklist.** Most auto-tuners report "NEON: yes" and
   stop. neonpilot's `probe/fastpath.py` maps the *exact* KleidiAI kernel tier that activates
   (NEON → DOTPROD → I8MM → SME2, highest-tier-wins, lower tiers reported present-but-superseded)
   and states the fast-path explanation in one verified sentence per feature — grounded in a real
   verbose `llama-bench -v` capture, not documentation guesswork.
2. **Cross-generation Apple Silicon story (M1 Max → M5).** The repo ships (or, pending the M5
   milestone, will ship) real measured presets for both a DOTPROD-only chip (M1 Max) and an
   SME2-capable chip (M5), letting the report show *why* the same model runs differently across
   Apple Silicon generations — not just two disconnected numbers.
3. **Reusable preset registry, not a one-off log file.** Every tuning run can be packaged into a
   versioned, schema-validated `presets/<chip-id>/<model-class>.json` with full provenance (chip
   snapshot, pinned commit, measured t/s), re-emitting an exact `llama-bench` invocation for
   anyone with the same chip — turning a personal tuning session into a shareable artifact.
4. **Self-contained, statistically honest reporting.** The HTML report is a single file with
   inline SVG/CSS and zero external fetches (opens offline, no CDN), and it — along with the CLI
   itself — refuses to present a headline speedup number without flagging when the underlying
   samples don't statistically support it.

---

## Track & license

Entered in the **Arm AI Optimization Challenge 2026**, **Mobile AI** track.

Licensed under the [Apache License 2.0](./LICENSE).
