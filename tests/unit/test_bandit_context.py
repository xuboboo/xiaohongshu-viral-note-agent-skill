"""Bandit 上下文特征工程。"""
from xhs_skill.operations.bandit_context import (
    BANDIT_CONTEXT_DIM,
    BANDIT_CONTEXT_NAMES,
    build_bandit_context,
    describe_bandit_context,
)


def test_context_dim_stable():
    vec = build_bandit_context(
        {
            "account_weight": 72,
            "hour": 21,
            "weekday": 5,
            "category": "美妆",
            "format": "graphic",
            "objective": "search_growth",
        }
    )
    assert len(vec) == BANDIT_CONTEXT_DIM
    assert vec[0] == 1.0  # bias
    assert vec[6] == 1.0  # weekend
    assert vec[7] == 1.0  # graphic
    named = describe_bandit_context(vec)
    assert set(named) == set(BANDIT_CONTEXT_NAMES)


def test_default_context():
    vec = build_bandit_context()
    assert len(vec) == BANDIT_CONTEXT_DIM
    assert abs(vec[5] - 0.5) < 1e-6  # missing weight → 0.5


def test_category_hash_deterministic():
    a = build_bandit_context({"category": "数码"})
    b = build_bandit_context({"category": "数码"})
    c = build_bandit_context({"category": "美食"})
    assert a[-1] == b[-1]
    assert a[-1] != c[-1]