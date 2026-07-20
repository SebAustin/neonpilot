"""Run-directory creation and JSON (de)serialization for neonpilot artifacts (PLAN.md section 2).

Run artifacts live at `~/.neonpilot/runs/<ISO-timestamp>/` by default (with a best-effort
`latest` symlink); `--out DIR` overrides this (used by CI, per PLAN.md section 2.1).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

from neonpilot._hydrate import from_dict
from neonpilot.models import ChipReport, SweepResult, TrialResult

_DEFAULT_RUNS_ROOT = Path.home() / ".neonpilot" / "runs"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def new_run_dir(root: Path | None = None) -> Path:
    """Create a fresh, empty run directory and best-effort update the `latest` symlink.

    :param root: parent directory for runs (default: `~/.neonpilot/runs`). CI passes
        `--out ./runs` so run artifacts land inside the workspace (PLAN.md section 2.1).
    """
    base = root if root is not None else _DEFAULT_RUNS_ROOT
    base.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime(_TIMESTAMP_FORMAT)
    run_dir = base / timestamp
    suffix = 1
    while run_dir.exists():
        run_dir = base / f"{timestamp}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)

    _update_latest_symlink(base, run_dir)
    return run_dir


def _update_latest_symlink(base: Path, run_dir: Path) -> None:
    """Best-effort `latest` symlink; never fails the run if the platform lacks symlinks."""
    latest = base / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(run_dir.name)
    except OSError:
        pass  # e.g. no symlink support -- artifacts are still written to run_dir itself.


def _jsonable(obj: object) -> object:
    """Recursively convert dataclasses (and lists/dicts containing them) into JSON-safe values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {name: _jsonable(value) for name, value in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_jsonable(item) for item in obj]
    return obj


def dump(obj: object, path: Path) -> None:
    """Serialize `obj` (a dataclass, or a list of dataclasses) to `path` as stable JSON.

    2-space indent, sorted keys, trailing newline -- matches PLAN.md section 1.3's preset
    on-disk format, applied uniformly to all persisted artifacts.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _jsonable(obj) if dataclasses.is_dataclass(obj) else [_jsonable(item) for item in obj]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path) -> dict | list:
    """Load and return the parsed JSON at `path`. Callers rehydrate into dataclasses as needed."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_chip_report(path: Path) -> ChipReport:
    """Load a `chip.json` artifact back into a `ChipReport`."""
    return from_dict(ChipReport, load(path))


def load_sweep_result(path: Path) -> SweepResult:
    """Load a `result.json` artifact back into a `SweepResult`."""
    return from_dict(SweepResult, load(path))


def write_run_log(path: Path, result: SweepResult) -> None:
    """Write one structured JSON line per trial (config, t/s, stddev, thermal, status).

    PLAN.md section 10: "every run writes run.log (structured, one JSON line per trial...)".
    """
    all_trials: list[TrialResult] = [result.baseline, *result.trials]
    lines = [json.dumps(_trial_log_entry(trial), sort_keys=True) for trial in all_trials]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _trial_log_entry(trial: TrialResult) -> dict:
    return {
        "trial_id": trial.trial_id,
        "stage": trial.stage,
        "status": trial.status,
        "config": dataclasses.asdict(trial.config),
        "gen_ts": trial.generation.avg_ts if trial.generation else None,
        "gen_stddev_ts": trial.generation.stddev_ts if trial.generation else None,
        "prefill_ts": trial.prefill.avg_ts if trial.prefill else None,
        "thermal": dataclasses.asdict(trial.thermal) if trial.thermal else None,
        "error": trial.error,
    }
