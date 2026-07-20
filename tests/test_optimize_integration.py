"""Gated integration test: a full `neonpilot optimize` run against the real pinned llama-bench
binary and the real tiny CI model, with a small budget (PLAN.md section 7: CI budget).

Skipped unless `NEONPILOT_INTEGRATION=1` is set, matching tests/test_runner_integration.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from neonpilot.cli import app

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
def test_full_optimize_against_real_binary_and_tiny_model(tmp_path):
    assert _BINARY.exists(), f"llama-bench binary not found at {_BINARY}; run `make fetch-llama`"
    assert _MODEL.exists(), f"tiny CI model not found at {_MODEL}"

    runner = CliRunner()
    out_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "optimize",
            str(_MODEL),
            "--llama-bin",
            str(_BINARY),
            "--out",
            str(out_dir),
            "--budget",
            "180",
            "--reps",
            "2",
            "--prompt-n",
            "32",
            "--gen-n",
            "16",
        ],
    )

    assert result.exit_code == 0, result.output

    run_dirs = [p for p in out_dir.iterdir() if p.is_dir() and p.name != "latest"]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    for filename in ("chip.json", "plan.json", "trials.json", "result.json", "run.log"):
        assert (run_dir / filename).exists(), filename

    data = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert data["best"]["status"] == "ok"
    assert data["elapsed_s"] < 180 or data["budget_truncated"] is True
