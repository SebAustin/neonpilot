# neonpilot — Requirements

**Entry:** Arm AI Optimization Challenge 2026 (Devpost), Mobile AI track. Deadline **2026-08-14**.
License: Apache-2.0. Public GitHub repo mandatory.

## Restatement / Job-to-be-done

Developers deploying LLMs on Arm CPUs (Apple Silicon laptops today, Graviton/mobile Arm
tomorrow) don't know which llama.cpp runtime knobs (threads, KV-cache quant, flash attention,
batch size) are optimal for their specific chip, and manual sweeps are slow and unscientific.
neonpilot is a CLI that (1) explains *why* a given Arm chip is fast or slow for LLM inference
(ISA feature probe), (2) empirically finds a near-optimal runtime config in under 15 minutes
via a staged (not exhaustive) benchmark sweep, and (3) packages the result as a shareable,
versioned preset plus a polished report — turning a one-off personal tuning run into a
reusable community artifact.

Primary user: a developer/researcher with an Arm CPU (initially Apple Silicon) who has a
GGUF model and wants a faster, justified inference config without hand-tuning or reading
llama.cpp source.

## Functional Requirements

### FR1 — `neonpilot probe`
- Detect: chip name/model, core topology (P-core count, E-core count, total), RAM (GB).
- Detect ISA features relevant to LLM inference: NEON, dotprod, i8mm, SVE, SVE2, SME, SME2.
  - macOS: via `sysctl -a` (`hw.optional.*`, `hw.perflevel*`).
  - Linux: via `/proc/cpuinfo` + `getauxval(AT_HWCAP)`/`AT_HWCAP2`.
- Map detected features → which llama.cpp Arm fast paths activate (KleidiAI repack GEMM
  kernels, i8mm INT8 dot-product kernels, SME2 kernels) and which do not, with a one-line
  "why" for each (e.g., "SME2 absent → falls back to NEON dot-product kernel").
- Output: human-readable Rich table by default; `--json` for machine-readable output.
- Must run in < 2 seconds with no model loaded.

### FR2 — `neonpilot optimize <model.gguf>`
- Run a **staged sweep**, not full grid search, over:
  - thread count/placement (P-cores-only vs P+E, at minimum 2 candidate configs)
  - KV-cache type: f16, q8_0, q4_0
  - flash attention: on/off
  - batch/ubatch size: at least 2 candidate pairs
- Each candidate benchmarked via `llama-bench` (or equivalent harness) measuring:
  - prefill tokens/sec (TTFT proxy)
  - generation tokens/sec
- ≥ 3 repetitions per candidate; report median and standard deviation.
- Thermal cooldown guard between candidates (configurable delay; skip/warn if core temp
  telemetry unavailable, e.g. non-Apple-Silicon).
- Early stopping: abandon a sweep branch once it's statistically dominated by a better
  candidate already measured.
- Total wall-clock for a full run: **< 15 minutes** on the M1 Max reference model
  (default test model class, see Constraints).
- Emits a machine-readable result set (JSON) consumed by `report` and `apply`.

### FR3 — `neonpilot report`
- Generate both a Markdown report and a **self-contained single-file HTML** report (inline
  CSS/JS/SVG or data-URI charts — no external asset fetches, opens offline).
- Contents: baseline (llama.cpp defaults) vs tuned config comparison chart (bar or similar)
  for prefill and generation t/s, chip ISA feature table (from `probe`), sweep methodology
  summary (repetitions, cooldown, early-stopping notes).
- Must render correctly opened directly from the filesystem in a modern browser (no local
  server required).

### FR4 — `neonpilot apply` + preset registry
- `apply` writes/loads a `presets/<chip-id>/<model-class>.json` file containing the winning
  runtime flags plus provenance (chip probe snapshot, llama.cpp commit, date, measured t/s).
- Preset schema documented and versioned (`schema_version` field) so third parties can
  contribute presets for other chips without code changes.
- Repo ships **in-tree measured presets** for at minimum: Apple M1 Max and Apple M5, generated
  from real hardware runs (not synthesized), demonstrating the NEON-only vs SME2
  cross-generation story.
- `apply` can re-emit the exact `llama-bench` invocation for a stored preset so a
  user can reproduce or integrate it without re-running the sweep. (Serving flags for
  `llama-server` are documented in the preset JSON as plain text — no extra binary dependency.)

### FR5 — Packaging / CLI ergonomics
- Installable via `pip install neonpilot` (or `pip install -e .` from source) on Python 3.11+.
- CLI built with Typer; output rendering with Rich.
- Single `make benchmark` (or documented equivalent) target reproduces the full probe →
  optimize → report → apply pipeline end-to-end on a clean clone.
- `--help` on every subcommand; no undocumented flags required for basic use.

## Non-Goals (v1 — explicitly out of scope)

- No custom/hand-written compute kernels (we consume llama.cpp's Arm kernels, we don't write
  new ones).
- No training or fine-tuning of models.
- No Android target (probe/optimize logic may be portable in principle; not built or tested
  for Android in v1).
- No GPU or Metal backend — CPU-only by design; this is the point of the project.
- No server/API deployment mode (no long-running inference server, no REST endpoint).
- No support for non-GGUF model formats.
- No full/exhaustive grid search over the runtime parameter space — staged sweep with early
  stopping only.
- Linux and AWS Graviton: **"designed to work, untested"** in v1. CI does not gate on Linux
  benchmark correctness; only macOS-arm64 CI is authoritative. A Graviton run is optional
  stretch scope, not a launch requirement.

## Constraints

| Category | Constraint | Status |
|---|---|---|
| Language/runtime | Python 3.11+, Typer, Rich | Fixed |
| Inference engine | llama.cpp, **pinned to one specific commit SHA** recorded in repo | Fixed |
| Backend | CPU-only; Metal/GPU explicitly disabled at build time | Fixed |
| Primary hardware | Apple M1 Max, 64 GB RAM, macOS 26.5 | Fixed |
| Secondary hardware | User's Apple M5 machine, run via `make benchmark` | Assumption — see ASSUMPTIONS.md |
| Stretch hardware | AWS Graviton (arm64) | Optional, out of critical path |
| Test model | GGUF < 300 MB (e.g. SmolLM-135M or Qwen2.5-0.5B) for CI/integration tests | Assumption — see ASSUMPTIONS.md |
| CI | GitHub Actions, `macos-arm64` (or `macos-14`/`macos-latest` Apple Silicon) runner, must be green | Fixed |
| Lint/format | `ruff` clean (lint + format) | Fixed |
| Tests | `pytest` green; unit tests for probe parsing logic and preset schema; integration test running a real tiny-model sweep | Fixed |
| License | Apache-2.0 | Fixed |
| Repo visibility | Public on GitHub | Fixed |
| Sweep time budget | Full `optimize` run < 15 min on M1 Max reference model | Fixed |
| Report portability | HTML report self-contained (no CDN/external fetch) | Fixed |

## Measurable Success Criteria

A verifier must be able to check each of these without subjective judgment:

1. **Reproducibility**: `git clone` → documented setup steps in README → `make benchmark`
   (or equivalent) completes without manual intervention on a clean macOS-arm64 machine with
   Xcode CLT installed.
2. **Speedup proof**: on Apple M1 Max, the tuned preset's generation tokens/sec is **≥ 10%
   higher** than llama.cpp's default runtime flags on the same model and same prompt/decode
   length, measured as median of ≥ 3 runs each, reported with stddev in the HTML report.
   (10% is the minimum bar; actual results are expected to exceed this — record the real
   number, don't just clear the bar.)
3. **Cross-generation story present**: repo contains committed, real (not fabricated)
   measured presets for both M1 Max and M5, and the report/README explicitly states the
   ISA-feature-driven difference between them (e.g., SME2 kernel activation on M5).
4. **CI green**: GitHub Actions workflow on a macos-arm64 runner passes on the default branch
   at time of submission — `ruff check .`, `ruff format --check .`, `pytest` all exit 0.
5. **Test coverage floor**: `pytest --cov` reports ≥ 80% line coverage on the `neonpilot`
   package (excluding vendored/pinned llama.cpp code).
6. **Probe correctness**: `neonpilot probe --json` on the M1 Max reference machine reports
   NEON=true, dotprod=true, i8mm=false, sve=false, sme=false, sme2=false (verified against the
   real `sysctl` capture — `hw.optional.arm.FEAT_I8MM=0` on M1 Max; see
   `docs/dev/day1-spikes.md` S1) and on the M5 machine reports sme2=true.
7. **Time budget**: `neonpilot optimize` on the pinned tiny CI model completes in under the
   documented time budget for CI (separately budgeted, shorter than the 15-min full-model
   target) — CI must not time out.
8. **Report artifact**: `neonpilot report` produces an `.html` file that opens correctly via
   `file://` in an unmodified installation of Safari, Chrome, and Firefox with zero console
   network errors (no external asset requests).
9. **Install path**: `pip install -e .` followed by `neonpilot --help` and each subcommand's
   `--help` exits 0 with no traceback, on a fresh virtualenv.
10. **Differentiation artifact present**: README contains an explicit, named comparison
    section against the "generic auto-tune" category of entries (without naming competitors
    by repo), articulating the ISA-probe / cross-generation / preset-registry / report-quality
    differentiators — verifiable by reading the README table of contents / section headers.

## Open Risks and Unknowns

- **M5 access timing**: M5 hardware run depends on user availability outside the primary dev
  machine; if it slips past the deadline, cross-generation story becomes "M1 Max measured,
  M5 documented-but-unverified" — degrades success criterion 3.
- **Thermal noise on laptop chassis**: M1 Max under sustained sweep load may thermal-throttle
  despite cooldown guards, inflating variance and potentially threatening the 10% speedup bar
  on later candidates in a sweep. Mitigation: cooldown delay + discard high-variance runs, but
  this is not fully solved.
- **llama.cpp upstream drift**: pinning to a commit avoids drift but means security/perf
  fixes upstream are not picked up automatically; if the pinned commit has a known Arm-kernel
  regression, results could look worse than current upstream.
- **KleidiAI availability**: KleidiAI kernel integration in llama.cpp is version/build-flag
  dependent; if the pinned commit's CMake build doesn't actually wire in KleidiAI on this
  Apple Silicon target, part of the "fast-path explanation" in `probe` becomes aspirational
  rather than verified. Needs a Day-1 spike to confirm before relying on it in messaging.
  # NOTE — resolved during Day-1 spike, see ASSUMPTIONS.md item on KleidiAI verification.
- **`llama-bench` variance definition**: no industry-standard variance threshold for "stable"
  benchmark; the ≥3-rep median/stddev approach is a reasonable default but not something a
  judge can independently audit without re-running.
- **Competitive landscape drift**: other "armtune"-named entrants are early/0-stars today;
  they could ship comparable differentiators before the deadline. Mitigation is executing our
  differentiators well and documenting them clearly, not blocking on competitor monitoring.
- **Graviton stretch scope**: if pursued, AWS costs and access (see ASSUMPTIONS.md
  credential-scope preflight) are unvalidated as of this writing.
