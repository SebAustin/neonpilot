"""Gated integration test: invokes the real pinned llama-bench binary against the tiny CI
model (SmolLM2-135M-Instruct Q4_K_M, ASSUMPTIONS.md #3 / docs/dev/day1-spikes.md S5).

Skipped unless `NEONPILOT_INTEGRATION=1` is set (PLAN.md section 7), so the default `make test`
/ `pytest` run never depends on a built binary or a downloaded model.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from neonpilot.bench.runner import run_bench
from neonpilot.models import RuntimeConfig

pytestmark = pytest.mark.integration

_BINARY = Path(
    os.environ.get(
        "NEONPILOT_LLAMA_BIN",
        Path(__file__).parent.parent / "vendor" / "llama.cpp" / "build" / "bin" / "llama-bench",
    )
)
_MODEL = Path.home() / ".neonpilot" / "models" / "SmolLM2-135M-Instruct-Q4_K_M.gguf"

_SKIP_REASON = "set NEONPILOT_INTEGRATION=1 to run real-binary integration tests"


@pytest.mark.skipif(os.environ.get("NEONPILOT_INTEGRATION") != "1", reason=_SKIP_REASON)
def test_run_bench_against_real_binary_and_tiny_model():
    assert _BINARY.exists(), f"llama-bench binary not found at {_BINARY}; run `make fetch-llama`"
    assert _MODEL.exists(), f"tiny CI model not found at {_MODEL}"

    samples = run_bench(
        str(_BINARY),
        str(_MODEL),
        cfg=None,  # baseline: no tuning flags
        reps=2,
        prompt_n=32,
        gen_n=16,
        timeout_s=120,
    )

    assert len(samples) == 2
    test_types = {sample.test_type for sample in samples}
    assert test_types == {"pp", "tg"}
    for sample in samples:
        assert sample.avg_ts > 0
        assert len(sample.samples_ts) == 2


@pytest.mark.skipif(os.environ.get("NEONPILOT_INTEGRATION") != "1", reason=_SKIP_REASON)
def test_run_bench_with_explicit_config_against_real_binary():
    assert _BINARY.exists(), f"llama-bench binary not found at {_BINARY}; run `make fetch-llama`"
    assert _MODEL.exists(), f"tiny CI model not found at {_MODEL}"

    cfg = RuntimeConfig(
        threads=4, cache_type_k="f16", cache_type_v="f16", flash_attn="auto", batch=2048, ubatch=512
    )
    samples = run_bench(
        str(_BINARY), str(_MODEL), cfg, reps=1, prompt_n=32, gen_n=16, timeout_s=120
    )
    assert len(samples) == 2
