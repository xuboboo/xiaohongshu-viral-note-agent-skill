"""Bandit 选择策略：greedy_ucb / boltzmann。"""
from xhs_skill.operations.bandit_policy import boltzmann_sample, select_arm


def test_greedy_ucb_picks_max():
    arms = [("low", 0.1, 0.0), ("high", 0.9, 0.1), ("mid", 0.5, 0.0)]
    arm, score, _ = select_arm(
        arms,
        strategy="greedy_ucb",
        temperature=0.35,
        seed_material="t:p:s",
    )
    assert arm == "high"
    assert score == 0.9


def test_boltzmann_is_deterministic_for_seed():
    arms = [("a", 1.0, 0.2), ("b", 0.8, 0.3), ("c", 0.5, 0.1)]
    first = boltzmann_sample(arms, temperature=0.5, seed_material="seed-1")
    second = boltzmann_sample(arms, temperature=0.5, seed_material="seed-1")
    assert first == second
    other = boltzmann_sample(arms, temperature=0.5, seed_material="seed-2")
    # 不同 seed 可能相同，但函数应可调用；至少结构完整
    assert other[0] in {"a", "b", "c"}


def test_zero_temperature_is_greedy():
    arms = [("a", 0.2, 0.0), ("b", 0.9, 0.1)]
    arm, _, _ = boltzmann_sample(arms, temperature=0.0, seed_material="x")
    assert arm == "b"