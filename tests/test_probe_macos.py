"""Golden tests for probe/macos_sysctl.py against real + synthetic sysctl fixtures.

M1 Max fixture is a real capture (docs/dev/day1-spikes.md S1): asserts the exact verified ISA
truth (neon/dotprod/fp16=true, i8mm/sme/sme2=false) and topology (8 P + 2 E = 10 cores).
M5 fixture is clearly labeled synthetic (see its header comment) and exercises the SME2 code
path only -- never treated as measured data.
"""

from __future__ import annotations

from neonpilot.models import SCHEMA_VERSION
from neonpilot.probe.macos_sysctl import read_chip_report


def test_m1_max_isa_truth(fixture_text):
    report = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))

    assert report.isa["neon"] is True
    assert report.isa["dotprod"] is True
    assert report.isa["fp16"] is True
    assert report.isa["i8mm"] is False
    assert report.isa["bf16"] is False
    assert report.isa["sme"] is False
    assert report.isa["sme2"] is False
    assert report.isa["sve"] is False
    assert report.isa["sve2"] is False


def test_m1_max_topology_and_identity(fixture_text):
    report = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))

    assert report.chip_name == "Apple M1 Max"
    assert report.chip_id == "apple-m1-max"
    assert report.p_cores == 8
    assert report.e_cores == 2
    assert report.total_cores == 10
    assert report.ram_gb == 64.0
    assert report.platform == "darwin"
    assert report.schema_version == SCHEMA_VERSION


def test_m1_max_fast_path_notes_no_i8mm_overclaim(fixture_text):
    report = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    notes_by_feature = {note.feature: note for note in report.fast_paths}

    dotprod_note = notes_by_feature["dotprod"]
    assert dotprod_note.active is True
    assert "i8mm ABSENT" in dotprod_note.why
    assert "DOTPROD-tier" in dotprod_note.why

    i8mm_note = notes_by_feature["i8mm"]
    assert i8mm_note.active is False

    sme2_note = notes_by_feature["sme2"]
    assert sme2_note.active is False


def test_m1_max_provenance_raw_keys_present(fixture_text):
    report = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    assert report.raw["hw.optional.arm.FEAT_I8MM"] == "0"
    assert report.raw["hw.optional.arm.FEAT_DotProd"] == "1"
    assert report.raw["machdep.cpu.brand_string"] == "Apple M1 Max"


def test_m5_synthetic_sme2_code_path(fixture_text):
    report = read_chip_report(fixture_text("sysctl_apple_m5_synthetic.txt"))

    assert report.isa["sme2"] is True
    assert report.isa["i8mm"] is True

    notes_by_feature = {note.feature: note for note in report.fast_paths}
    sme2_note = notes_by_feature["sme2"]
    assert sme2_note.active is True
    assert "SME2 present" in sme2_note.why

    # i8mm present but superseded by the higher SME2 tier -- not double-counted as active.
    assert notes_by_feature["i8mm"].active is False
    assert notes_by_feature["dotprod"].active is False


def test_missing_keys_default_gracefully():
    report = read_chip_report("machdep.cpu.brand_string: Mystery Chip\n")

    assert report.chip_name == "Mystery Chip"
    assert report.p_cores == 0
    assert report.e_cores == 0
    assert report.ram_gb == 0.0
    assert all(value is False for value in report.isa.values())


def test_empty_input_does_not_raise():
    report = read_chip_report("")
    assert report.chip_name == "Unknown Apple Silicon"
    assert report.total_cores == 0
