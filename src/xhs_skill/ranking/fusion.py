"""多路排序融合：Reciprocal Rank Fusion（生产 hybrid search 主流范式）。

参考：Azure AI Search / OpenSearch RRF — 将规则分、学习排序、语义相关等多列表
融合成单一排序，避免分数尺度不可比问题。
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> dict[str, float]:
    """对多个「已按优→劣排序」的 id 列表做 RRF。

    score(d) = Σ_i weight_i / (k + rank_i(d))
    rank 从 1 开始；未出现在某列表中的文档不贡献该项。
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    if not ranked_lists:
        return {}
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    if len(weights) != len(ranked_lists):
        raise ValueError("weights length must match ranked_lists")

    scores: dict[str, float] = defaultdict(float)
    for weight, ranking in zip(weights, ranked_lists, strict=True):
        if weight == 0:
            continue
        seen: set[str] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            scores[doc_id] += float(weight) / (k + rank)
    return dict(scores)


def rrf_order(
    ranked_lists: Sequence[Sequence[str]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[str]:
    """返回按 RRF 分数从高到低的 id 列表。"""
    scores = reciprocal_rank_fusion(ranked_lists, k=k, weights=weights)
    return sorted(scores.keys(), key=lambda item: scores[item], reverse=True)