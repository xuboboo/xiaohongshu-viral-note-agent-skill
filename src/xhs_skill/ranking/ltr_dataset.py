"""发后指标 → LambdaMART 训练行（query 分组 + 特征 + 相关性标签）。

约定 content_features 可携带：
- topic / primary_keyword
- selected_title / title
- mechanism
- title_candidates: 逗号分隔或 JSON 列表（同 query 负样本/对照）

无标题时用 note_id 占位，保证流水线可跑但质量较低。
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from xhs_skill.operations.models import PublishedMetrics
from xhs_skill.ranking.features import FEATURE_ORDER, title_features
from xhs_skill.schemas.content import TitleCandidate


def engagement_score(metrics: PublishedMetrics) -> float:
    """可解释的互动强度（非因果）。"""
    views = float(metrics.views or 0)
    likes = float(metrics.likes or 0)
    saves = float(metrics.saves or 0)
    comments = float(metrics.comments or 0)
    shares = float(metrics.shares or 0)
    follows = float(metrics.follows or 0)
    interactions = likes + 1.5 * saves + 2.0 * comments + 1.2 * shares + 3.0 * follows
    if views <= 0:
        return interactions
    # log1p(views) 平滑曝光，乘以互动率
    rate = interactions / max(views, 1.0)
    return math.log1p(views) * (1.0 + 10.0 * rate)


def feedback_weight(metrics: PublishedMetrics) -> float:
    """训练样本置信权重，避免低曝光/过早快照主导模型。

    若发布链路记录了 selection_propensity，则做截断 IPW；没有 propensity 时不伪造。
    """
    features = metrics.content_features or {}
    views = max(0.0, float(metrics.views or 0))
    exposure_confidence = min(1.0, math.log1p(views) / math.log1p(10_000))
    delay_minutes = max(0.0, float(features.get("snapshot_delay_minutes") or 0.0))
    maturity = min(1.0, max(0.2, delay_minutes / 1440.0)) if delay_minutes else 0.6
    source_confidence = 1.0 if metrics.source == "AUTHORIZED_BROWSER" else 0.85
    weight = max(0.1, exposure_confidence * maturity * source_confidence)

    propensity = features.get("selection_propensity")
    if isinstance(propensity, (int, float)) and 0 < float(propensity) <= 1:
        # 截断 IPW，避免极小 propensity 造成方差爆炸。
        weight *= min(3.0, 1.0 / max(0.1, float(propensity)))
    return round(min(3.0, weight), 6)


def latest_metric_snapshots(
    metrics_list: Iterable[PublishedMetrics],
) -> list[PublishedMetrics]:
    """每个 tenant/account/note 仅保留最新快照，防止 T+1/24/72 重复泄漏。"""
    latest: dict[tuple[str, str, str], PublishedMetrics] = {}
    for metrics in metrics_list:
        key = (metrics.tenant_id, metrics.account_id, metrics.note_id)
        current = latest.get(key)
        if current is None or metrics.snapshot_at > current.snapshot_at:
            latest[key] = metrics
    return sorted(
        latest.values(),
        key=lambda item: (item.tenant_id, item.account_id, item.note_id),
    )


def relevance_label(score: float, *, peers: Sequence[float] | None = None) -> float:
    """映射到 0–4 的 lambdarank 标签。

    有同 query 同伴时用分位数；否则用绝对阈值。
    """
    if peers and len(peers) >= 2:
        ordered = sorted(peers)
        # 相对位置 0..1
        rank = sum(1 for value in ordered if value <= score) / len(ordered)
        if rank >= 0.9:
            return 4.0
        if rank >= 0.7:
            return 3.0
        if rank >= 0.45:
            return 2.0
        if rank >= 0.2:
            return 1.0
        return 0.0
    if score >= 12:
        return 4.0
    if score >= 7:
        return 3.0
    if score >= 3.5:
        return 2.0
    if score >= 1.0:
        return 1.0
    return 0.0


def _feature_list(title: str, keyword: str, mechanism: str) -> list[float]:
    feats = title_features(title, keyword, mechanism)
    return [float(feats[name]) for name in FEATURE_ORDER]


def _parse_candidates(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in text.split(",") if part.strip()]


def metrics_to_ltr_rows(
    metrics_list: Iterable[PublishedMetrics],
    *,
    min_group_size: int = 1,
) -> list[dict[str, Any]]:
    """从发布指标构造 JSONL 训练行。

    每行: {query_id, relevance, features, title, note_id, engagement}
    """
    items = latest_metric_snapshots(metrics_list)
    # 先算 engagement，再按 query 分组定标签
    prepared: list[dict[str, Any]] = []
    for metrics in items:
        features = metrics.content_features or {}
        topic = str(features.get("topic") or features.get("primary_keyword") or "unknown")
        title = str(
            features.get("selected_title")
            or features.get("title")
            or metrics.note_id
        )
        mechanism = str(features.get("mechanism") or features.get("content_angle") or "")
        eng = engagement_score(metrics)
        prepared.append(
            {
                "query_id": topic,
                "title": title,
                "mechanism": mechanism,
                "keyword": topic,
                "note_id": metrics.note_id,
                "account_id": metrics.account_id,
                "engagement": eng,
                "sample_weight": feedback_weight(metrics),
                "snapshot_at": metrics.snapshot_at.isoformat(),
                "features": _feature_list(title, topic, mechanism),
                "extra_titles": _parse_candidates(features.get("title_candidates")),
            }
        )

    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        by_query[row["query_id"]].append(row)

    rows: list[dict[str, Any]] = []
    for query_id, group in by_query.items():
        if len(group) < min_group_size:
            continue
        peers = [item["engagement"] for item in group]
        observed_titles = {str(item["title"]).strip() for item in group}
        emitted_synthetic: set[str] = set()
        for item in group:
            label = relevance_label(item["engagement"], peers=peers)
            rows.append(
                {
                    "query_id": query_id,
                    "relevance": label,
                    "features": item["features"],
                    "title": item["title"],
                    "mechanism": item["mechanism"],
                    "note_id": item["note_id"],
                    "account_id": item["account_id"],
                    "engagement": round(item["engagement"], 6),
                    "sample_weight": item["sample_weight"],
                    "snapshot_at": item["snapshot_at"],
                    "feedback_kind": "observed",
                }
            )
            # 对照候选：同 query 的未发表标题当弱负样本（relevance 0）
            for alt in item["extra_titles"][:4]:
                # 真实发布过的标题绝不能再标为负样本；同 query 合成负样本只发一次。
                if alt in observed_titles or alt in emitted_synthetic:
                    continue
                emitted_synthetic.add(alt)
                rows.append(
                    {
                        "query_id": query_id,
                        "relevance": 0.0,
                        "features": _feature_list(alt, item["keyword"], item["mechanism"]),
                        "title": alt,
                        "mechanism": item["mechanism"],
                        "note_id": f"{item['note_id']}:candidate",
                        "account_id": item["account_id"],
                        "engagement": 0.0,
                        "sample_weight": 0.25,
                        "feedback_kind": "synthetic_negative",
                        "synthetic_negative": True,
                    }
                )
    # lambdarank 要求同 query 连续；排序稳定
    rows.sort(key=lambda row: (row["query_id"], -float(row["relevance"]), row["title"]))
    return rows


def write_ltr_jsonl(rows: Sequence[dict[str, Any]], path: str) -> int:
    from pathlib import Path

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def package_title_snapshot(
    *,
    topic: str,
    selected_title: str,
    mechanism: str = "",
    title_candidates: Sequence[TitleCandidate] | Sequence[str] = (),
) -> dict[str, str]:
    """发布前写入 metrics.content_features 的标准字段。"""
    titles: list[str] = []
    for item in title_candidates:
        if isinstance(item, TitleCandidate):
            titles.append(item.title)
        else:
            titles.append(str(item))
    return {
        "topic": topic,
        "selected_title": selected_title,
        "mechanism": mechanism,
        "title_candidates": ",".join(titles[:12]),
    }