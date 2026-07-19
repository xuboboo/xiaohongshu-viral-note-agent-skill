"""轻量趋势摘要记忆：同 query 跨次对比增速（非站内热榜）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xhs_skill.core.identifiers import atomic_write_private, private_mkdir, validate_identifier
from xhs_skill.schemas.research import HotNoteCandidate, TrendTopic


def snapshot_from_notes_trends(
    *,
    query: str,
    score_type: str,
    notes: list[HotNoteCandidate],
    trends: list[TrendTopic],
) -> dict[str, Any]:
    """压缩可对比摘要（不存全文）。"""
    note_scores = [float(n.hot_score or 0) for n in notes[:20]]
    mean_score = round(sum(note_scores) / len(note_scores), 3) if note_scores else 0.0
    top_ids = [n.id for n in notes[:8]]
    topic_map = {
        t.topic: {
            "score": float(t.score),
            "growth_rate": float(t.growth_rate),
            "saturation": float(t.saturation),
            "trend_class": str(t.trend_class),
            "gap": float(t.content_gap_score),
        }
        for t in trends[:20]
    }
    return {
        "query": query,
        "score_type": score_type,
        "as_of": datetime.now(UTC).isoformat(),
        "note_count": len(notes),
        "mean_hot_score": mean_score,
        "top_note_ids": top_ids,
        "topics": topic_map,
    }


def compare_snapshots(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """双轴：绝对分 + 相对上次增速；产出 rising_words / dual_axis。"""
    if not previous:
        return {
            "has_baseline": False,
            "as_of_prev": None,
            "mean_score_delta": None,
            "rising_words": [],
            "declining_words": [],
            "dual_axis": [],
            "note_id_churn": None,
            "hint": "首次记录趋势摘要，下次同 query 可算增速。",
        }

    cur_topics = current.get("topics") or {}
    prev_topics = previous.get("topics") or {}
    dual: list[dict[str, Any]] = []
    rising: list[dict[str, Any]] = []
    declining: list[dict[str, Any]] = []

    for topic, cur in cur_topics.items():
        prev = prev_topics.get(topic) or {}
        abs_score = float(cur.get("score") or 0)
        prev_score = float(prev.get("score") or 0) if prev else 0.0
        delta = abs_score - prev_score if prev else 0.0
        # 竞争代理：饱和度越高竞争越强
        sat = float(cur.get("saturation") or 0.5)
        opportunity = round(max(0.0, delta) * (1.0 - min(1.0, sat)), 4)
        row = {
            "topic": topic,
            "absolute_score": abs_score,
            "score_delta": round(delta, 3),
            "saturation": sat,
            "opportunity": opportunity,
            "trend_class": cur.get("trend_class"),
        }
        dual.append(row)
        if delta >= 5 or opportunity >= 3:
            rising.append(row)
        elif delta <= -5:
            declining.append(row)

    dual.sort(key=lambda r: (r["opportunity"], r["absolute_score"]), reverse=True)
    rising.sort(key=lambda r: r["opportunity"], reverse=True)
    declining.sort(key=lambda r: r["score_delta"])

    cur_ids = set(current.get("top_note_ids") or [])
    prev_ids = set(previous.get("top_note_ids") or [])
    churn = None
    if cur_ids or prev_ids:
        union = cur_ids | prev_ids
        churn = round(1.0 - (len(cur_ids & prev_ids) / max(len(union), 1)), 3)

    mean_delta = None
    if current.get("mean_hot_score") is not None and previous.get("mean_hot_score") is not None:
        mean_delta = round(
            float(current["mean_hot_score"]) - float(previous["mean_hot_score"]), 3
        )

    return {
        "has_baseline": True,
        "as_of_prev": previous.get("as_of"),
        "mean_score_delta": mean_delta,
        "rising_words": rising[:8],
        "declining_words": declining[:6],
        "dual_axis": dual[:12],
        "note_id_churn": churn,
        "hint": "增速来自本机/缓存趋势摘要对比，不是站内官方热词榜。",
    }


class TrendMemoryStore:
    """本地文件趋势摘要（可与 Cache 并存；不提交用户数据）。"""

    def __init__(self, root: str | Path = "./data/trend_memory") -> None:
        self.root = private_mkdir(root)

    def _path(self, query: str) -> Path:
        # 用 hash 避免路径注入；query 仅作展示存在文件内容
        import hashlib

        digest = hashlib.sha256(query.strip().casefold().encode("utf-8")).hexdigest()[:32]
        validate_identifier(digest, field="trend_key")
        return self.root / f"{digest}.json"

    def load(self, query: str) -> dict[str, Any] | None:
        path = self._path(query)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, snapshot: dict[str, Any]) -> None:
        query = str(snapshot.get("query") or "").strip()
        if not query:
            return
        path = self._path(query)
        atomic_write_private(path, json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8"))


def apply_trend_memory(
    *,
    query: str,
    score_type: str,
    notes: list[HotNoteCandidate],
    trends: list[TrendTopic],
    store: TrendMemoryStore | None = None,
) -> dict[str, Any]:
    """读旧摘要 → 对比 → 写新摘要。"""
    store = store or TrendMemoryStore()
    current = snapshot_from_notes_trends(
        query=query, score_type=score_type, notes=notes, trends=trends
    )
    previous = store.load(query)
    comparison = compare_snapshots(current, previous)
    store.save(current)
    return {
        "snapshot": {
            "as_of": current["as_of"],
            "score_type": score_type,
            "mean_hot_score": current["mean_hot_score"],
            "note_count": current["note_count"],
        },
        "comparison": comparison,
    }