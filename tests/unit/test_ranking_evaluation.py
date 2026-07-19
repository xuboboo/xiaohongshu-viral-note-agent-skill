"""LTR 离线评估单测。"""
from xhs_skill.ranking.evaluation import (
    dcg_at_k,
    evaluate_candidate,
    mean_query_ndcg,
    ndcg_at_k,
    split_rows_by_query,
)


def _row(query: str, relevance: float, first_feature: float = 0.5) -> dict:
    features = [0.5] * 10
    features[0] = first_feature
    return {
        "query_id": query,
        "relevance": relevance,
        "features": features,
    }


def test_ndcg_perfect_and_reversed():
    labels = [3.0, 2.0, 0.0]
    assert ndcg_at_k(labels, [3.0, 2.0, 0.0], k=3) == 1.0
    assert ndcg_at_k(labels, [0.0, 2.0, 3.0], k=3) < 1.0
    assert dcg_at_k(labels, 3) > 0


def test_query_split_has_no_leakage():
    rows = [_row(f"q{i}", float(i % 4)) for i in range(12)]
    train, validation = split_rows_by_query(rows, validation_fraction=0.25)
    train_queries = {row["query_id"] for row in train}
    valid_queries = {row["query_id"] for row in validation}
    assert train_queries
    assert valid_queries
    assert train_queries.isdisjoint(valid_queries)


def test_mean_query_ndcg_equal_weights_queries():
    rows = [
        _row("a", 3.0),
        _row("a", 0.0),
        _row("b", 0.0),
        _row("b", 3.0),
    ]
    score = mean_query_ndcg(rows, [1.0, 0.0, 0.0, 1.0], k=2)
    assert score == 1.0


def test_candidate_promotion_report():
    rows = [
        _row("a", 3.0),
        _row("a", 0.0),
        _row("b", 2.0),
        _row("b", 0.0),
    ]
    report = evaluate_candidate(rows, [1.0, 0.0, 1.0, 0.0], k=2)
    assert report["queries"] == 2
    assert report["ndcg_at_k"] == 1.0
    assert isinstance(report["promotion_recommended"], bool)