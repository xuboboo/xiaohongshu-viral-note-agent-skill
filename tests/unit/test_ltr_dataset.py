"""LTR 指标回流：PublishedMetrics → 训练行。"""
from xhs_skill.operations.models import PublishedMetrics
from xhs_skill.ranking.features import FEATURE_ORDER
from datetime import UTC, datetime, timedelta

from xhs_skill.ranking.ltr_dataset import (
    engagement_score,
    feedback_weight,
    latest_metric_snapshots,
    metrics_to_ltr_rows,
    package_title_snapshot,
    relevance_label,
)


def test_engagement_and_label():
    m = PublishedMetrics(
        note_id="n1",
        account_id="a1",
        views=1000,
        likes=50,
        saves=20,
        comments=5,
        content_features={"topic": "防晒", "selected_title": "防晒怎么选"},
    )
    score = engagement_score(m)
    assert score > 0
    assert relevance_label(score) >= 1


def test_metrics_to_ltr_rows_feature_dim():
    rows_in = [
        PublishedMetrics(
            note_id="n1",
            account_id="a1",
            views=2000,
            likes=80,
            content_features={
                "topic": "空气炸锅",
                "selected_title": "空气炸锅怎么选不踩坑",
                "mechanism": "避坑",
                "title_candidates": "空气炸锅闭眼冲,上班族空气炸锅",
            },
        ),
        PublishedMetrics(
            note_id="n2",
            account_id="a1",
            views=100,
            likes=2,
            content_features={
                "topic": "空气炸锅",
                "selected_title": "空气炸锅随便买",
                "mechanism": "硬广",
            },
        ),
    ]
    rows = metrics_to_ltr_rows(rows_in)
    assert rows
    assert all(len(row["features"]) == len(FEATURE_ORDER) for row in rows)
    # 同 query 应有多行
    assert sum(1 for row in rows if row["query_id"] == "空气炸锅") >= 2
    # 合成负样本存在
    assert any(row.get("synthetic_negative") for row in rows)


def test_latest_snapshot_and_feedback_weight():
    now = datetime.now(UTC)
    early = PublishedMetrics(
        note_id="same",
        account_id="a1",
        snapshot_at=now - timedelta(hours=1),
        views=10,
        content_features={"topic": "防晒", "snapshot_delay_minutes": 60},
    )
    mature = early.model_copy(
        update={
            "snapshot_at": now,
            "views": 1000,
            "source": "AUTHORIZED_BROWSER",
            "content_features": {"topic": "防晒", "snapshot_delay_minutes": 1440},
        }
    )
    latest = latest_metric_snapshots([early, mature])
    assert latest == [mature]
    assert feedback_weight(mature) > feedback_weight(early)


def test_observed_title_not_emitted_as_synthetic_negative():
    metrics = [
        PublishedMetrics(
            note_id="n1",
            account_id="a1",
            views=1000,
            content_features={
                "topic": "防晒",
                "selected_title": "标题A",
                "title_candidates": "标题B,标题C",
            },
        ),
        PublishedMetrics(
            note_id="n2",
            account_id="a1",
            views=2000,
            content_features={"topic": "防晒", "selected_title": "标题B"},
        ),
    ]
    rows = metrics_to_ltr_rows(metrics)
    conflicts = [
        row
        for row in rows
        if row["title"] == "标题B" and row.get("synthetic_negative")
    ]
    assert conflicts == []
    assert all(float(row["sample_weight"]) > 0 for row in rows)


def test_package_title_snapshot():
    snap = package_title_snapshot(
        topic="防晒",
        selected_title="油皮防晒怎么选",
        mechanism="场景",
        title_candidates=["油皮防晒怎么选", "闭眼冲防晒"],
    )
    assert snap["topic"] == "防晒"
    assert "闭眼冲防晒" in snap["title_candidates"]