"""Preset schema validation (PLAN.md section 1.2/1.4).

A preset JSON file may be contributed by a third party (FR4). `validate` is the single gate
every loaded preset passes through: reject a `schema_version` mismatch or missing fields with
a clear error, never silently coerce or partially trust untrusted community data (PLAN.md
section 1.4, rule 4).
"""

from __future__ import annotations

import dataclasses

from neonpilot._hydrate import from_dict
from neonpilot.models import SCHEMA_VERSION, Preset, RuntimeConfig

#: `RuntimeConfig.flash_attn`'s declared domain (models.py docstring: "on" | "off" | "auto").
_VALID_FLASH_ATTN = frozenset({"on", "off", "auto"})

#: KV-cache quant types llama.cpp's `-ctk`/`-ctv` accept (ggml type names valid as a KV cache
#: type). PLAN.md section 4.1 only *sweeps* {f16, q8_0, q4_0}; this allow-list is intentionally
#: a superset of the swept set so a preset produced from a manually-chosen (not swept) KV type
#: is not rejected outright, while still bounding the field to known-real ggml type names.
_VALID_CACHE_TYPES = frozenset(
    {"f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1", "q6_0", "iq4_nl"}
)

#: Sane upper bounds for positive-int config fields (SECURITY.md F1): generous enough for any
#: real chip/workload, tight enough to reject nonsense (e.g. threads=2**31).
#: `MAX_REPS` is public (not `_`-prefixed): robustness review H5 reuses it as the `--reps`
#: upper bound in `cli.py`, so the CLI and the preset schema it eventually feeds can never
#: drift apart on what a "valid" reps value is.
_MAX_THREADS = 1024
_MAX_BATCH = 1 << 20
MAX_REPS = 1000


class PresetValidationError(Exception):
    """Raised when a preset dict fails schema validation."""


def validate(data: object) -> Preset:
    """Validate an untrusted dict and return a `Preset`.

    :raises PresetValidationError: if `data` isn't a dict, has the wrong `schema_version`, is
        missing required fields, has a field of the wrong scalar type, an out-of-range numeric
        config value, an unrecognized `flash_attn`/`cache_type_k`/`cache_type_v`, or a
        `model_file` that isn't a bare filename.
    """
    if not isinstance(data, dict):
        raise PresetValidationError(f"preset must be a JSON object, got {type(data).__name__}")

    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise PresetValidationError(
            f"unsupported preset schema_version {schema_version!r} (expected {SCHEMA_VERSION!r})"
        )

    missing = [field.name for field in dataclasses.fields(Preset) if field.name not in data]
    if missing:
        raise PresetValidationError(f"preset missing required fields: {missing}")

    try:
        preset = from_dict(Preset, data)
    except (TypeError, KeyError, ValueError) as exc:
        raise PresetValidationError(f"malformed preset: {exc}") from exc

    _validate_runtime_config(preset.config)
    _validate_model_file(preset.model_file)
    if preset.reps < 1 or preset.reps > MAX_REPS:
        raise PresetValidationError(f"reps must be between 1 and {MAX_REPS}, got {preset.reps}")

    return preset


def _validate_runtime_config(cfg: RuntimeConfig) -> None:
    if cfg.flash_attn not in _VALID_FLASH_ATTN:
        raise PresetValidationError(
            f"config.flash_attn must be one of {sorted(_VALID_FLASH_ATTN)}, got {cfg.flash_attn!r}"
        )
    for name, cache_type in (
        ("cache_type_k", cfg.cache_type_k),
        ("cache_type_v", cfg.cache_type_v),
    ):
        if cache_type not in _VALID_CACHE_TYPES:
            raise PresetValidationError(
                f"config.{name} must be one of {sorted(_VALID_CACHE_TYPES)}, got {cache_type!r}"
            )
    if not (1 <= cfg.threads <= _MAX_THREADS):
        raise PresetValidationError(
            f"config.threads must be between 1 and {_MAX_THREADS}, got {cfg.threads}"
        )
    for name, value in (("batch", cfg.batch), ("ubatch", cfg.ubatch)):
        if not (1 <= value <= _MAX_BATCH):
            raise PresetValidationError(
                f"config.{name} must be between 1 and {_MAX_BATCH}, got {value}"
            )


def _validate_model_file(model_file: str) -> None:
    """`model_file` must be a bare filename: no path separators, no `.`/`..` traversal tokens
    (SECURITY.md F1/F2 -- `preset/io.invocation()` embeds this value in a printed command line,
    and a future consumer could join it onto a directory)."""
    if not model_file or model_file in (".", ".."):
        raise PresetValidationError(
            f"model_file must be a non-empty bare filename, got {model_file!r}"
        )
    if "/" in model_file or "\\" in model_file:
        raise PresetValidationError(
            f"model_file must not contain path separators, got {model_file!r}"
        )


def to_dict(preset: Preset) -> dict:
    """Serialize a `Preset` to a plain dict (for `json.dumps`)."""
    return dataclasses.asdict(preset)
