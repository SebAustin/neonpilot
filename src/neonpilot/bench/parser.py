"""Parse `llama-bench -o json` stdout into validated BenchSample rows.

Trust boundary: llama-bench is a pinned but third-party binary (PLAN.md section 1.4). Its
stdout is untrusted until this parser validates shape and types. Malformed input raises
`BenchParseError` rather than propagating a raw `KeyError`/`TypeError`/`json.JSONDecodeError`,
so callers (the future `search/engine.py`) can catch one exception type and record
`TrialResult(status="error")`.
"""

from __future__ import annotations

import json

from neonpilot.models import BenchSample

#: Keys every llama-bench JSON row must have (PLAN.md section 0 verified field list, S4).
_REQUIRED_KEYS = ("n_prompt", "n_gen", "avg_ts", "stddev_ts", "samples_ts")


class BenchParseError(Exception):
    """Raised when llama-bench stdout is not the expected JSON array shape."""


def _classify(row: dict) -> str:
    """A `pp` (prefill) row has n_prompt > 0; a `tg` (generation) row has n_gen > 0."""
    if row["n_prompt"] > 0:
        return "pp"
    if row["n_gen"] > 0:
        return "tg"
    raise BenchParseError(f"row has neither n_prompt nor n_gen > 0: {row!r}")


def _validate_row(row: object) -> dict:
    if not isinstance(row, dict):
        raise BenchParseError(f"expected a JSON object per row, got {type(row).__name__}")
    missing = [key for key in _REQUIRED_KEYS if key not in row]
    if missing:
        raise BenchParseError(f"row missing required keys {missing}: {row!r}")
    if not isinstance(row["samples_ts"], list) or not row["samples_ts"]:
        raise BenchParseError(f"samples_ts must be a non-empty list: {row!r}")
    try:
        int(row["n_prompt"])
        int(row["n_gen"])
        float(row["avg_ts"])
        float(row["stddev_ts"])
        [float(sample) for sample in row["samples_ts"]]
    except (TypeError, ValueError) as exc:
        raise BenchParseError(f"row has non-numeric field: {row!r}") from exc
    return row


def parse(stdout: str) -> list[BenchSample]:
    """Parse llama-bench's `-o json` stdout into a list of BenchSample.

    :param stdout: raw stdout captured from the llama-bench subprocess.
    :raises BenchParseError: if `stdout` is not valid JSON, not a non-empty array, or any row
        is missing required keys / has non-numeric fields.
    """
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BenchParseError(f"stdout is not valid JSON: {exc}") from exc

    if not isinstance(parsed, list) or not parsed:
        raise BenchParseError("expected a non-empty JSON array from llama-bench -o json")

    samples: list[BenchSample] = []
    for row in parsed:
        validated = _validate_row(row)
        samples.append(
            BenchSample(
                test_type=_classify(validated),
                n_prompt=int(validated["n_prompt"]),
                n_gen=int(validated["n_gen"]),
                avg_ts=float(validated["avg_ts"]),
                stddev_ts=float(validated["stddev_ts"]),
                samples_ts=[float(sample) for sample in validated["samples_ts"]],
            )
        )
    return samples
