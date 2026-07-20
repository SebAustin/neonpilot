"""Preset schema validation (PLAN.md section 1.2/1.4).

A preset JSON file may be contributed by a third party (FR4). `validate` is the single gate
every loaded preset passes through: reject a `schema_version` mismatch or missing fields with
a clear error, never silently coerce or partially trust untrusted community data (PLAN.md
section 1.4, rule 4).
"""

from __future__ import annotations

import dataclasses

from neonpilot._hydrate import from_dict
from neonpilot.models import SCHEMA_VERSION, Preset


class PresetValidationError(Exception):
    """Raised when a preset dict fails schema validation."""


def validate(data: object) -> Preset:
    """Validate an untrusted dict and return a `Preset`.

    :raises PresetValidationError: if `data` isn't a dict, has the wrong `schema_version`, is
        missing required fields, or has a field of the wrong shape.
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
        return from_dict(Preset, data)
    except (TypeError, KeyError, ValueError) as exc:
        raise PresetValidationError(f"malformed preset: {exc}") from exc


def to_dict(preset: Preset) -> dict:
    """Serialize a `Preset` to a plain dict (for `json.dumps`)."""
    return dataclasses.asdict(preset)
