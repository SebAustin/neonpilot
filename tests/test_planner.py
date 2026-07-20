"""Tests for search/planner.py: candidate sets for M1 Max / M5 / generic topologies."""

from __future__ import annotations

from neonpilot.models import SweepBudget
from neonpilot.probe.macos_sysctl import read_chip_report
from neonpilot.search.planner import plan

_BUDGET = SweepBudget(total_seconds=900, reps=3, prompt_n=512, gen_n=128)


def test_m1_max_stage_a_thread_candidates_match_plan_example(fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    search_plan = plan(chip, _BUDGET)
    assert [cfg.threads for cfg in search_plan.stage_a] == [6, 8, 9, 10]


def test_stage_a_defaults_other_flags_to_llama_cpp_defaults(fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    search_plan = plan(chip, _BUDGET)
    for cfg in search_plan.stage_a:
        assert cfg.cache_type_k == "f16"
        assert cfg.cache_type_v == "f16"
        assert cfg.flash_attn == "auto"
        assert cfg.batch == 2048
        assert cfg.ubatch == 512


def test_stage_b_has_six_fa_x_kv_combos(fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    search_plan = plan(chip, _BUDGET)
    combos = {(cfg.flash_attn, cfg.cache_type_k) for cfg in search_plan.stage_b}
    assert combos == {
        ("off", "f16"),
        ("off", "q8_0"),
        ("off", "q4_0"),
        ("on", "f16"),
        ("on", "q8_0"),
        ("on", "q4_0"),
    }
    assert len(search_plan.stage_b) == 6
    for cfg in search_plan.stage_b:
        assert cfg.cache_type_k == cfg.cache_type_v


def test_stage_c_has_three_batch_ubatch_pairs(fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    search_plan = plan(chip, _BUDGET)
    pairs = {(cfg.batch, cfg.ubatch) for cfg in search_plan.stage_c}
    assert pairs == {(2048, 512), (2048, 1024), (4096, 2048)}
    assert len(search_plan.stage_c) == 3


def test_baseline_is_none_meaning_llama_cpp_defaults(fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    search_plan = plan(chip, _BUDGET)
    assert search_plan.baseline is None


def test_notes_mention_each_stage(fixture_text):
    chip = read_chip_report(fixture_text("sysctl_apple_m1_max.txt"))
    search_plan = plan(chip, _BUDGET)
    joined = " ".join(search_plan.notes)
    assert "Stage A" in joined
    assert "Stage B" in joined
    assert "Stage C" in joined


def test_m5_synthetic_topology_thread_candidates(fixture_text):
    """M5 synthetic fixture: p_cores=10, total_cores=14 -> {10, 8, 14, 13} sorted."""
    chip = read_chip_report(fixture_text("sysctl_apple_m5_synthetic.txt"))
    search_plan = plan(chip, _BUDGET)
    assert [cfg.threads for cfg in search_plan.stage_a] == [8, 10, 13, 14]


def test_generic_homogeneous_topology_at_least_two_candidates():
    """Generic Linux/Graviton-like topology: p_cores == total_cores (no E-cores)."""
    from neonpilot.probe.linux_cpuinfo import read_chip_report as read_linux

    cpuinfo = "\n".join(f"processor\t: {i}" for i in range(4))
    chip = read_linux(cpuinfo, hwcap=0, hwcap2=0)
    search_plan = plan(chip, _BUDGET)
    assert len(search_plan.stage_a) >= 2
    assert all(cfg.threads >= 1 for cfg in search_plan.stage_a)


def test_single_core_topology_degrades_gracefully():
    from neonpilot.probe.linux_cpuinfo import read_chip_report as read_linux

    chip = read_linux("processor\t: 0\n", hwcap=0, hwcap2=0)
    search_plan = plan(chip, _BUDGET)
    assert len(search_plan.stage_a) >= 1
    assert all(cfg.threads >= 1 for cfg in search_plan.stage_a)
