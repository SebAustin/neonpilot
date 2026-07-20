# neonpilot — System Design & Implementation Plan

> Source of truth: [`REQUIREMENTS.md`](./REQUIREMENTS.md) and [`ASSUMPTIONS.md`](./ASSUMPTIONS.md).
> Verified Day-1 facts: [`docs/dev/day1-spikes.md`](./docs/dev/day1-spikes.md).
> This plan is the build contract. The **builder** and **test-engineer** code against the
> dataclasses/JSON schemas in §1 and the interfaces in §1.2. If a requirement and this plan
> disagree, the requirement wins and this plan is patched (see Revision log).

neonpilot is a Python 3.11+ CLI that (1) **probes** an Arm CPU and explains which llama.cpp
Arm fast paths activate, (2) **optimizes** llama.cpp runtime flags via a staged, thermally
guarded benchmark sweep in under 15 minutes, (3) emits a self-contained **report**, and (4)
packages the winner as a versioned, shareable **preset**. CPU-only by design; Apple Silicon
is the authoritative target, Linux/Graviton is "designed to work, untested".

---

## 0. Live environment facts (verified 2026-07-20)

These drive design decisions below. `[web]` = verified against upstream docs; `[spike]` = verified
on the M1 Max reference machine and recorded in `docs/dev/day1-spikes.md`. All formerly
`[probe-day1]` items are now resolved.

| Fact | Value | Source | Impact on design |
|---|---|---|---|
| llama-bench source path | `tools/llama-bench` (moved from `examples/llama-bench`) | [web] llama.cpp README | Build/fetch script targets `build/bin/llama-bench`; do not hardcode `examples/`. |
| `llama-bench -o json` fields | `build_commit, cpu_info, n_batch, n_ubatch, n_threads, type_k, type_v, flash_attn, n_prompt, n_gen, avg_ns, stddev_ns, avg_ts, stddev_ts, samples_ns[], samples_ts[]`; one array entry per (test × config) | [spike] S4 + [web] | `BenchSample` (§1.3) mirrors `avg_ts`/`stddev_ts`/`samples_ts`. Parser reads them directly — no in-config re-computation. |
| `-fa` flag | `on`/`off`/`auto`; **default `auto`** — JSON shows `flash_attn = -1` for auto | [spike] S4 + [web] | Baseline (§9) pins `-fa` by *omission* (llama.cpp resolves it); we record the resolved value. |
| KV-cache flags | `-ctk`/`-ctv`, default `f16` (`type_k`/`type_v` in JSON) | [spike] S4 + [web] | Stage B sweeps `f16, q8_0, q4_0`. |
| Batch flags | `-b` (default 2048), `-ub` (default 512) | [web] | Stage C sweeps `-ub`/`-b` pairs. |
| Threads flag | `-t`; **M1 Max default `n_threads = 8`** (= P-core count) | [spike] S4 | Stage A candidates derived from topology; default 8 seeds baseline. |
| Build flags | `-DGGML_METAL=OFF -DGGML_BLAS=OFF -DGGML_CPU_KLEIDIAI=ON`, target `llama-bench` | [spike] S2 | Fetch/build script (§3.2). `llama-cli` target **does not exist** with examples off and is **not needed** — tuner uses `llama-bench` only. |
| `cmake` on dev machine | installed via Homebrew (was absent) | [spike] S2 | Setup script + README still `brew install cmake`; CI installs it explicitly. |
| **M1 Max ISA truth** | **NEON=T, dotprod=T, FP16=T, i8mm=F, bf16=F, sme=F, sme2=F** | [spike] S1 (`hw.optional.arm.FEAT_I8MM=0`) | **M1 Max has dotprod but NOT i8mm.** Golden fixture `tests/fixtures/sysctl_apple_m1_max.txt`; probe copy must not claim i8mm. |
| Topology (M1 Max) | `perflevel0.physicalcpu=8` (P), `perflevel1.physicalcpu=2` (E), `physicalcpu=10`, ~64 GiB | [spike] S1 | `ChipReport.p_cores=8, e_cores=2, total_cores=10`. |
| **KleidiAI on M1 Max** | **VERIFIED engaged**: `primary q4/q8 kernel feature DOTPROD`, `SME disabled`; `CPU_KLEIDIAI` buffer + `CPU_REPACK q6_K_8x4` for the rest | [spike] S3 | Probe copy: "i8mm ABSENT → DOTPROD-tier KleidiAI kernels engaged; SME disabled; other quants via CPU_REPACK." No i8mm/SME overclaim. M5 expected to select SME-tier (capture during M5 run). |
| Pinned llama.cpp | tag **`b10069`** = SHA **`178a6c44937154dc4c4eff0d166f4a044c4fceba`** | [spike] S2 | Recorded in `scripts/fetch_llama.sh` + `neonpilot/_llama_pin.py`; asserted by `tests/test_pin.py`. |
| `powermetrics` thermal telemetry | likely needs sudo | ASSUMPTIONS #8 | Thermal guard has a no-sudo adaptive/fixed fallback (§4.4); never blocks the pipeline. |

**Day-1 probe checklist — COMPLETE** (see `docs/dev/day1-spikes.md`): sysctl fixture captured (S1),
cmake installed + pinned llama.cpp built (S2), KleidiAI kernel path confirmed (S3), real
`llama-bench -o json` shape captured (S4), both models downloaded (S5). Remaining hardware-gated
item: M5 SME2 kernel-path capture, during the M5 benchmark run.

---

## 1. Architecture

### 1.1 Component map

```mermaid
flowchart TD
    CLI["cli.py — Typer app<br/>(probe / optimize / report / apply)"]

    subgraph probe["probe/ — read-only host introspection"]
        PA["adapters: macos_sysctl.py · linux_cpuinfo.py"]
        PM["fastpath.py — ISA → kernel mapping"]
        PA --> PM
    end

    subgraph bench["bench/ — measurement (subprocess boundary)"]
        BR["runner.py — llama-bench subprocess"]
        BP["parser.py — JSON → BenchSample"]
        BT["thermal.py — cooldown guard"]
        BS["stats.py — median/stddev/dominance"]
        BR --> BP
    end

    subgraph search["search/ — experiment design"]
        SP["planner.py — staged candidate sets"]
        SE["engine.py — orchestrate trials, early stop"]
        SP --> SE
    end

    subgraph report["report/"]
        RM["markdown.py"]
        RH["html.py — inline SVG/CSS, no JS deps"]
    end

    subgraph preset["preset/"]
        PS["schema.py — Preset dataclass + validate"]
        PIO["io.py — load/save/apply/invocation"]
    end

    llama[("build/bin/llama-bench<br/>pinned llama.cpp (untrusted output)")]

    CLI --> probe & search & report & preset
    SE --> BR & BT & BS
    SE --> SP
    BR -->|subprocess| llama
    probe --> SE
    SE -->|TrialResult[]| report & preset

    classDef ext fill:#2a2a2a,stroke:#e0457b,color:#fff;
    class llama ext;
```

### 1.2 Modules — single responsibility + interface

| Module | Responsibility | Key public interface | Depends on |
|---|---|---|---|
| `probe/macos_sysctl.py` | Parse `sysctl -a` → topology + ISA | `read_chip_report(sysctl_text: str \| None) -> ChipReport` (text injectable for tests) | stdlib only |
| `probe/linux_cpuinfo.py` | Parse `/proc/cpuinfo` + HWCAP → same | `read_chip_report(cpuinfo_text, hwcap: int, hwcap2: int) -> ChipReport` | stdlib, `ctypes` for `getauxval` |
| `probe/fastpath.py` | Map ISA flags → llama.cpp kernel activation + one-line "why" | `explain(isa: dict[str,bool]) -> list[FastPathNote]` | none |
| `probe/__init__.py` | Platform dispatch | `probe_host() -> ChipReport` | adapters |
| `bench/runner.py` | Build argv, spawn `llama-bench`, capture stdout, timeout, error surface | `run_bench(binary, model, cfg: RuntimeConfig, reps: int, prompt_n, gen_n, timeout_s) -> list[BenchSample]` | `parser`, `subprocess` |
| `bench/parser.py` | `llama-bench` JSON → `BenchSample[]`; validate shape | `parse(stdout: str) -> list[BenchSample]` | stdlib `json` |
| `bench/thermal.py` | Cooldown between trials; read `powermetrics` if available, else fixed delay | `cooldown(policy: CooldownPolicy) -> ThermalSnapshot \| None` | `subprocess` (best-effort) |
| `bench/stats.py` | Median, stddev, statistical-dominance test | `median(xs)`, `stddev(xs)`, `dominates(a: TrialResult, b: TrialResult) -> bool` | stdlib `statistics` |
| `search/planner.py` | Build staged candidate sets from `ChipReport` | `plan(chip: ChipReport, budget: SweepBudget) -> SearchPlan` | none |
| `search/engine.py` | Run stages A→B→C, thread best-so-far, early-stop, enforce budget | `run(plan: SearchPlan, ctx: SweepContext) -> SweepResult` | `bench/*`, `planner` |
| `report/markdown.py` | `SweepResult`+`ChipReport` → `.md` | `render_markdown(result, chip) -> str` | none |
| `report/html.py` | Same → single-file `.html`, inline SVG bars, inline CSS, zero external fetch | `render_html(result, chip) -> str` | none (hand-rolled SVG) |
| `preset/schema.py` | `Preset` dataclass, `schema_version`, validation | `validate(d: dict) -> Preset`, `to_dict(p) -> dict` | stdlib |
| `preset/io.py` | Load/save presets, `apply` (re-emit **llama-bench** invocation), registry paths | `save(p, root)`, `load(chip_id, model_class, root)`, `invocation(p) -> str` (llama-bench command line) | `schema` |
| `cli.py` | Typer commands, Rich rendering, arg validation, exit codes | `app` (Typer) | all above |
| `artifacts.py` | Run-dir creation, JSON (de)serialization, `latest` symlink | `new_run_dir()`, `dump(obj, path)`, `load(path)` | stdlib |

**Design rules enforced:** adapters take **injected text**, never call `subprocess` themselves
(makes probe parsers pure and unit-testable from fixtures). `bench/runner.py` is the *only* module
that spawns the untrusted `llama-bench` binary. `report/*` and `preset/*` are pure functions of
their inputs (golden-file testable). No module imports `cli.py`.

### 1.3 Core data contracts (builder + test-engineer code to these exactly)

All dataclasses live in `neonpilot/models.py`, are `@dataclass(frozen=True)` (immutability per repo
style), and serialize via `dataclasses.asdict`. `schema_version` is a module constant.

```python
# neonpilot/models.py
SCHEMA_VERSION = "1.0.0"
# Pinned llama.cpp: tag b10069 = SHA 178a6c44937154dc4c4eff0d166f4a044c4fceba.
# Canonical value lives in neonpilot/_llama_pin.py (LLAMA_CPP_COMMIT); asserted by test_pin.py.

@dataclass(frozen=True)
class FastPathNote:
    feature: str        # "i8mm" | "dotprod" | "sme2" ...
    kernel: str         # "KleidiAI DOTPROD q4/q8 GEMM" | "CPU_REPACK q6_K_8x4" | "SME2 kernel (M5)"
    active: bool        # does THIS chip activate it?
    why: str            # M1 Max i8mm note: "i8mm ABSENT -> DOTPROD-tier KleidiAI kernels engaged"

@dataclass(frozen=True)
class ChipReport:
    schema_version: str          # SCHEMA_VERSION
    probed_at: str               # ISO-8601 UTC
    platform: str                # "darwin" | "linux"
    chip_name: str               # "Apple M1 Max"
    chip_id: str                 # slug: "apple-m1-max"
    cpu_brand: str               # raw brand string
    p_cores: int                 # M1 Max: 8
    e_cores: int                 # M1 Max: 2
    total_cores: int             # M1 Max: 10
    ram_gb: float
    isa: dict[str, bool]         # keys: neon,dotprod,i8mm,sve,sve2,sme,sme2,bf16,fp16
    fast_paths: list[FastPathNote]
    raw: dict[str, str]          # captured source keys, for provenance + fixtures

@dataclass(frozen=True)
class RuntimeConfig:
    threads: int
    cache_type_k: str            # "f16" | "q8_0" | "q4_0" ...
    cache_type_v: str
    flash_attn: str              # "on" | "off" | "auto"
    batch: int                   # -b  (logical, default 2048)
    ubatch: int                  # -ub (physical, default 512)

@dataclass(frozen=True)
class BenchSample:               # one llama-bench JSON row
    test_type: str               # "pp" (prefill) | "tg" (generation)
    n_prompt: int
    n_gen: int
    avg_ts: float                # tokens/sec  (from llama-bench avg_ts)
    stddev_ts: float             # from llama-bench stddev_ts
    samples_ts: list[float]      # per-rep tokens/sec

@dataclass(frozen=True)
class ThermalSnapshot:
    source: str                  # "powermetrics" | "elapsed-fallback" | "idle-skip"
    cpu_temp_c: float | None
    throttled: bool | None
    cooldown_s: float            # actual seconds waited for this gap

@dataclass(frozen=True)
class TrialResult:
    trial_id: str                # "A2", "B1-fa_on-q8_0"
    stage: str                   # "A" | "B" | "C" | "baseline" | "confirm"
    config: RuntimeConfig
    prefill: BenchSample | None
    generation: BenchSample | None
    reps: int
    started_at: str
    ended_at: str
    thermal: ThermalSnapshot | None
    status: str                  # "ok" | "pruned" | "error"
    error: str | None

@dataclass(frozen=True)
class CooldownPolicy:
    target_temp_c: float | None  # cool until below this (None => no sensor available)
    max_cooldown_s: float        # hard cap on any single cooldown gap
    fixed_delay_s: float         # used when no sensor AND idle check unavailable
    idle_skip: bool              # skip cooldown when a thermal/idle check says already cool

@dataclass(frozen=True)
class SweepBudget:
    total_seconds: int           # 900 full-model, 180 CI
    reps: int                    # >= 3 (single `-r reps` call per config, see §4.3)
    prompt_n: int                # -p tokens (prefill workload); full-model=512, CI=64
    gen_n: int                   # -n tokens (decode workload);  full-model=128, CI=32

@dataclass(frozen=True)
class SearchPlan:
    stage_a: list[RuntimeConfig] # thread candidates (topology-derived)
    stage_b: list[RuntimeConfig] # fa x kv-cache candidates
    stage_c: list[RuntimeConfig] # (batch, ubatch) candidates
    baseline: RuntimeConfig | None  # None => "no tuning flags" (llama.cpp defaults, §9)
    notes: list[str]             # human-readable rationale per stage

@dataclass(frozen=True)
class SweepContext:
    binary: str                  # path to build/bin/llama-bench
    model_path: str              # absolute path to the .gguf under test
    model_class: str             # e.g. "qwen2.5-3b-instruct-q4_k_m"
    out_dir: str                 # run-dir for artifacts/logs
    budget: SweepBudget
    cooldown: CooldownPolicy
    timeout_s: int               # per-invocation hard timeout for the runner
    llama_cpp_commit: str        # pinned SHA (recorded into SweepResult)
    # runner is dependency-injected as a callable so engine is unit-testable with a mock:
    #   run_bench(binary, model, cfg, reps, prompt_n, gen_n, timeout_s) -> list[BenchSample]

@dataclass(frozen=True)
class SweepResult:
    schema_version: str
    model_file: str
    model_class: str
    llama_cpp_commit: str
    baseline: TrialResult        # llama.cpp defaults, no tuning flags
    trials: list[TrialResult]    # every candidate incl. pruned/error
    best: TrialResult
    speedup_gen_pct: float       # (best.gen - baseline.gen)/baseline.gen*100
    speedup_prefill_pct: float
    elapsed_s: float
    budget: SweepBudget
    budget_truncated: bool       # True iff a stage/confirm pass was dropped to fit budget
    dropped_stages: list[str]    # e.g. ["C", "confirm"]; [] when nothing dropped

@dataclass(frozen=True)
class Preset:
    schema_version: str
    chip_id: str
    chip: ChipReport             # full probe snapshot (provenance)
    model_class: str             # "qwen2.5-3b-instruct-q4_k_m"
    model_file: str              # filename only, not absolute path
    config: RuntimeConfig        # winning flags
    llama_cpp_commit: str        # pinned SHA
    generated_at: str
    baseline_gen_ts: float
    baseline_prefill_ts: float
    tuned_gen_ts: float
    tuned_prefill_ts: float
    tuned_gen_stddev: float
    speedup_gen_pct: float
    speedup_prefill_pct: float
    server_flags: str            # equivalent llama-server flags as plain text (no binary dep)
    neonpilot_version: str
    os_version: str
    reps: int
    cooldown_s: float
```

`Preset` JSON on disk = `dataclasses.asdict(preset)` with 2-space indent, sorted keys, trailing
newline (stable diffs for in-tree presets).

### 1.4 Trust boundaries

1. **Host → probe (read-only):** we only *read* `sysctl`/`/proc/cpuinfo`. No writes, no sudo for
   probe. Input treated as untrusted text: parsers validate and default-fill missing keys rather
   than `KeyError`.
2. **neonpilot → llama-bench subprocess (untrusted output):** the pinned binary is third-party
   code. `bench/runner.py` is the sole spawn point, uses **argv lists (never `shell=True`)**, sets
   a hard `timeout_s`, and treats stdout as untrusted → `parser.py` validates JSON shape before use.
   Non-zero exit / malformed JSON → `TrialResult(status="error")`, never a crash.
3. **`powermetrics` (privileged, optional):** may need sudo. Best-effort only; failure downgrades
   to elapsed-time cooldown. Never blocks the pipeline, never prompts interactively in CI.
4. **Preset files (contributed by third parties):** loaded via `schema.validate`, which checks
   `schema_version` and field types. A malformed community preset is rejected with a clear error,
   not executed blindly. `apply` re-emits a command string for the user to run; neonpilot does not
   auto-exec arbitrary flags from an untrusted preset without a `--print` review path.
5. **No network at runtime** except explicit model/llama.cpp fetch during setup. The tool phones
   home to nothing (ASSUMPTIONS #11). HTML report fetches zero external assets.

---

## 2. Data flow

```
neonpilot optimize model.gguf
        │
        ▼
  probe_host() ─────────────► ChipReport ──┐  (also `neonpilot probe` standalone)
        │                                   │
        ▼                                   ▼
  planner.plan(chip, budget) ─────────► SearchPlan (staged candidate list)
        │
        ▼
  engine.run(plan, ctx) ──► measure baseline first, then per candidate:
        │                 runner.run_bench(reps) → parser → BenchSample[]
        │                 thermal.cooldown() between candidates
        │                 stats.dominates() → prune REMAINING candidates (early stop)
        │                 final confirm pass: baseline vs best back-to-back
        ▼
   SweepResult (baseline + all trials + best + speedups + truncation flags)
        │
        ├──► artifacts.dump ──► ~/.neonpilot/runs/<ts>/{chip.json, plan.json,
        │                        trials.json, result.json, run.log}
        │
        ├──► report.render_markdown / render_html ──► runs/<ts>/report.{md,html}
        │
        └──► preset.save (on `apply`) ──► presets/<chip-id>/<model-class>.json  (in-tree)
```

### 2.1 Artifact location — decision

**Run artifacts → `~/.neonpilot/runs/<ISO-timestamp>/` (user-global), with a `latest` symlink.
Curated presets → `./presets/<chip-id>/<model-class>.json` (in-tree, committed).**
(Models are cached at `~/.neonpilot/models/`, per spike S5.)

Rationale:
- **Runs are ephemeral, machine-specific, and noisy** (logs, every pruned trial). Writing them into
  the working tree by default would pollute `git status` on a clean clone and tempt accidental
  commits of large logs. User-global `~/.neonpilot/runs/` keeps them out of the repo and shared
  across clones/branches.
- **Presets are curated, small, and reviewable** — they *are* a deliverable (FR4, SC3) and belong
  in-tree with stable diffs.
- **CI reproducibility override:** `optimize`/`report` accept `--out DIR`. CI passes
  `--out ./runs` so the run dir is inside the workspace and uploadable as a GitHub Actions
  artifact. `make benchmark` uses the default user-global path. This gives both "clean tree by
  default" and "capturable in CI" without a second code path.
- Rejected: default `./runs/` in CWD — pollutes the tree and every example command leaves
  untracked files, hurting the SC1 "clean clone" story.

---

## 3. llama.cpp integration

### 3.1 Pinning strategy

- Pinned to release tag **`b10069`** = SHA **`178a6c44937154dc4c4eff0d166f4a044c4fceba`** (spike
  S2), chosen because it (a) builds cleanly on Apple Silicon with `-DGGML_METAL=OFF`, (b) exposes
  the current `tools/llama-bench` with `-o json` + `-fa on/off/auto` + `-ctk/-ctv` (S4), and (c)
  wires in KleidiAI CPU kernels via `-DGGML_CPU_KLEIDIAI=ON` (S3). The tag doubles as provenance;
  the SHA is what we pin.
- SHA recorded in **exactly two places** and asserted equal by a test:
  `scripts/fetch_llama.sh` (`LLAMA_CPP_SHA=178a6c44937154dc4c4eff0d166f4a044c4fceba`) and
  `neonpilot/_llama_pin.py` (`LLAMA_CPP_COMMIT = "178a6c44937154dc4c4eff0d166f4a044c4fceba"`).
  `tests/test_pin.py` asserts they match, so provenance in presets is never stale.
- Never silently re-pin: changing the SHA requires a Revision-log + ASSUMPTIONS #4 note.

### 3.2 Fetch + build (`scripts/fetch_llama.sh`)

```
set -euo pipefail
LLAMA_CPP_SHA="178a6c44937154dc4c4eff0d166f4a044c4fceba"   # tag b10069
VENDOR="${NEONPILOT_VENDOR:-vendor/llama.cpp}"
# shallow fetch the exact commit (no full history), read-only, no auth (public)
git init "$VENDOR" && git -C "$VENDOR" fetch --depth 1 \
    https://github.com/ggml-org/llama.cpp "$LLAMA_CPP_SHA"
git -C "$VENDOR" checkout FETCH_HEAD
cmake -S "$VENDOR" -B "$VENDOR/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_METAL=OFF -DGGML_BLAS=OFF \
    -DGGML_CPU_KLEIDIAI=ON \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF \
    -DLLAMA_BUILD_TOOLS=ON
cmake --build "$VENDOR/build" --config Release --target llama-bench -j
```

- **Binary lives at** `vendor/llama.cpp/build/bin/llama-bench`. `NEONPILOT_LLAMA_BIN` env var
  overrides the discovered path (used by tests / prebuilt CI cache).
- **`llama-cli` is NOT built and NOT needed** (spike S2): the target doesn't exist with examples
  off, and the tuner drives everything through `llama-bench`. `apply` re-emits a `llama-bench`
  command line; serving flags are documented as plain text in the preset (`server_flags`), not as a
  binary dependency.
- `cmake` is installed via `brew install cmake` (README prereqs + `scripts/setup.sh`); CI installs
  it explicitly (cached).
- `vendor/` is git-ignored (we fetch, we don't vendor source into our repo → keeps repo small and
  the Apache-2.0 licensing clean; llama.cpp stays read-only upstream, ASSUMPTIONS credential table).
- Path-with-spaces discipline: the project dir contains spaces ("Arm Create- AI Optimization
  Challenge"). All shell vars quoted (`"$VENDOR"`), all Python paths via `pathlib.Path` / argv
  lists, **never** string-interpolated shell. A lint test greps scripts for unquoted `$VAR`.

### 3.3 Invocation & parsing

`runner.run_bench` builds argv (one call carries all `reps` via `-r`):

```
[binary, "-m", str(model), "-o", "json",
 "-t", str(cfg.threads),
 "-ctk", cfg.cache_type_k, "-ctv", cfg.cache_type_v,
 "-fa", cfg.flash_attn,
 "-b", str(cfg.batch), "-ub", str(cfg.ubatch),
 "-p", str(prompt_n), "-n", str(gen_n),
 "-r", str(reps)]
```

- `-o json` emits a JSON array; each element is one test row. `parser.parse` reads `avg_ts`,
  `stddev_ts`, `samples_ts`, and classifies rows: a `pp`/prompt row → `prefill`, a `tg`/gen row →
  `generation`. **We trust llama-bench's own `avg_ts`/`stddev_ts`** (it computes them over the
  `reps` samples in the single call), so `bench/stats.py` is used only for *cross-config* dominance
  and median selection, never to re-pool within-config variance. Parser validates: array non-empty,
  each row has the expected keys, numeric fields parse as float — else raise `BenchParseError` →
  `TrialResult(status="error")`.
- Baseline trial = same argv **minus all tuning flags** (`-t/-ctk/-ctv/-fa/-b/-ub` omitted), so
  llama.cpp applies its own defaults (KV `f16`, `flash_attn=-1` auto, `n_threads=8` on M1 Max, per
  S4). We record the resolved thread count and `-fa` value from the JSON so the baseline is
  reproducible (see §9).

---

## 4. Search design

### 4.1 Staged sweep (greedy hill-climb across knob groups, not full grid)

Baseline is measured **first** (needed for the 10% bar and to seed "best-so-far"). Then three
stages; each stage fixes the winner of the prior stage and varies one knob group. Planned worst
case (no pruning) = 1 baseline + 4 (A) + 6 (B) + 3 (C) + 2 (confirm) = **16 configs**, versus
O(product) ≈ 36+ for a full grid.

**Stage A — threads / placement.** Candidate set derived from `ChipReport` topology:
- General rule: `sorted(set([p, p-2, total, max(1, total-1)]))`, clamped ≥1, min 2 (FR2), cap 4.
  Concretely for M1 Max (`p_cores`=8, `total`=10): `[6, 8, 9, 10]` — P-core-minus, P-cores-only
  (= llama.cpp default 8), all-but-one, all-cores.
- Winner A* = highest generation t/s (ties broken by prefill t/s, then fewer threads).

**Stage B — flash-attention × KV-cache type.** With threads=A*:
- `flash_attn ∈ {off, on}` × `cache_type ∈ {f16, q8_0, q4_0}` (k=v). 2×3=6, the most impactful
  group for CPU decode and memory bandwidth. Winner B* by generation t/s, with a memory-tie rule
  preferring smaller KV cache when within noise (helps long-context users).

**Stage C — prefill batching.** With threads=A*, fa/kv=B*:
- `(-b, -ub) ∈ {(2048, 512)[default], (2048, 1024), (4096, 2048)}` — 3 pairs. Optimized for
  **prefill** t/s (secondary objective) while requiring generation t/s not to regress > noise.

**Confirm pass.** Re-measure baseline and the final winner **back-to-back** (2 configs) in the same
thermal window; these feed §9's speedup number.

Final winner = confirm-pass winner. Every candidate (incl. pruned) is retained in
`SweepResult.trials`.

### 4.2 Objective

```
score(trial) = gen_ts                       # PRIMARY: generation tokens/sec (from single -r call)
tiebreak_1   = prefill_ts                    # SECONDARY: prefill tokens/sec
tiebreak_2   = -kv_cache_bytes               # prefer smaller KV cache within noise band
```
A weighted single number is avoided as primary because gen and prefill are different units; instead
generation t/s is the hard primary and prefill is an explicit tiebreak. The **report** additionally
shows a weighted composite `0.7*gen_norm + 0.3*prefill_norm` for readers, clearly labeled as
presentational only.

### 4.3 Rep model + early stopping (single decision, no contradiction)

- **Rep execution — ONE model, chosen:** every config is measured in **one `llama-bench` call with
  `-r reps`** (reps=3 default). We use llama-bench's own `avg_ts`/`stddev_ts` for that config. There
  is **no rep-level early exit** — we never split reps across calls, so `stats.py` needs no pooled-
  variance aggregation. This keeps the runner deterministic and the parser trivial.
- **Early stopping is at the CANDIDATE level only.** After a config is fully measured, we compare it
  to the current best via statistical dominance:
  ```
  dominates(best, cand) := best.gen_ts - k*best.stddev  >  cand.gen_ts + k*cand.stddev   (k = 1.0)
  ```
  When the current best dominates a candidate AND the remaining candidates in that stage are
  monotonically worse along the swept axis (e.g. Stage B: once a smaller/faster KV type clearly
  wins, the remaining larger-cost KV variants are skipped), those **not-yet-run** candidates are
  marked `status="pruned"` and never benched. Pruning removes future work; it never truncates a
  measurement already in progress. Pruned trials are shown greyed-out in the report (methodology
  transparency).

### 4.4 Cooldown, budget, and the <15-min projection (hard-capped by truncation)

**Reference full-model run:** **Qwen2.5-3B-Instruct Q4_K_M (~2.1 GB, spike S5)**. Workload pinned:
`prompt_n = 512`, `gen_n = 128`, `reps = 3`. These are recorded in `SweepBudget` and the preset so
the timing below is reproducible, not hand-wavy.

**Per-config time estimate** (3B-class Q4_K_M on M1 Max, CPU-only; smaller than the earlier 7-8B
assumption → more budget headroom. To be re-calibrated by the M5-timing capture and this table
updated with measured numbers):

| Component | Est. | Basis |
|---|---|---|
| model load (mmap, once per call) | ~1.5 s | ~2.1 GB Q4_K_M, warm page cache |
| prefill ×3 reps | 3 × (512 / ~140 t/s) ≈ 11 s | pp throughput est. (3B) |
| generation ×3 reps | 3 × (128 / ~40 t/s) ≈ 10 s | tg throughput est. (3B) |
| **per config total** | **~23 s** | sum |

**Worst-case budget (no pruning) — must fit WITHOUT relying on truncation:**

| Item | Count | Unit | Subtotal |
|---|---|---|---|
| Configs (baseline + A4 + B6 + C3 + confirm2) | 16 | ~23 s | ~368 s |
| Cooldown gaps (adaptive, capped) | 15 | ≤ 20 s | ≤ 300 s |
| **Total (worst case, cap-bound cooldowns)** | | | **~668 s < 900 s** |

Headroom ≈ 230 s covers slower-than-estimated throughput or a high-variance re-measure. With
early-stopping the config count typically drops to ~10–12, and with idle-skip cooldowns the real
run lands well under budget. (The 2.1 GB model vs the earlier 4.5 GB assumption roughly halves
per-config load time, which is why the budget is now comfortable rather than tight.)

**Cooldown design — resolving the "cooldown eats the budget" tension.** A naive fixed 30 s cooldown
× 15 gaps = 450 s would consume half the budget and make truncation (dropping Stage B/C — exactly
where the gains live) likely. We avoid that:
- `CooldownPolicy` is **adaptive**: if `powermetrics` (or an idle/thermal check) reports the CPU is
  already at/below `target_temp_c`, cooldown is **skipped** (`idle_skip=True`, `source="idle-skip"`,
  `cooldown_s=0`). Otherwise cool until below target or `max_cooldown_s` (default **20 s**, not 30).
- Only when **no sensor and no idle signal** exists do we fall back to `fixed_delay_s` (default 20 s
  full-model / 3 s CI). Even at the cap the table above still fits.
- This reclaims ~150–300 s versus the old fixed-30 s scheme, so **Stage B/C are protected** and
  truncation becomes a rare safety net, not the expected path.

**Truncation as last-resort only.** `engine.run` tracks elapsed and projects remaining cost. If — and
only if — the projection would still blow the 900 s ceiling, it drops work in this order:
`adaptive extras → Stage C → confirm pass`, sets `budget_truncated=True`, and appends the dropped
label to `dropped_stages`. The confirm pass is dropped *after* Stage C because §9's headline SC2
number depends on the back-to-back confirm measurement for warm-vs-cold fairness; if confirm is
ever dropped, the report must state that the speedup figure is baseline-vs-best from sweep samples
(degraded measurement quality), not a confirmed back-to-back pair. Stage A and Stage B (the
gain-bearing knobs) are dropped last, and the report flags any truncation explicitly.

---

## 5. Tech choices with trade-offs

| Decision | Choice | Trade-off / why | Rejected alternative |
|---|---|---|---|
| Benchmark harness | **subprocess `llama-bench -o json`** | Full fidelity to the pinned binary + exact flag control; JSON is a stable machine contract; isolates untrusted native code in its own process w/ timeout. `llama-cli` not even built (S2). | `llama-cpp-python` bindings — couples us to a pip wheel's build flags (may enable Metal, may not match our pin), harder to pin SHA, in-process crash risk. |
| CLI framework | **Typer + Rich** (repo default) | Type-hint driven commands, auto `--help`, great tables for probe output. Fits FR5 exactly. | `argparse` — more boilerplate, worse help/tables; `click` raw — Typer wraps it better here. |
| HTML report | **hand-rolled inline SVG bars + inline CSS, zero JS** | Guarantees SC8 (opens via `file://` in Safari/Chrome/Firefox, no network, no console errors). Small, auditable. | Chart.js/Plotly — external/bundled JS, CDN or large inline blob, CSP/`file://` friction, overkill for 2 bar charts. |
| Probe input | **inject text into pure parsers**; adapters read `sysctl`/`/proc` | Parsers become pure fns → trivially unit-testable from fixtures (SC6, 80% cov). | Parsers call subprocess directly — untestable without the exact hardware. |
| Data modeling | **frozen dataclasses + `asdict`**, hand JSON | stdlib-only, immutable (repo style), stable diffs; no heavy dep. | Pydantic — nice validation but a runtime dep + version churn; we need only shape checks, done in `schema.validate`. |
| llama.cpp source | **fetch pinned SHA to git-ignored `vendor/`, build locally** | Reproducible, small repo, clean Apache-2.0 (we don't re-vendor upstream source). | git submodule — heavier clone UX; committing source — bloats repo + license bookkeeping. |
| Stats | **stdlib `statistics` + simple dominance rule** | No numpy/scipy dep; median/stddev/dominance are enough; llama-bench already gives per-rep samples. | numpy/scipy — dependency weight for arithmetic we can do in stdlib. |
| Thermal | **adaptive best-effort `powermetrics`, fixed-delay fallback** | Rigor when available, reclaims budget via idle-skip, never blocks UX/CI on sudo (ASSUMPTIONS #8). | Require sudo `powermetrics` — breaks smooth CLI + CI; fixed 30 s always — eats the budget. |
| Config storage | JSON (not YAML/TOML) for presets & runs | One format end-to-end, `json` in stdlib, machine-readable for `report`/`apply`. | YAML — extra dep + ambiguity; TOML — write-side stdlib support is weaker. |

---

## 6. Milestones (vertical slices; thinnest runnable path first)

Each milestone ends with a **verifiable** outcome. End-to-end path exists by M3.

### M0 — Scaffold + CI (thinnest slice)
- **Files:** `pyproject.toml` (Typer, Rich, ruff, pytest, pytest-cov), `neonpilot/__init__.py`,
  `neonpilot/cli.py` (all 4 commands as stubs printing "not implemented"), `neonpilot/models.py`
  (all dataclasses from §1.3), `.github/workflows/ci.yml` (macos-arm64: ruff check, ruff format
  --check, pytest), `Makefile`, `LICENSE` (Apache-2.0), `README.md` skeleton.
- **Done-when:** `pip install -e .` succeeds on fresh venv; `neonpilot --help` and each subcommand
  `--help` exit 0 (SC9); CI green on empty test suite; `ruff` clean.

### M1 — probe
- **Files:** `probe/macos_sysctl.py`, `probe/linux_cpuinfo.py`, `probe/fastpath.py`,
  `probe/__init__.py`; `tests/fixtures/sysctl_apple_m1_max.txt` (captured, spike S1),
  `tests/test_probe_*.py`; wire `cli.probe` (Rich table + `--json`).
- **Done-when:** `neonpilot probe --json` on M1 Max reports `neon=true, dotprod=true,
  i8mm=false, sve=false, sme=false, sme2=false` (SC6, matches S1 fixture `FEAT_I8MM=0`); runs < 2s;
  unit tests parse M1 Max fixture; `fastpath.explain` produces a "why" line per feature, including
  the "i8mm ABSENT → DOTPROD-tier KleidiAI" note (S3). (M5 fixture added in M5.)

### M2 — bench harness (parses **real** llama-bench output)
- **Files:** `bench/runner.py`, `bench/parser.py`, `bench/stats.py`, `bench/thermal.py`;
  `scripts/fetch_llama.sh`, `neonpilot/_llama_pin.py`, `tests/test_pin.py`;
  `tests/fixtures/llama_bench_pp.json`, `llama_bench_tg.json` (real output captured, spike S4);
  `tests/test_parser.py`, `tests/test_stats.py`.
- **Done-when:** pinned llama.cpp (b10069) builds via `scripts/fetch_llama.sh`; `run_bench` on the
  tiny model returns `BenchSample[]` with sane t/s; `parser.parse` matches golden fixtures;
  `stats.dominates` unit-tested; `test_pin.py` asserts SHA `178a6c44…` consistent across both files.

### M3 — search end-to-end (tiny model) — **first full pipeline**
- **Files:** `search/planner.py`, `search/engine.py`; `artifacts.py`; wire `cli.optimize`;
  `tests/test_planner.py`, `tests/test_engine.py` (mocked runner).
- **Done-when:** `neonpilot optimize tiny.gguf` runs baseline + staged sweep, writes
  `~/.neonpilot/runs/<ts>/result.json` with a `best`, `speedup_gen_pct`, and `budget_truncated`
  flag, under the 180s CI budget; planner tests assert correct candidate sets from a mocked M1 Max
  `ChipReport` (`[6,8,9,10]`); engine tests (mocked runner) assert candidate-level pruning and that
  `budget_truncated`/`dropped_stages` populate when a tiny budget forces truncation.

### M4 — report + preset + apply
- **Files:** `report/markdown.py`, `report/html.py`, `preset/schema.py`, `preset/io.py`;
  wire `cli.report`, `cli.apply`; `tests/test_report_golden.py`, `tests/test_preset.py`;
  `tests/golden/report.html`.
- **Done-when:** `neonpilot report` emits `.md` + self-contained `.html` (no external fetch —
  test asserts no `http(s)://` asset refs, only `data:`/inline); `apply` writes
  `presets/<chip-id>/<model-class>.json` validating against `schema`, and re-emits an exact
  **`llama-bench`** invocation string (plus `server_flags` plain-text for llama-server, no binary
  dependency); golden-file tests pass.

### M5 — real run on M1 Max + committed presets
- **Files:** `presets/apple-m1-max/qwen2.5-3b-instruct-q4_k_m.json` (real),
  `presets/apple-m5/...` (real, M5-access permitting), `tests/fixtures/sysctl_apple_m5.txt`,
  updated ASSUMPTIONS/Live-facts, demo `report.html` checked into `docs/`.
- **Done-when:** full `optimize` on M1 Max + Qwen2.5-3B reference model completes < 15 min and the
  committed preset shows tuned gen t/s **≥ 10%** over baseline with stddev (SC2, conditional — see
  R2/§11); M5 preset committed with `sme2=true` probe and cross-gen narrative (SC3, captures the
  SME-tier KleidiAI kernel path) — or, if M5 slips, M5 numbers explicitly labeled unverified/removed
  (ASSUMPTIONS #6), documented as a degraded SC3.

### M6 — docs + Devpost draft
- **Files:** finalized `README.md` (setup, `make benchmark`, differentiation section per SC10),
  `docs/`, Devpost draft.
- **Done-when:** `make benchmark` on a clean clone runs probe→optimize→report→apply without manual
  intervention (SC1); README has the named "vs generic auto-tune" differentiation section (SC10);
  coverage ≥ 80% (SC5); CI green (SC4).

**Critical path:** M0→M1→M2→M3 (working pipeline) → M4 (deliverable artifacts) → M5 (proof
numbers) → M6 (packaging). M5 is the only milestone gated on external hardware access.

---

## 7. Testing strategy

**Coverage floor 80% (SC5), enforced in CI via `pytest --cov=neonpilot --cov-fail-under=80`**
(excluding `vendor/`).

- **Unit (fast, no hardware, no network):**
  - Probe parsers against real captured fixtures: `sysctl_apple_m1_max.txt` (S1),
    `sysctl_apple_m5.txt` (M5), a Linux `cpuinfo` capture. Assert exact ISA dicts — M1 Max
    `i8mm=false` (SC6) — topology (`8/2/10`), RAM. Edge cases: missing keys, unknown chip → graceful
    defaults.
  - `fastpath.explain` → snapshot of `FastPathNote[]`, including the M1 Max
    "i8mm ABSENT → DOTPROD-tier KleidiAI" note.
  - `bench/parser.py` against golden real `llama-bench` JSON (pp, tg, malformed, empty-array).
  - `bench/stats.py`: median/stddev vs known values; `dominates` truth table.
  - `search/planner.py`: candidate sets for M1 Max / M5 / generic topologies.
  - `search/engine.py` with a **mocked runner** (deterministic fake `BenchSample`s): verifies stage
    ordering, candidate-level pruning, budget truncation (`budget_truncated`/`dropped_stages`),
    best selection — **no real benchmarking**, so it's fast and deterministic.
  - `report/*`: golden-file `.md` and `.html`; assert HTML has zero external `http(s)` asset refs.
  - `preset/schema.py`: valid/invalid presets, `schema_version` mismatch, round-trip
    `to_dict`→`validate`.
- **Integration (gated):** `NEONPILOT_INTEGRATION=1` runs a real sweep on the tiny GGUF
  (**SmolLM2-135M-Instruct Q4_K_M, 101 MB, `unsloth/SmolLM2-135M-Instruct-GGUF`, ASSUMPTIONS #3 /
  spike S5**). Verifies build→probe→bench→search→report→preset produces well-formed artifacts within
  the **CI budget (180s)**. Model download **cached** (GitHub Actions cache keyed on model URL) so
  it downloads once.
- **CI (macos-arm64, authoritative):** see §7.1 for the workflow shape, timing, and cache fallback.
- **Golden/provenance:** `tests/test_pin.py` (SHA `178a6c44…` consistency);
  `tests/test_no_external_assets.py` (report portability, SC8); `tests/test_shell_quoting.py` (greps
  scripts for unquoted `$VAR`, R4).

**CI timing discipline:** tests **never assert absolute performance numbers** (throughput varies by
runner). They assert *structure* (fields present, best≥baseline in the mocked case, artifacts exist,
budget respected). The 10% speedup (SC2) is proven **on the M1 Max reference machine in M5**, not in
CI.

### 7.1 CI workflow shape, timing budget, and cache fallback

- **Runner:** `macos-14`/`macos-latest` (Apple Silicon, M1/M2-class). Jobs: `lint` (ruff), `test`
  (pytest unit + coverage), `integration` (gated real tiny-model sweep).
- **Cold-build cost:** a from-scratch llama.cpp CPU-only build of the single `llama-bench` target
  (no examples/tests/server, no `llama-cli`) on the macos-arm64 runner is estimated at **~6–9 min**.
  To keep this off the critical path we **cache the built binary** keyed on
  `${{ runner.os }}-b10069-cpuonly`; a warm run restores in seconds. The tiny GGUF is cached
  separately keyed on its URL.
- **`timeout-minutes`:** each job sets an explicit cap — `lint: 10`, `test: 20`,
  `integration: 25` (cold build ~9 + tiny sweep ≤3 + overhead). This guarantees a hung
  `llama-bench` or a stuck build is reaped rather than burning the 6-hour Actions default.
- **Cache-eviction fallback (GitHub Actions ~7-day idle / 10 GB-per-repo limit):** the binary cache
  can be evicted after inactivity or when the repo cache exceeds 10 GB. The workflow therefore
  treats the cache as **best-effort**: a cache miss triggers `scripts/fetch_llama.sh` to rebuild
  from the pinned SHA `178a6c44…` (the `timeout-minutes: 25` on `integration` accommodates a full
  cold build). CI is thus never *dependent* on a warm cache — the cache is a speedup, and a miss
  degrades to a slower-but-green run, not a failure. We prune cache size by keeping only the
  current-SHA key (older SHAs' caches age out naturally).

---

## 8. Risks & mitigations

| # | Risk | Likelihood/Impact | Mitigation | Residual |
|---|---|---|---|---|
| R1 | **Thermal variance** on laptop inflates stddev, threatens 10% bar on late candidates | High/High | Adaptive cooldown (powermetrics/idle-skip, 20 s cap); discard/redo runs with stddev/mean>0.15; measure baseline and best back-to-back in the confirm pass; report stddev honestly | Not fully solved; documented in report methodology |
| R2 | **llama.cpp default threads already near-optimal** → thread tuning alone <10% | High/High | Widen tunable surface beyond threads: KV-cache quant, flash-attn, ubatch (Stage B/C carry most of the gain, and are budget-protected per §4.4). If total gain <10%, **report the real number honestly** (SC2 fails openly, §11), lean on ISA-probe/report/registry differentiators, and revisit the bar in ASSUMPTIONS #10 *with the user* rather than fudge | Gain could still be modest on some models; honest reporting is the policy |
| R3 | **CI flakiness** on timing-sensitive tests | Med/Med | Never assert absolute perf in CI; unit tests use mocked runner; integration asserts structure + budget only; explicit `timeout-minutes` per job | Low |
| R4 | **Path with spaces** in project dir breaks shell/subprocess | Med/High | `pathlib` + argv lists everywhere (never `shell=True`); quote all shell vars; `tests/test_shell_quoting.py` greps scripts for unquoted `$VAR`; a test runs `run_bench` from a spaced temp dir | Low |
| R5 | **M5 access slips** past deadline → SC3 degraded | Med/High | Ship M1 Max as fully-measured; label M5 numbers unverified or omit (never fabricate, ASSUMPTIONS #6); document as known gap | SC3 partial if it slips |
| R6 | **KleidiAI kernel-path messaging** could overclaim on M1 Max | Low/Med | **RESOLVED (spike S3):** verified DOTPROD-tier KleidiAI engages, SME disabled, no i8mm; probe copy fixed to match. M5 SME-tier path to be captured during M5 run | Low |
| R7 | **Pinned commit (b10069) has an Arm regression** vs upstream | Low/Med | Smoke-benchmarked at pin time (S2/S3 build clean, kernels engage); SHA + rationale recorded; re-pin only with changelog | Low |
| R8 | **`cmake` absent / build fails on clean machine** | Med/High | `scripts/setup.sh` + README run `brew install cmake` (installed in S2); CI installs explicitly; build cached on SHA with cold-build fallback (§7.1); setup script fails fast with a clear message | Low |
| R9 | **Malformed/hostile community preset** | Low/Med | `schema.validate` gates all loads; `apply` re-emits a command for user review, doesn't blind-exec | Low |
| R10 | **Tiny CI model too small to show KV/fa deltas** | Low/Low | **Moot for CI:** SmolLM2-135M-Instruct Q4_K_M (101 MB, spike S5) — CI checks *structure* only (well-formed artifacts, budget), never a performance delta; real deltas are proven on the Qwen2.5-3B reference model | None material |
| R11 | **Cooldown consumes the 15-min budget**, forcing truncation of gain-bearing Stage B/C | Med/High | Adaptive/idle-skip cooldown with 20 s cap (§4.4) reclaims ~150–300 s; smaller 2.1 GB reference model halves load time; truncation order drops extras→C→confirm before A/B (confirm protected for SC2 fairness); worst-case budget table shows fit (~668 s) without truncation | Low |

---

## 9. Baseline definition (for the "≥10% vs baseline" success criterion)

SC2 is comparative, so the baseline must be fair and pinned — not a strawman.

- **Baseline = llama.cpp's own out-of-the-box behavior with no neonpilot tuning flags.** Concretely,
  `llama-bench -m <model> -p 512 -n 128 -r 3` with **no** `-t/-ctk/-ctv/-fa/-b/-ub` overrides,
  so llama.cpp applies its shipped defaults (KV `f16`, `-fa auto` → `flash_attn=-1`, `-b 2048`,
  `-ub 512`, and its own default thread count `n_threads=8` on M1 Max, per spike S4). This is the
  honest "what a developer gets if they just run llama.cpp" alternative — reasoning/tuning
  **disabled**, not a hobbled config.
- **Recorded, not assumed:** the baseline trial's resolved thread count and `-fa` decision are
  captured from the JSON and written into `SweepResult.baseline` and the preset, so the comparison
  is reproducible and can't drift. The exact same `-p 512`/`-n 128` prompt/decode lengths, same
  model file (Qwen2.5-3B Q4_K_M), same machine, measured as median of ≥3 reps with stddev.
- **Measured back-to-back with the tuned config** in the §4.1 confirm pass (same thermal-state
  window) to prevent warm-vs-cold bias. Both numbers + stddev shown side-by-side in the HTML report.
- **Speedup** = `(tuned_gen_ts − baseline_gen_ts) / baseline_gen_ts × 100`, on generation t/s
  (primary). Prefill speedup reported separately. Anti-self-flattery: we do **not** pick the
  baseline's worst thread count; llama.cpp chooses its own default (8). If tuned only ties baseline,
  the report says so plainly.

---

## 10. Security, observability, packaging notes

- **Security:** no secrets in repo; HF token not needed (both models public, spike S5) — if a
  future model is gated, use a read-only `HF_TOKEN` CI secret (ASSUMPTIONS credential table). No
  `shell=True`; subprocess argv lists; hard timeouts; untrusted JSON validated. No telemetry/
  phone-home (ASSUMPTIONS #11). HTML report = zero external fetch (SC8), so no CSP/exfil surface.
- **Observability:** every run writes `run.log` (structured, one JSON line per trial: config,
  t/s, stddev, thermal, status) + `result.json`. Rich console shows a live table of trials with
  pruned/ok status. Failures surface the llama-bench argv + captured stderr for reproduction.
- **Packaging:** `pyproject.toml` (PEP 621), console-script `neonpilot = neonpilot.cli:app`,
  `pip install -e .` (SC9). `make benchmark` = setup → probe → optimize → report → apply on a clean
  clone (SC1). Ruff for lint+format (Fixed constraint).

---

## 11. Traceability — success criteria → where satisfied

| SC | Satisfied by |
|---|---|
| SC1 reproducible `make benchmark` | M6, §10 packaging |
| SC2 ≥10% speedup w/ stddev | **Conditionally satisfied** — M5 run, §4 search, §9 baseline. **See R2 fallback:** if the measured gain on the Qwen2.5-3B reference model is <10%, SC2 is reported as **failed honestly with the real number** in the HTML report and README — not silently passed. The 10% bar in REQUIREMENTS/ASSUMPTIONS #10 is then revisited **with the user**, and the differentiation weight shifts to the ISA-probe / cross-generation / preset-registry / report-quality pillars. We never lower the bar only in the README. |
| SC3 cross-gen M1 Max + M5 presets | M5, FR4, §2.1 (M1 Max verified; M5 SME2-tier path pending M5 run; degrades to "M5 unverified" if access slips, R5) |
| SC4 CI green | M0/M6, §7 + §7.1 CI |
| SC5 ≥80% coverage | §7, CI `--cov-fail-under=80` |
| SC6 probe correctness | M1, §1.3 ChipReport, S1 fixture (**i8mm=false** on M1 Max) |
| SC7 CI time budget | §4.4 (180s CI budget), §7.1 timeouts, M3 |
| SC8 self-contained HTML | M4, §5, `test_no_external_assets` |
| SC9 install path | M0, §10 |
| SC10 differentiation section | M6 README |

---

## Revision log

- _2026-07-20 — v1 (initial plan)._ Authored full architecture, data contracts (§1.3), staged
  search (§4), baseline definition (§9), milestones M0–M6, testing, risks. Recorded live upstream
  facts and flagged hardware/`cmake`/KleidiAI probes as Day-1 build tasks (§0).
- _2026-07-20 — v2 (critic round 1)._ Added `budget_truncated`/`dropped_stages` to `SweepResult`;
  defined `SearchPlan`/`SweepContext`/`CooldownPolicy`; pinned `prompt_n`/`gen_n` + worst-case
  budget table + adaptive cooldown; disambiguated the rep model (single `-r reps`, candidate-level
  early stop only); marked SC2 conditional with honest-failure behavior; added §7.1 CI timing +
  cache-eviction fallback.
- _2026-07-20 — v3 (critic round 2 — propagate verified Day-1 spike facts, `docs/dev/day1-spikes.md`)._
  1. **i8mm corrected everywhere.** M1 Max has dotprod but **NOT** i8mm (`FEAT_I8MM=0`, S1): §0 ISA
     row and M1 Done-when now assert `i8mm=false`. **`REQUIREMENTS.md` SC6 corrected** from
     `i8mm=true` to `i8mm=false` to match the verified hardware fixture (authorized correction).
  2. **llama-cli removed.** It doesn't exist with examples off and isn't needed (S2): §3.2 build
     target is `llama-bench` only, §1.2 `preset/io.invocation(p) -> str` re-emits a **llama-bench**
     command, M4 Done-when updated; serving flags now documented as plain-text `Preset.server_flags`
     (no binary dependency). Also added `-DGGML_BLAS=OFF` to match the verified build.
  3. **KleidiAI VERIFIED.** §0 row updated (DOTPROD-tier q4/q8 kernels engaged, SME disabled,
     CPU_KLEIDIAI + CPU_REPACK `q6_K_8x4`, S3); §1.3 `FastPathNote` example rewritten to
     "i8mm ABSENT → DOTPROD-tier KleidiAI kernels engaged" — no i8mm/SME overclaim; R6 marked
     resolved.
  4. **Models reconciled with S5.** Reference benchmark model = **Qwen2.5-3B-Instruct Q4_K_M
     (~2.1 GB)** (updated §4.4/§9/M5/§11 and recomputed the per-config load basis — budget now
     ~668 s worst case with headroom); CI model = **SmolLM2-135M-Instruct Q4_K_M (101 MB, unsloth)**
     (updated §7, R10 now "moot — CI checks structure only"). `ASSUMPTIONS.md` #2/#3 updated.
  5. **Real pin filled.** Tag `b10069` = SHA `178a6c44937154dc4c4eff0d166f4a044c4fceba` in §3.2
     fetch script and §3.1/§1.3 `LLAMA_CPP_COMMIT`, so `test_pin.py` has real matching values.
     `ASSUMPTIONS.md` #4 and the credential table updated.
- _2026-07-20 — v3.1 (critic PASS at 98/100; two sanctioned polish edits applied by orchestrator)._
  §4.4 heading softened from "proof" to "projection (hard-capped by truncation)" — the per-config
  throughput figures are estimates until M5 calibrates them. Truncation order reversed to
  `adaptive extras → Stage C → confirm pass` so the §9 back-to-back confirm measurement (SC2
  fairness) is dropped last, with a mandated report caveat if it ever is; R11 updated to match.
