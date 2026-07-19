"""Learning-to-rank 离线评估：query 级切分、NDCG 与候选晋级判断。"""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Sequence
from typing import Any


def dcg_at_k(relevances: Sequence[float], k: int = 5) -> float:
    """Discounted cumulative gain，输入按预测顺序排列。"""
    if k < 1:
        raise ValueError("k must be >= 1")
    total = 0.0
    for index, relevance in enumerate(relevances[:k], start=1):
        gain = (2.0 ** max(0.0, float(relevance))) - 1.0
        total += gain / math.log2(index + 1)
    return total


def ndcg_at_k(labels: Sequence[float], scores: Sequence[float], k: int = 5) -> float:
    """Normalized DCG；无正标签时返回 0。"""
    if len(labels) != len(scores):
        raise ValueError("labels and scores length mismatch")
    predicted = [
        label
        for _, label in sorted(
            zip(scores, labels, strict=True), key=lambda item: item[0], reverse=True
        )
    ]
    ideal = sorted((float(item) for item in labels), reverse=True)
    denominator = dcg_at_k(ideal, k)
    if denominator <= 0:
        return 0.0
    return round(dcg_at_k(predicted, k) / denominator, 8)


def split_rows_by_query(
    rows: Sequence[dict[str, Any]],
    *,
    validation_fraction: float = 0.2,
    seed: str = "xhs-ltr-v2",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 query_id 稳定切分，避免同 query 泄漏到 train/validation。"""
    if not 0 <= validation_fraction < 1:
        raise ValueError("validation_fraction must be in [0, 1)")
    query_ids = sorted({str(row["query_id"]) for row in rows})
    if validation_fraction == 0 or len(query_ids) < 3:
        return list(rows), []

    validation_queries: set[str] = set()
    for query_id in query_ids:
        digest = hashlib.sha256(f"{seed}:{query_id}".encode()).digest()
        point = int.from_bytes(digest[:8], "big") / 2**64
        if point < validation_fraction:
            validation_queries.add(query_id)
    # 保证两侧均有 query。
    if not validation_queries:
        validation_queries.add(query_ids[-1])
    if len(validation_queries) == len(query_ids):
        validation_queries.remove(query_ids[0])

    train = [row for row in rows if str(row["query_id"]) not in validation_queries]
    validation = [row for row in rows if str(row["query_id"]) in validation_queries]
    return train, validation


def mean_query_ndcg(
    rows: Sequence[dict[str, Any]],
    scores: Sequence[float],
    *,
    k: int = 5,
) -> float:
    """按 query 等权平均，避免大 query 支配结果。"""
    if len(rows) != len(scores):
        raise ValueError("rows and scores length mismatch")
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        grouped[str(row["query_id"])].append((float(row["relevance"]), float(score)))
    values = [
        ndcg_at_k(
            [item[0] for item in pairs],
            [item[1] for item in pairs],
            k=k,
        )
        for pairs in grouped.values()
        if len(pairs) >= 2
    ]
    return round(sum(values) / len(values), 8) if values else 0.0


def rule_score_from_features(features: Sequence[float]) -> float:
    """与 ranking.features.score_title 对齐的可审计规则基线。"""
    values = list(map(float, features))
    if len(values) < 10:
        return 0.0
    return (
        0.18 * values[0]
        + 0.18 * values[1]
        + 0.10 * values[2]
        + 0.12 * values[3]
        + 0.10 * values[4]
        - 0.45 * values[5]
        + 0.12 * values[6]
        + 0.12 * values[7]
        + 0.08 * values[8]
        - 0.25 * values[9]
    )


def evaluate_candidate(
    rows: Sequence[dict[str, Any]],
    predictions: Sequence[float],
    *,
    k: int = 5,
    minimum_ndcg_lift: float = 0.0,
) -> dict[str, float | bool | int]:
    """候选模型对比规则基线；只有 NDCG 不退化才建议晋级。"""
    baseline_scores = [rule_score_from_features(row["features"]) for row in rows]
    candidate_ndcg = mean_query_ndcg(rows, predictions, k=k)
    baseline_ndcg = mean_query_ndcg(rows, baseline_scores, k=k)
    lift = round(candidate_ndcg - baseline_ndcg, 8)
    return {
        "queries": len({str(row["query_id"]) for row in rows}),
        "rows": len(rows),
        "ndcg_at_k": candidate_ndcg,
        "baseline_ndcg_at_k": baseline_ndcg,
        "ndcg_lift": lift,
        "promotion_recommended": lift >= minimum_ndcg_lift,
    }