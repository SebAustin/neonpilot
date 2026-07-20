"""Load/save presets in the `presets/<chip-id>/<model-class>.json` registry layout, and
re-emit the exact llama-bench invocation for a stored preset (PLAN.md section 1.2, FR4).
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from neonpilot.models import Preset
from neonpilot.preset.schema import to_dict, validate


def save(preset: Preset, root: Path) -> Path:
    """Write `root/<chip_id>/<model_class>.json` (2-space indent, sorted keys, trailing newline).

    :return: the path written.
    """
    target_dir = root / preset.chip_id
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{preset.model_class}.json"
    path.write_text(json.dumps(to_dict(preset), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(chip_id: str, model_class: str, root: Path) -> Preset:
    """Load and validate `root/<chip_id>/<model_class>.json`.

    :raises FileNotFoundError: if no preset exists at that path.
    :raises neonpilot.preset.schema.PresetValidationError: if the file fails validation.
    """
    path = root / chip_id / f"{model_class}.json"
    if not path.exists():
        raise FileNotFoundError(f"no preset at {path}")
    return validate(json.loads(path.read_text(encoding="utf-8")))


def invocation(preset: Preset) -> str:
    """Re-emit the exact `llama-bench` command line for a preset's winning config.

    Shell-quoted (`shlex.quote`) so the emitted string is safe to copy-paste, including for
    paths containing spaces (this repo's own directory is one such path).
    """
    cfg = preset.config
    parts = [
        "llama-bench",
        "-m",
        preset.model_file,
        "-o",
        "json",
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
        "-r",
        str(preset.reps),
    ]
    return " ".join(shlex.quote(part) for part in parts)
