from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from xhs_skill.schemas.research import HotNoteCandidate, ScoreType


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [0.5 for _ in values]
    return [(value - low) / (high - low) for value in values]


def query_relevance(query: str, note: HotNoteCandidate) -> float:
    """中英混合相关分：整词命中 + 标题前置加权。"""

    raw = (query or "").strip()
    if not raw:
        return 0.5
    terms = [term for term in re.split(r"\s+", raw.lower()) if term]
    # 中文无空格：补 2–3 字片段
    compact = re.sub(r"\s+", "", raw)
    if len(compact) >= 2 and not re.search(r"[A-Za-z]{3,}", compact):
        for size in (3, 2):
            for i in range(0, len(compact) - size + 1):
                terms.append(compact[i : i + size].lower())
    terms = list(dict.fromkeys(terms))[:16]
    title = (note.title or "").lower()
    haystack = f"{title} {note.snippet or ''} {note.body or ''}".lower()
    if not terms:
        return 0.5
    hits = sum(1 for term in terms if term in haystack)
    base = min(1.0, hits / max(len(terms), 1) * 1.4)
    # 标题前 12 字命中核心片段
    head = title[:12]
    front = 0.15 if any(t in head for t in terms if len(t) >= 2) else 0.0
    return min(1.0, base + front)


def rank_hot_notes(
    notes: list[HotNoteCandidate],
    query: str,
    *,
    half_life_hours: float = 72.0,
) -> tuple[ScoreType, list[HotNoteCandidate]]:
    has_metrics = any(
        any(value is not None for value in (n.likes, n.saves, n.comments, n.shares)) for n in notes
    )
    now = datetime.now(UTC)

    engagements: list[float] = []
    velocities: list[float] = []
    creator_norms: list[float] = []
    freshnesses: list[float] = []
    relevances: list[float] = []
    search_ranks: list[float] = []

    for note in notes:
        engagement = (
            # 公开营销文常强调：收藏/评论/分享权重高于纯点赞（非官方 CES）
            0.10 * math.log1p(note.likes or 0)
            + 0.35 * math.log1p(note.saves or 0)
            + 0.30 * math.log1p(note.comments or 0)
            + 0.25 * math.log1p(note.shares or 0)
        )
        age_hours = max(
            1.0,
            ((now - note.published_at).total_seconds() / 3600)
            if note.published_at
            else half_life_hours * 2,
        )
        freshness = math.exp(-age_hours / half_life_hours)
        engagements.append(engagement)
        velocities.append(engagement / max(age_hours, 6))
        creator_norms.append(engagement / math.log(10 + (note.followers or 0)))
        freshnesses.append(freshness)
        relevances.append(query_relevance(query, note))
        search_ranks.append(1 / max(note.source_rank or len(notes), 1))

    norm_engagement = _normalize(engagements)
    norm_velocity = _normalize(velocities)
    norm_creator = _normalize(creator_norms)
    norm_rank = _normalize(search_ranks)
    score_type = ScoreType.METRIC_HOT_SCORE if has_metrics else ScoreType.PUBLIC_INDEX_HOT_SCORE

    for index, note in enumerate(notes):
        if score_type == ScoreType.METRIC_HOT_SCORE:
            components = {
                "engagement": 0.28 * norm_engagement[index],
                "velocity": 0.22 * norm_velocity[index],
                "creator_normalized": 0.12 * norm_creator[index],
                "freshness": 0.15 * freshnesses[index],
                "relevance": 0.18 * relevances[index],  # 搜索意图匹配加权
                "source_support": 0.05 * note.data_confidence,
            }
        else:
            components = {
                "search_rank": 0.25 * norm_rank[index],
                "relevance": 0.32 * relevances[index],  # 公开索引更重语义相关
                "freshness": 0.18 * freshnesses[index],
                "cross_engine_support": 0.15 * note.data_confidence,
                "source_confidence": 0.10 * note.data_confidence,
            }
        note.score_type = score_type
        note.score_components = {key: round(value, 6) for key, value in components.items()}
        note.hot_score = round(sum(components.values()) * 100, 4)

    return score_type, sorted(notes, key=lambda item: item.hot_score or 0, reverse=True)
