"""同 query 搜索质量记忆：驱动扩词深度、重试与 needs_web_search 建议。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xhs_skill.core.identifiers import atomic_write_private, private_mkdir, validate_identifier


def _query_key(query: str) -> str:
    digest = hashlib.sha256(query.strip().casefold().encode("utf-8")).hexdigest()[:32]
    validate_identifier(digest, field="search_quality_key")
    return digest


class SearchQualityMemory:
    """本地文件：上次同 query 的 search_quality 摘要（不进 git）。"""

    def __init__(self, root: str | Path = "./data/search_quality") -> None:
        self.root = private_mkdir(root)

    def _path(self, query: str) -> Path:
        return self.root / f"{_query_key(query)}.json"

    def load(self, query: str) -> dict[str, Any] | None:
        path = self._path(query)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, query: str, quality: dict[str, Any], *, note_count: int = 0) -> None:
        if not (query or "").strip():
            return
        payload = {
            "query": query.strip(),
            "as_of": datetime.now(UTC).isoformat(),
            "score": float(quality.get("score") or 0),
            "label": str(quality.get("label") or "unknown"),
            "recommendations": list(quality.get("recommendations") or [])[:6],
            "metrics": quality.get("metrics") or {},
            "note_count": int(note_count),
            "cache_ttl_multiplier": float(quality.get("cache_ttl_multiplier") or 1.0),
        }
        atomic_write_private(
            self._path(query),
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )


def plan_search_strategy(
    previous: dict[str, Any] | None,
    *,
    default_max_variants: int = 6,
    default_live_retries: int = 2,
    registered_live: list[str] | None = None,
) -> dict[str, Any]:
    """根据上次质量给出本次扩词/重试/TTL/provider 策略。"""
    live = list(registered_live or [])
    if not previous:
        return {
            "has_baseline": False,
            "max_variants": default_max_variants,
            "variant_cap": 5,
            "live_retries": default_live_retries,
            "ttl_multiplier_boost": 1.0,
            "prefer_crowd_angles": False,
            "force_site_queries": False,
            "prefer_multi_provider": False,
            "max_live_providers": max(1, len(live)) if live else 1,
            "provider_priority": live,
            "reason": "首次检索，使用默认策略。",
            "previous": None,
        }

    label = str(previous.get("label") or "fair")
    score = float(previous.get("score") or 50)
    recs = list(previous.get("recommendations") or [])
    metrics = previous.get("metrics") or {}
    last_sources = [
        str(s) for s in (metrics.get("unique_sources") or []) if s and s != "client_web"
    ]

    max_variants = default_max_variants
    variant_cap = 5
    live_retries = default_live_retries
    ttl_boost = 1.0
    prefer_crowd = False
    force_site = False
    prefer_multi = False
    max_live = max(1, min(2, len(live))) if live else 1
    reasons: list[str] = []

    if label in {"poor", "empty"} or score < 40:
        max_variants = min(12, default_max_variants + 4)
        variant_cap = 7
        live_retries = max(default_live_retries, 3)
        ttl_boost = 0.5
        prefer_crowd = True
        force_site = True
        prefer_multi = True
        max_live = max(1, len(live))  # 用尽可用 live 源
        reasons.append(f"上次质量 {score:.0f}（{label}），加深扩词与重试，并尽量多源。")
    elif label == "fair" or score < 70:
        max_variants = min(10, default_max_variants + 2)
        variant_cap = 6
        live_retries = default_live_retries
        prefer_crowd = True
        prefer_multi = float(metrics.get("source_diversity") or 1) < 0.5
        max_live = max(2, min(3, len(live))) if prefer_multi and live else max(1, min(2, len(live)))
        reasons.append(f"上次质量 {score:.0f}（{label}），适度加深扩词。")
    else:
        max_variants = max(4, default_max_variants - 1)
        variant_cap = 4
        live_retries = max(1, default_live_retries - 1)
        ttl_boost = 1.2
        max_live = 1 if live else 1
        reasons.append(f"上次质量 {score:.0f}（{label}），收敛扩词、拉长缓存。")

    if float(metrics.get("freshness_72h") or 1) < 0.3:
        force_site = True
        reasons.append("上次结果偏旧，优先 site 限定与时新变体。")
    if float(metrics.get("source_diversity") or 1) < 0.4:
        max_variants = min(12, max_variants + 1)
        prefer_multi = True
        max_live = max(max_live, min(len(live), 3)) if live else max_live
        reasons.append("上次来源单一，增加变体与多源覆盖。")
    if float(metrics.get("metric_coverage") or 1) < 0.2:
        prefer_crowd = True

    # provider 优先级：上次未出现的 live 源排前（探索），已出现的置后（避免重复偏斜）
    provider_priority = _prioritize_providers(live, last_sources, prefer_multi=prefer_multi)

    return {
        "has_baseline": True,
        "max_variants": max_variants,
        "variant_cap": variant_cap,
        "live_retries": live_retries,
        "ttl_multiplier_boost": ttl_boost,
        "prefer_crowd_angles": prefer_crowd,
        "force_site_queries": force_site,
        "prefer_multi_provider": prefer_multi,
        "max_live_providers": max(1, max_live) if live else 0,
        "provider_priority": provider_priority,
        "reason": " ".join(reasons) or "沿用默认策略。",
        "previous": {
            "score": score,
            "label": label,
            "as_of": previous.get("as_of"),
            "note_count": previous.get("note_count"),
            "recommendations": recs[:4],
            "unique_sources": last_sources[:8],
        },
    }


def _prioritize_providers(
    live: list[str],
    last_sources: list[str],
    *,
    prefer_multi: bool,
) -> list[str]:
    if not live:
        return []
    last_set = set(last_sources)
    # 探索：上次没用过的 live 源优先
    unexplored = [p for p in live if p not in last_set]
    explored = [p for p in live if p in last_set]
    if prefer_multi and unexplored:
        return unexplored + explored
    if prefer_multi and explored:
        # 轮换：把上次第一个源放到末尾
        return explored[1:] + unexplored + explored[:1] if len(explored) > 1 else live
    # 质量好时保持注册顺序（稳定）
    return list(live)


def quality_delta(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """对比本次与上次质量，供 hot_insights / UX。"""
    if not previous:
        return {
            "has_baseline": False,
            "score_delta": None,
            "improved": None,
            "hint": "首次记录搜索质量，下次同 query 可自适应扩词。",
        }
    cur = float(current.get("score") or 0)
    prev = float(previous.get("score") or 0)
    delta = round(cur - prev, 1)
    return {
        "has_baseline": True,
        "score_delta": delta,
        "improved": delta >= 3,
        "regressed": delta <= -5,
        "previous_label": previous.get("label"),
        "previous_score": prev,
        "hint": (
            f"相对上次质量 Δ={delta:+.1f}（{previous.get('label')}→{current.get('label')}）。"
        ),
    }