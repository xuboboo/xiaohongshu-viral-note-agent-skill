"""上下文 bandit 选择策略：LinUCB + Boltzmann 探索（2025 仍常用生产组合）。

- greedy_ucb：经典 argmax(μ + α·σ)
- boltzmann：在 UCB 分数上做温度 softmax，避免过度 exploitation，适合内容机制探索
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence


def boltzmann_sample(
    arm_scores: Sequence[tuple[str, float, float]],
    *,
    temperature: float,
    seed_material: str,
) -> tuple[str, float, float]:
    """从 (arm, score, exploration) 中按 softmax(score/T) 采样。

    temperature→0 逼近 greedy；temperature 大则更均匀探索。
    """
    if not arm_scores:
        raise ValueError("arm_scores cannot be empty")
    if temperature <= 0:
        # 退化为 greedy + 确定性平局打破
        max_score = max(item[1] for item in arm_scores)
        candidates = [
            item for item in arm_scores if math.isclose(item[1], max_score, rel_tol=1e-12)
        ]
        digest = hashlib.sha256(seed_material.encode()).digest()
        return candidates[int.from_bytes(digest[:8], "big") % len(candidates)]

    # 数值稳定 softmax
    scaled = [item[1] / temperature for item in arm_scores]
    peak = max(scaled)
    exps = [math.exp(value - peak) for value in scaled]
    total = sum(exps) or 1.0
    probs = [value / total for value in exps]

    digest = hashlib.sha256(seed_material.encode()).digest()
    point = int.from_bytes(digest[:8], "big") / 2**64
    cumulative = 0.0
    for index, prob in enumerate(probs):
        cumulative += prob
        if point < cumulative:
            return arm_scores[index]
    return arm_scores[-1]


def select_arm(
    arm_scores: Sequence[tuple[str, float, float]],
    *,
    strategy: str,
    temperature: float,
    seed_material: str,
) -> tuple[str, float, float]:
    """统一选择入口。strategy: greedy_ucb | boltzmann。"""
    mode = (strategy or "greedy_ucb").strip().lower()
    if mode in {"boltzmann", "softmax", "soft"}:
        return boltzmann_sample(
            arm_scores, temperature=temperature, seed_material=seed_material
        )
    # default greedy_ucb
    max_score = max(item[1] for item in arm_scores)
    candidates = [
        item for item in arm_scores if math.isclose(item[1], max_score, rel_tol=1e-12)
    ]
    digest = hashlib.sha256(seed_material.encode()).digest()
    return candidates[int.from_bytes(digest[:8], "big") % len(candidates)]