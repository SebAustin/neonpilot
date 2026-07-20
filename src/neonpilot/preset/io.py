"""Load/save presets in the `presets/<chip-id>/<model-class>.json` registry layout, and
re-emit the exact llama-bench invocation for a stored preset (PLAN.md section 1.2, FR4).
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from neonpilot.models import Preset
from neonpilot.preset.schema import to_dict, validate

#: Allow-list for `chip_id`/`model_class` path segments (SECURITY.md F2). Deliberately excludes
#: "/" and "\\" (no separators) -- the exact-match rejection of "." and "." below closes the
#: remaining gap: a single ".." *segment* needs no separator to traverse a parent directory.
_SAFE_SLUG = re.compile(r"^[a-z0-9._-]+$")
_FORBIDDEN_SLUGS = frozenset({".", ".."})


class UnsafePresetPathError(ValueError):
    """Raised when a preset's `chip_id`/`model_class` would escape the presets root on disk."""


def _sanitize_slug(value: str, field_name: str) -> str:
    """Reject anything that isn't a safe, single path segment.

    :raises UnsafePresetPathError: if `value` is empty, contains characters outside
        `[a-z0-9._-]`, or is exactly `.`/`..` (a traversal token that needs no separator).
    """
    if (
        not isinstance(value, str)
        or not value
        or not _SAFE_SLUG.match(value)
        or value in _FORBIDDEN_SLUGS
    ):
        raise UnsafePresetPathError(
            f"{field_name} must be a safe path segment matching [a-z0-9._-]+ "
            f"(and not '.' or '..'), got {value!r}"
        )
    return value


def _resolved_under(root: Path, *parts: str) -> Path:
    """Join `parts` onto `root` and assert the resolved result stays under `root.resolve()`.

    Belt-and-braces on top of `_sanitize_slug` (SECURITY.md F2): even if the slug allow-list
    were ever loosened, a symlink or an unexpected traversal is still caught here.
    """
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*parts)
    resolved = candidate.resolve()
    if not (resolved == root_resolved or resolved.is_relative_to(root_resolved)):
        raise UnsafePresetPathError(
            f"resolved path {resolved} escapes presets root {root_resolved}"
        )
    return candidate


def save(preset: Preset, root: Path) -> Path:
    """Write `root/<chip_id>/<model_class>.json` (2-space indent, sorted keys, trailing newline).

    :raises UnsafePresetPathError: if `preset.chip_id`/`preset.model_class` are not safe path
        segments, e.g. a forged `chip_id="../../etc"` from a shared/tampered run directory.
    :return: the path written.
    """
    chip_id = _sanitize_slug(preset.chip_id, "chip_id")
    model_class = _sanitize_slug(preset.model_class, "model_class")

    target_dir = _resolved_under(root, chip_id)
    path = _resolved_under(root, chip_id, f"{model_class}.json")
    target_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(preset), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(chip_id: str, model_class: str, root: Path) -> Preset:
    """Load and validate `root/<chip_id>/<model_class>.json`.

    :raises UnsafePresetPathError: if `chip_id`/`model_class` are not safe path segments.
    :raises FileNotFoundError: if no preset exists at that path.
    :raises neonpilot.preset.schema.PresetValidationError: if the file fails validation.
    """
    chip_id = _sanitize_slug(chip_id, "chip_id")
    model_class = _sanitize_slug(model_class, "model_class")

    path = _resolved_under(root, chip_id, f"{model_class}.json")
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
