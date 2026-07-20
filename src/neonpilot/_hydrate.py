"""Generic dict -> frozen-dataclass rehydration for neonpilot.models types.

`dataclasses.asdict` handles the dataclass -> dict direction everywhere in this codebase; this
module handles the reverse (dict, e.g. loaded from JSON -> the exact nested dataclass tree),
which `artifacts.py` and `preset/schema.py` both need to reconstruct a `ChipReport`/
`SweepResult`/`Preset` after a round trip through disk. Kept internal (leading underscore):
callers should go through `artifacts.load_*` / `preset.schema.validate`, not this directly.
"""

from __future__ import annotations

import dataclasses
import types
import typing

_NONE_TYPE = type(None)
_UNION_ORIGINS = (typing.Union, types.UnionType)

#: Scalar types that get *strict* isinstance validation during hydration (SECURITY.md F1):
#: a preset/artifact JSON is untrusted input, and prior to this fix `from_dict` accepted any
#: value for a scalar field (e.g. a string in a declared `int` field) without complaint, only
#: to fail later -- or not fail at all -- deep inside engine/report code. `bool` is checked
#: first because `bool` is a subclass of `int` in Python (`isinstance(True, int) is True`),
#: so a naive `isinstance` check alone would silently accept booleans in int/float fields.
_STRICT_SCALAR_TYPES = (bool, int, float, str)


def from_dict(cls: type, data: object) -> object:
    """Reconstruct a `cls` dataclass instance from a plain dict (as produced by `json.loads`).

    :raises TypeError: if `data` is missing required fields or a value has the wrong shape.
    """
    if data is None:
        return None
    if not dataclasses.is_dataclass(cls):
        return data
    if not isinstance(data, dict):
        raise TypeError(f"expected a dict to build {cls.__name__}, got {type(data).__name__}")

    hints = typing.get_type_hints(cls)
    kwargs = {}
    for field in dataclasses.fields(cls):
        if field.name not in data:
            raise TypeError(f"{cls.__name__} missing required field {field.name!r}")
        kwargs[field.name] = _convert(hints[field.name], data[field.name])
    return cls(**kwargs)


def _convert(field_type: object, value: object) -> object:
    origin = typing.get_origin(field_type)

    if origin in _UNION_ORIGINS:
        non_none = [arg for arg in typing.get_args(field_type) if arg is not _NONE_TYPE]
        if value is None:
            return None
        return _convert(non_none[0], value)

    if origin is list:
        if not isinstance(value, list):
            raise TypeError(f"expected a list, got {type(value).__name__}: {value!r}")
        (item_type,) = typing.get_args(field_type)
        return [_convert(item_type, item) for item in value]

    if dataclasses.is_dataclass(field_type):
        return from_dict(field_type, value)

    if field_type in _STRICT_SCALAR_TYPES:
        return _convert_scalar(field_type, value)

    return value


def _convert_scalar(field_type: type, value: object) -> object:
    """Strictly validate a scalar leaf value against its declared dataclass field type.

    :raises TypeError: on any type mismatch, including `bool` masquerading as `int`/`float`
        (a real JSON footgun) and numeric values in `str` fields or vice versa.
    """
    if field_type is bool:
        if not isinstance(value, bool):
            raise TypeError(f"expected bool, got {type(value).__name__}: {value!r}")
        return value
    if field_type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"expected int, got {type(value).__name__}: {value!r}")
        return value
    if field_type is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"expected float, got {type(value).__name__}: {value!r}")
        return float(value)
    # field_type is str
    if not isinstance(value, str):
        raise TypeError(f"expected str, got {type(value).__name__}: {value!r}")
    return value
