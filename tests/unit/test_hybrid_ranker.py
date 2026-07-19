"""RRF 多路融合与 Hybrid 标题排序单测。"""
from __future__ import annotations

from xhs_skill.ranking.features import FEATURE_ORDER, title_features
from xhs_skill.ranking.fusion import reciprocal_rank_fusion, rrf_order
from xhs_skill.ranking.hybrid import HybridTitleRanker
from xhs_skill.schemas.content import TitleCandidate


def test_rrf_prefers_cross_list_agreement():
    # A 在两路都靠前，应压过只在一路第一的 B
    scores = reciprocal_rank_fusion(
        [
            ["B", "A", "C"],
            ["A", "C", "B"],
        ],
        k=60,
    )
    assert scores["A"] > scores["B"]
    assert rrf_order([["B", "A"], ["A", "C"]])[0] == "A"


def test_rrf_weights():
    scores = reciprocal_rank_fusion(
        [["X", "Y"], ["Y", "X"]],
        k=10,
        weights=[2.0, 0.1],
    )
    assert scores["X"] > scores["Y"]


def test_feature_order_has_v2_signals():
    feats = title_features("空气炸锅怎么选？5个避坑点", "空气炸锅", "搜索决策")
    assert list(feats.keys()) == FEATURE_ORDER
    assert feats["hook_strength"] > 0.5
    assert feats["search_intent"] > 0.5
    assert feats["risk_penalty"] == 0.0


def test_hybrid_ranker_without_embeddings():
    candidates = [
        TitleCandidate(id="1", title="空气炸锅怎么选不踩坑", mechanism="避坑"),
        TitleCandidate(id="2", title="闭眼冲！最好空气炸锅", mechanism="硬广"),
        TitleCandidate(id="3", title="上班族空气炸锅真实场景", mechanism="场景"),
    ]
    ranker = HybridTitleRanker(rrf_k=60)
    ordered, fused, meta = ranker.rank(candidates, "空气炸锅", apply_mmr=True)
    assert len(ordered) == 3
    assert "rule" in meta["channels"]
    assert fused
    # 风险标题不应排第一
    assert ordered[0].id != "2"
    assert "rrf" in (ordered[0].scores or {})


def test_hybrid_with_semantic_vectors():
    candidates = [
        TitleCandidate(id="a", title="主题相关标题A", mechanism="m1"),
        TitleCandidate(id="b", title="完全无关噪声标题", mechanism="m2"),
    ]
    # 人为构造：topic 与 a 更近
    topic = [1.0, 0.0, 0.0]
    title_vectors = {
        "a": [0.9, 0.1, 0.0],
        "b": [0.0, 1.0, 0.0],
    }
    ranker = HybridTitleRanker()
    ordered, _, meta = ranker.rank(
        candidates,
        "主题",
        topic_vector=topic,
        title_vectors=title_vectors,
        apply_mmr=False,
    )
    assert meta["semantic_active"] is True
    assert ordered[0].id == "a"