"""Tests for probe/linux_cpuinfo.py against a synthetic /proc/cpuinfo + hwcap fixture.

Linux/Graviton is "designed to work, untested" (REQUIREMENTS.md non-goals) -- these tests
verify the parser's own logic is internally consistent (hwcap bit -> isa flag mapping,
core counting, graceful defaults), not that it matches a specific real machine.
"""

from __future__ import annotations

from neonpilot.probe.linux_cpuinfo import read_chip_report

_GRAVITON2_CPUINFO = """\
processor\t: 0
BogoMIPS\t: 243.75
Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm asimddp
CPU implementer\t: 0x41
CPU architecture: 8
CPU variant\t: 0x1
CPU part\t: 0xd0c
CPU revision\t: 1

processor\t: 1
BogoMIPS\t: 243.75
CPU implementer\t: 0x41
CPU part\t: 0xd0c
"""

# HWCAP bits: ASIMD(1<<1) | FPHP(1<<9) | ASIMDDP(1<<20)
_GRAVITON2_HWCAP = (1 << 1) | (1 << 9) | (1 << 20)
_GRAVITON2_HWCAP2 = 0


def test_known_neoverse_part_is_named():
    report = read_chip_report(_GRAVITON2_CPUINFO, _GRAVITON2_HWCAP, _GRAVITON2_HWCAP2)
    assert report.chip_name == "Arm Neoverse N1"
    assert report.platform == "linux"


def test_core_counting_from_processor_lines():
    report = read_chip_report(_GRAVITON2_CPUINFO, _GRAVITON2_HWCAP, _GRAVITON2_HWCAP2)
    assert report.total_cores == 2
    assert report.p_cores == 2
    assert report.e_cores == 0


def test_hwcap_bits_map_to_isa_flags():
    report = read_chip_report(_GRAVITON2_CPUINFO, _GRAVITON2_HWCAP, _GRAVITON2_HWCAP2)
    assert report.isa["neon"] is True
    assert report.isa["fp16"] is True
    assert report.isa["dotprod"] is True
    assert report.isa["i8mm"] is False
    assert report.isa["sve"] is False
    assert report.isa["sme2"] is False


def test_sve2_i8mm_bf16_sme_sme2_bits():
    hwcap = 1 << 22  # SVE
    hwcap2 = (1 << 1) | (1 << 13) | (1 << 14) | (1 << 23) | (1 << 37)  # sve2,i8mm,bf16,sme,sme2
    report = read_chip_report("processor\t: 0\n", hwcap, hwcap2)
    assert report.isa["sve"] is True
    assert report.isa["sve2"] is True
    assert report.isa["i8mm"] is True
    assert report.isa["bf16"] is True
    assert report.isa["sme"] is True
    assert report.isa["sme2"] is True


def test_unknown_part_falls_back_to_generic_label():
    report = read_chip_report("processor\t: 0\nCPU implementer\t: 0x41\nCPU part\t: 0x999\n", 0, 0)
    assert "0x41" in report.chip_name
    assert "0x999" in report.chip_name


def test_missing_fields_default_gracefully():
    report = read_chip_report("", 0, 0)
    assert report.chip_name == "Unknown Arm CPU"
    assert report.total_cores == 0
    assert report.ram_gb == 0.0
    assert all(value is False for value in report.isa.values())
