"""Unit tests for bench/runner.py: argv construction + subprocess error surfacing.

No real subprocess is invoked here (subprocess.run is monkeypatched) -- the real-binary path
is covered by the gated integration test in tests/test_runner_integration.py.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from neonpilot.bench.runner import BenchRunError, build_argv, run_bench
from neonpilot.models import RuntimeConfig

_CFG = RuntimeConfig(
    threads=6, cache_type_k="q8_0", cache_type_v="q8_0", flash_attn="on", batch=4096, ubatch=1024
)


def test_build_argv_with_config_includes_all_tuning_flags():
    argv = build_argv("bin/llama-bench", "model.gguf", _CFG, reps=3, prompt_n=512, gen_n=128)
    assert argv == [
        "bin/llama-bench",
        "-m",
        "model.gguf",
        "-o",
        "json",
        "-t",
        "6",
        "-ctk",
        "q8_0",
        "-ctv",
        "q8_0",
        "-fa",
        "on",
        "-b",
        "4096",
        "-ub",
        "1024",
        "-p",
        "512",
        "-n",
        "128",
        "-r",
        "3",
    ]


def test_build_argv_baseline_omits_tuning_flags():
    argv = build_argv("bin/llama-bench", "model.gguf", None, reps=3, prompt_n=512, gen_n=128)
    assert argv == [
        "bin/llama-bench",
        "-m",
        "model.gguf",
        "-o",
        "json",
        "-p",
        "512",
        "-n",
        "128",
        "-r",
        "3",
    ]
    assert "-t" not in argv
    assert "-fa" not in argv


def test_run_bench_parses_stdout_on_success(monkeypatch):
    fake_stdout = (
        '[{"n_prompt": 64, "n_gen": 0, "avg_ts": 10.0, "stddev_ts": 0.5, "samples_ts": [10.0]}]'
    )

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=fake_stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    samples = run_bench(
        "bin/llama-bench", "model.gguf", None, reps=1, prompt_n=64, gen_n=0, timeout_s=30
    )
    assert len(samples) == 1
    assert samples[0].avg_ts == 10.0


def test_run_bench_raises_on_nonzero_exit(monkeypatch):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BenchRunError, match="exited 1"):
        run_bench("bin/llama-bench", "model.gguf", None, reps=1, prompt_n=64, gen_n=0, timeout_s=30)


def test_run_bench_raises_on_timeout(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=30)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BenchRunError, match="timed out"):
        run_bench("bin/llama-bench", "model.gguf", None, reps=1, prompt_n=64, gen_n=0, timeout_s=30)


def test_run_bench_raises_on_missing_binary(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BenchRunError, match="failed to spawn"):
        run_bench("does/not/exist", "model.gguf", None, reps=1, prompt_n=64, gen_n=0, timeout_s=30)


def test_run_bench_raises_on_permission_error(monkeypatch):
    """H1: a binary that exists but lacks the +x bit raises PermissionError, an OSError
    subclass FileNotFoundError-only handling previously missed, crashing with a raw traceback."""

    def fake_run(argv, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BenchRunError, match="failed to spawn"):
        run_bench("no-exec-bit", "model.gguf", None, reps=1, prompt_n=64, gen_n=0, timeout_s=30)


def test_run_bench_raises_on_exec_format_error(monkeypatch):
    """H1: an x86_64 binary run on arm64 (or similar) raises OSError("Exec format error")."""

    def fake_run(argv, **kwargs):
        raise OSError(8, "Exec format error")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BenchRunError, match="failed to spawn"):
        run_bench(
            "wrong-arch-binary", "model.gguf", None, reps=1, prompt_n=64, gen_n=0, timeout_s=30
        )


def test_run_bench_never_uses_shell_true(monkeypatch):
    captured_kwargs = {}

    fake_stdout = (
        '[{"n_prompt": 1, "n_gen": 0, "avg_ts": 1.0, "stddev_ts": 0.0, "samples_ts": [1.0]}]'
    )

    def fake_run(argv, **kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=fake_stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_bench("bin/llama-bench", "model.gguf", _CFG, reps=1, prompt_n=1, gen_n=0, timeout_s=5)
    assert captured_kwargs.get("shell") is not True
    assert captured_kwargs.get("timeout") == 5
