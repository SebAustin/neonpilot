"""Core data contracts shared across neonpilot modules.

All dataclasses here are ``@dataclass(frozen=True)`` (immutable per repo style) and serialize
via ``dataclasses.asdict``. This module has zero internal dependencies so every other module
in the package may import it without creating cycles.

See ``PLAN.md`` section 1.3 for the authoritative schema this module implements.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Schema version stamped onto every persisted artifact (ChipReport, SweepResult, Preset).
SCHEMA_VERSION = "1.0.0"

# Pinned llama.cpp: tag b10069 = SHA 178a6c44937154dc4c4eff0d166f4a044c4fceba.
# Canonical value lives in neonpilot/_llama_pin.py (LLAMA_CPP_COMMIT); asserted by test_pin.py.


@dataclass(frozen=True)
class FastPathNote:
    """One line of "why does/doesn't this Arm feature speed up llama.cpp" explanation."""

    feature: str  # "i8mm" | "dotprod" | "sme2" | ...
    kernel: str  # "KleidiAI DOTPROD q4/q8 GEMM" | "CPU_REPACK q6_K_8x4" | "SME2 kernel (M5)"
    active: bool  # does THIS chip activate it?
    why: str  # e.g. "i8mm ABSENT -> DOTPROD-tier KleidiAI kernels engaged"


@dataclass(frozen=True)
class ChipReport:
    """Snapshot of a probed Arm CPU: topology, RAM, ISA features, and fast-path mapping."""

    schema_version: str  # SCHEMA_VERSION
    probed_at: str  # ISO-8601 UTC
    platform: str  # "darwin" | "linux"
    chip_name: str  # "Apple M1 Max"
    chip_id: str  # slug: "apple-m1-max"
    cpu_brand: str  # raw brand string
    p_cores: int  # M1 Max: 8
    e_cores: int  # M1 Max: 2
    total_cores: int  # M1 Max: 10
    ram_gb: float
    isa: dict[str, bool]  # keys: neon,dotprod,i8mm,sve,sve2,sme,sme2,bf16,fp16
    fast_paths: list[FastPathNote]
    raw: dict[str, str]  # captured source keys, for provenance + fixtures


@dataclass(frozen=True)
class RuntimeConfig:
    """A candidate (or winning) set of llama.cpp runtime tuning flags."""

    threads: int
    cache_type_k: str  # "f16" | "q8_0" | "q4_0" | ...
    cache_type_v: str
    flash_attn: str  # "on" | "off" | "auto"
    batch: int  # -b  (logical, default 2048)
    ubatch: int  # -ub (physical, default 512)


@dataclass(frozen=True)
class BenchSample:
    """One llama-bench JSON row, trusted for its own avg/stddev over `-r reps` samples."""

    test_type: str  # "pp" (prefill) | "tg" (generation)
    n_prompt: int
    n_gen: int
    avg_ts: float  # tokens/sec  (from llama-bench avg_ts)
    stddev_ts: float  # from llama-bench stddev_ts
    samples_ts: list[float]  # per-rep tokens/sec


@dataclass(frozen=True)
class ThermalSnapshot:
    """Result of a single cooldown gap between benchmark trials."""

    source: str  # "powermetrics" | "elapsed-fallback" | "idle-skip"
    cpu_temp_c: float | None
    throttled: bool | None
    cooldown_s: float  # actual seconds waited for this gap


@dataclass(frozen=True)
class TrialResult:
    """The outcome of benchmarking one RuntimeConfig candidate."""

    trial_id: str  # "A2", "B1-fa_on-q8_0"
    stage: str  # "A" | "B" | "C" | "baseline" | "confirm"
    config: RuntimeConfig
    prefill: BenchSample | None
    generation: BenchSample | None
    reps: int
    started_at: str
    ended_at: str
    thermal: ThermalSnapshot | None
    status: str  # "ok" | "pruned" | "error"
    error: str | None
    # Extension beyond PLAN.md section 1.3's original contract -- see docs/dev/build-notes.md
    # (robustness review H3). True only for the baseline/confirm-baseline trials (cfg=None):
    # `.config` there is a *reconstruction* of what llama.cpp is expected to resolve to (not
    # parsed from the actual JSON response -- BenchSample carries no n_threads/type_k/type_v/
    # flash_attn), so it must never be treated as a measured, appliable config (e.g. packaged
    # into a Preset). Defaults to False so every pre-existing construction site/serialized
    # artifact is unaffected; `_hydrate.from_dict` fills this in from the field default when
    # hydrating an older result.json that predates this field.
    is_synthetic_config: bool = False


@dataclass(frozen=True)
class CooldownPolicy:
    """Configuration for the thermal cooldown guard between trials."""

    target_temp_c: float | None  # cool until below this (None => no sensor available)
    max_cooldown_s: float  # hard cap on any single cooldown gap
    fixed_delay_s: float  # used when no sensor AND idle check unavailable
    idle_skip: bool  # skip cooldown when a thermal/idle check says already cool


@dataclass(frozen=True)
class SweepBudget:
    """Time and workload budget for one `optimize` run."""

    total_seconds: int  # 900 full-model, 180 CI
    reps: int  # >= 3 (single `-r reps` call per config, see PLAN.md 4.3)
    prompt_n: int  # -p tokens (prefill workload); full-model=512, CI=64
    gen_n: int  # -n tokens (decode workload);  full-model=128, CI=32


@dataclass(frozen=True)
class SearchPlan:
    """Staged candidate sets produced by `search/planner.py`."""

    stage_a: list[RuntimeConfig]  # thread candidates (topology-derived)
    stage_b: list[RuntimeConfig]  # fa x kv-cache candidates
    stage_c: list[RuntimeConfig]  # (batch, ubatch) candidates
    baseline: RuntimeConfig | None  # None => "no tuning flags" (llama.cpp defaults, PLAN.md 9)
    notes: list[str]  # human-readable rationale per stage


@dataclass(frozen=True)
class SweepContext:
    """Everything `search/engine.py` needs to run a sweep, independent of the CLI."""

    binary: str  # path to build/bin/llama-bench
    model_path: str  # absolute path to the .gguf under test
    model_class: str  # e.g. "qwen2.5-3b-instruct-q4_k_m"
    out_dir: str  # run-dir for artifacts/logs
    budget: SweepBudget
    cooldown: CooldownPolicy
    timeout_s: int  # per-invocation hard timeout for the runner
    llama_cpp_commit: str  # pinned SHA (recorded into SweepResult)
    # Extension beyond PLAN.md section 1.3 (robustness review H3): the thread count llama.cpp
    # is expected to resolve to when no `-t` flag is given (its own default heuristic is the
    # chip's P-core count). Used only to build a plausible `TrialResult.config` *display* value
    # for the baseline/confirm-baseline trials (`is_synthetic_config=True`) -- never used to
    # build actual argv (the baseline call omits `-t` entirely, letting llama.cpp resolve its
    # own default). Defaults to 8 (the previously-hardcoded value) so existing callers/tests
    # that don't care about baseline display accuracy are unaffected; `cli.py` always passes
    # the real probed `chip.p_cores`.
    baseline_threads: int = 8


@dataclass(frozen=True)
class SweepResult:
    """Final output of a search/engine.run() sweep."""

    schema_version: str
    model_file: str
    model_class: str
    llama_cpp_commit: str
    baseline: TrialResult  # llama.cpp defaults, no tuning flags
    trials: list[TrialResult]  # every candidate incl. pruned/error
    best: TrialResult
    speedup_gen_pct: float  # (best.gen - baseline.gen)/baseline.gen*100
    speedup_prefill_pct: float
    elapsed_s: float
    budget: SweepBudget
    budget_truncated: bool  # True iff a stage/confirm pass was dropped to fit budget
    dropped_stages: list[str]  # e.g. ["C", "confirm"]; [] when nothing dropped


@dataclass(frozen=True)
class Preset:
    """A versioned, shareable, winning runtime config for a (chip, model_class) pair."""

    schema_version: str
    chip_id: str
    chip: ChipReport  # full probe snapshot (provenance)
    model_class: str  # "qwen2.5-3b-instruct-q4_k_m"
    model_file: str  # filename only, not absolute path
    config: RuntimeConfig  # winning flags
    llama_cpp_commit: str  # pinned SHA
    generated_at: str
    baseline_gen_ts: float
    baseline_prefill_ts: float
    tuned_gen_ts: float
    tuned_prefill_ts: float
    tuned_gen_stddev: float
    speedup_gen_pct: float
    speedup_prefill_pct: float
    server_flags: str  # equivalent llama-server flags as plain text (no binary dep)
    neonpilot_version: str
    os_version: str
    reps: int
    cooldown_s: float
