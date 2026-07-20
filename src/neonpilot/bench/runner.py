"""Spawn the pinned `llama-bench` binary and return parsed BenchSample rows.

This is the *only* module in neonpilot that spawns the untrusted llama-bench subprocess
(PLAN.md section 1.4): argv lists only, never `shell=True`, always a hard `timeout_s`, stdout
validated by `bench/parser.py` before use.

Baseline measurement: passing `cfg=None` omits all tuning flags (`-t/-ctk/-ctv/-fa/-b/-ub`) so
llama.cpp applies its own shipped defaults (PLAN.md section 3.3/9). This mirrors
`SearchPlan.baseline: RuntimeConfig | None`, which already models "no tuning" as `None`.
"""

from __future__ import annotations

import subprocess

from neonpilot.bench.parser import parse
from neonpilot.models import BenchSample, RuntimeConfig


class BenchRunError(Exception):
    """Raised when the llama-bench subprocess fails to run or exits non-zero."""


def build_argv(
    binary: str,
    model: str,
    cfg: RuntimeConfig | None,
    reps: int,
    prompt_n: int,
    gen_n: int,
) -> list[str]:
    """Build the llama-bench argv list for one config (PLAN.md section 3.3).

    :param cfg: tuning flags to apply, or ``None`` for the baseline (llama.cpp defaults).
    """
    argv = [binary, "-m", model, "-o", "json"]
    if cfg is not None:
        argv += [
            "-t",
            str(cfg.threads),
            "-ctk",
            cfg.cache_type_k,
            "-ctv",
            cfg.cache_type_v,
            "-fa",
            cfg.flash_attn,
            "-b",
            str(cfg.batch),
            "-ub",
            str(cfg.ubatch),
        ]
    argv += ["-p", str(prompt_n), "-n", str(gen_n), "-r", str(reps)]
    return argv


def run_bench(
    binary: str,
    model: str,
    cfg: RuntimeConfig | None,
    reps: int,
    prompt_n: int,
    gen_n: int,
    timeout_s: int,
) -> list[BenchSample]:
    """Run one llama-bench invocation (covering all `reps`) and return parsed samples.

    :raises BenchRunError: on a non-zero exit, a timeout, or a missing/unreadable binary.
    :raises neonpilot.bench.parser.BenchParseError: if stdout is not well-formed JSON.
    """
    argv = build_argv(binary, model, cfg, reps, prompt_n, gen_n)
    try:
        # SECURITY.md F10 (LOW, accepted): no memory/CPU rlimit on the child -- a hostile GGUF
        # could drive the process to consume large CPU/RAM up until `timeout_s` expires. Not
        # applying `resource.setrlimit`/`preexec_fn` here deliberately: this is a single-user
        # local CLI (no privilege boundary is crossed; the child runs as the invoking user and
        # can already do anything that user can), the hard timeout already bounds wall-clock
        # duration, and platform-portable rlimit behavior (esp. RLIMIT_AS on macOS) is fiddly
        # enough that adding it here would be disproportionate engineering for a LOW/local-only
        # finding. Revisit if neonpilot ever benchmarks untrusted GGUFs on shared infrastructure.
        result = subprocess.run(  # noqa: S603 -- fixed argv list, no shell, hard timeout
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BenchRunError(f"llama-bench binary not found: {binary!r}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BenchRunError(f"llama-bench timed out after {timeout_s}s: {argv}") from exc

    if result.returncode != 0:
        raise BenchRunError(
            f"llama-bench exited {result.returncode} for argv={argv}: {result.stderr.strip()}"
        )
    return parse(result.stdout)
