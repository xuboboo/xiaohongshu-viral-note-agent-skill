from __future__ import annotations

import statistics

from xhs_skill.operations.models import (
    AttributionContribution,
    PerformanceAttribution,
    PublishedMetrics,
)


def _engagement(metrics: PublishedMetrics) -> float:
    if not metrics.views:
        return float((metrics.likes or 0) + 2 * (metrics.saves or 0) + 2 * (metrics.shares or 0))
    weighted = (
        0.15 * (metrics.likes or 0)
        + 0.35 * (metrics.saves or 0)
        + 0.20 * (metrics.comments or 0)
        + 0.30 * (metrics.shares or 0)
    )
    return weighted / max(metrics.views, 1)


def attribute_performance(
    target: PublishedMetrics,
    history: list[PublishedMetrics],
    *,
    primary_metric: str = "engagement_rate",
) -> PerformanceAttribution:
    peer = [item for item in history if item.note_id != target.note_id]
    metric_value = _engagement(target)
    baseline = statistics.median([_engagement(item) for item in peer]) if peer else metric_value
    lift = metric_value - baseline
    contributions: list[AttributionContribution] = []
    numeric_features = {
        key: float(value)
        for key, value in target.content_features.items()
        if isinstance(value, (int, float, bool))
    }
    for feature, value in numeric_features.items():
        peer_values = [
            float(item.content_features[feature])
            for item in peer
            if feature in item.content_features
            and isinstance(item.content_features[feature], (int, float, bool))
        ]
        if not peer_values:
            continue
        center = statistics.fmean(peer_values)
        spread = statistics.pstdev(peer_values) or 1.0
        standardized = (value - center) / spread
        contribution = standardized * lift / max(1, len(numeric_features))
        contributions.append(
            AttributionContribution(
                feature=feature,
                contribution=round(contribution, 6),
                direction="POSITIVE" if contribution >= 0 else "NEGATIVE",
                confidence=min(0.9, len(peer_values) / 20),
                explanation=(
                    f"该特征相对历史均值偏离 {standardized:.2f} 个标准差，"
                    "贡献为相关性估计，不代表因果。"
                ),
            )
        )
    contributions.sort(key=lambda item: abs(item.contribution), reverse=True)
    return PerformanceAttribution(
        note_id=target.note_id,
        account_id=target.account_id,
        primary_metric=primary_metric,
        metric_value=round(metric_value, 8),
        baseline_value=round(baseline, 8),
        lift=round(lift, 8),
        contributions=contributions,
    )
