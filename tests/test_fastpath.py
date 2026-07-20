"""Unit tests for probe/fastpath.py's ISA -> kernel-tier explanation logic."""

from __future__ import annotations

from neonpilot.probe.fastpath import explain


def _by_feature(notes):
    return {note.feature: note for note in notes}


def test_explain_returns_five_canonical_features():
    notes = explain({})
    features = {note.feature for note in notes}
    assert features == {"neon", "dotprod", "i8mm", "sme", "sme2"}


def test_m1_max_style_isa_engages_dotprod_tier_only():
    notes = _by_feature(
        explain({"neon": True, "dotprod": True, "i8mm": False, "sme": False, "sme2": False})
    )
    assert notes["dotprod"].active is True
    assert notes["i8mm"].active is False
    assert notes["sme2"].active is False
    assert notes["neon"].active is False  # superseded by dotprod


def test_no_isa_features_falls_back_to_scalar():
    notes = _by_feature(explain({}))
    assert notes["neon"].active is False
    assert "NEON absent" in notes["neon"].why
    assert notes["dotprod"].active is False


def test_neon_only_engages_generic_kernel():
    notes = _by_feature(explain({"neon": True}))
    assert notes["neon"].active is True
    assert "generic NEON" in notes["neon"].why


def test_i8mm_present_without_sme2_engages_i8mm_tier():
    notes = _by_feature(explain({"neon": True, "dotprod": True, "i8mm": True, "sme2": False}))
    assert notes["i8mm"].active is True
    assert notes["dotprod"].active is False  # superseded, not double-active


def test_sme2_present_supersedes_everything():
    notes = _by_feature(
        explain({"neon": True, "dotprod": True, "i8mm": True, "sme": True, "sme2": True})
    )
    assert notes["sme2"].active is True
    assert notes["i8mm"].active is False
    assert notes["dotprod"].active is False
    assert "SME2 present" in notes["sme2"].why


def test_sme_without_sme2_is_reported_active():
    notes = _by_feature(explain({"sme": True, "sme2": False}))
    assert notes["sme"].active is True
    assert notes["sme2"].active is False
