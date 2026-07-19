"""早期爆发信号：授权互动速度启发式（非官方热榜）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from xhs_skill.schemas.research import HotNoteCandidate


def early_viral_signals(
    notes: list[HotNoteCandidate],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """当笔记有互动+发布时间时，估算早期速度分。"""
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for note in notes:
        likes = note.likes
        saves = note.saves
        comments = note.comments
        if likes is None and saves is None and comments is None:
            continue
        published = note.published_at or note.indexed_at
        if published is None:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        age_hours = max((now - published.astimezone(UTC)).total_seconds() / 3600.0, 0.5)
        eng = float(likes or 0) + 2.0 * float(saves or 0) + 1.5 * float(comments or 0)
        velocity = eng / age_hours
        # 早期窗口加权：越新越高
        early_boost = 1.4 if age_hours <= 24 else (1.1 if age_hours <= 72 else 0.85)
        signal = round(velocity * early_boost, 3)
        if signal < 0.5:
            continue
        rows.append(
            {
                "note_id": note.id,
                "title": note.title,
                "age_hours": round(age_hours, 2),
                "engagement_proxy": round(eng, 2),
                "velocity": round(velocity, 3),
                "early_signal_score": signal,
                "band": "early_hot" if signal >= 5 else "warming",
            }
        )
    rows.sort(key=lambda r: r["early_signal_score"], reverse=True)
    return rows[:limit]