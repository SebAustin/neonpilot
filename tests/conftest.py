"""Shared pytest fixtures: fixture-file loading helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    """Return a function that reads a fixture file (relative to tests/fixtures/) as text."""

    def _read(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return _read
