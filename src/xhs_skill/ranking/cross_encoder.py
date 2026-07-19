"""Cross-encoder 风格标题精排（有模型 key 时旁路）。

生产约束（2026 hybrid/rerank 实践）：
- 只精排粗排 top-k，控制延迟预算
- 单次超时 + 最多尝试 1 个 provider（成本保护）
- 进程内 TTL 缓存（同 topic+标题集合命中直接返回）
- 无 key / 超时 / 失败：静默跳过，不拖垮 generate
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Sequence
from threading import Lock

from xhs_skill.providers.registry import ProviderRegistry
from xhs_skill.schemas.content import TitleCandidate
from xhs_skill.schemas.provider import GenerationRequest

logger = logging.getLogger(__name__)

SYSTEM = (
    "你是小红书标题相关性评审。根据主题给每个标题打 0 到 1 的相关分。"
    "只评估搜索意图匹配、具体性、可信度；不要编造点击数据。"
)

# 进程内缓存：key → (expire_monotonic, scores)
_CE_CACHE: dict[str, tuple[float, dict[str, float]]] = {}
_CE_CACHE_LOCK = Lock()
_CE_CACHE_MAX = 256


def _cache_key(topic: str, pool: Sequence[TitleCandidate]) -> str:
    payload = json.dumps(
        {
            "topic": topic,
            "titles": [{"id": item.id, "title": item.title} for item in pool],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict[str, float] | None:
    now = time.monotonic()
    with _CE_CACHE_LOCK:
        hit = _CE_CACHE.get(key)
        if not hit:
            return None
        expire_at, scores = hit
        if expire_at < now:
            _CE_CACHE.pop(key, None)
            return None
        return dict(scores)


def _cache_put(key: str, scores: dict[str, float], ttl_seconds: float) -> None:
    if ttl_seconds <= 0:
        return
    expire_at = time.monotonic() + ttl_seconds
    with _CE_CACHE_LOCK:
        if len(_CE_CACHE) >= _CE_CACHE_MAX:
            # 简单淘汰：删最早过期项
            oldest = min(_CE_CACHE.items(), key=lambda item: item[1][0])[0]
            _CE_CACHE.pop(oldest, None)
        _CE_CACHE[key] = (expire_at, dict(scores))


def clear_cross_encoder_cache() -> None:
    with _CE_CACHE_LOCK:
        _CE_CACHE.clear()


async def cross_encoder_scores(
    topic: str,
    candidates: Sequence[TitleCandidate],
    *,
    providers: ProviderRegistry | None = None,
    provider_name: str | None = None,
    limit: int = 12,
    timeout_seconds: float = 4.0,
    cache_ttl_seconds: float = 300.0,
    max_provider_attempts: int = 1,
) -> dict[str, float]:
    """返回 {title_id: score}；失败/超时返回空 dict。"""
    if not candidates:
        return {}
    pool = list(candidates)[: max(1, limit)]
    key = _cache_key(topic, pool)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    registry = providers or ProviderRegistry()
    try:
        provider_list = registry.candidates(provider_name)
    except Exception:
        return {}
    if not provider_list:
        return {}

    schema = {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "score": {"type": "number"},
                    },
                    "required": ["id", "score"],
                },
            }
        },
        "required": ["scores"],
        "additionalProperties": False,
    }
    payload = {
        "topic": topic,
        "titles": [
            {"id": item.id, "title": item.title, "mechanism": item.mechanism}
            for item in pool
        ],
    }

    attempts = 0
    for provider in provider_list:
        if attempts >= max(1, max_provider_attempts):
            break
        model = getattr(provider, "default_model", None)
        if not model:
            continue
        attempts += 1
        try:
            response = await asyncio.wait_for(
                provider.generate(
                    GenerationRequest(
                        model=model,
                        system=SYSTEM,
                        prompt=json.dumps(payload, ensure_ascii=False),
                        output_schema=schema,
                    )
                ),
                timeout=max(0.1, float(timeout_seconds)),
            )
        except TimeoutError:
            logger.debug(
                "cross-encoder provider %s timed out after %.1fs",
                getattr(provider, "name", "?"),
                timeout_seconds,
            )
            continue
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cross-encoder provider %s failed: %s",
                getattr(provider, "name", "?"),
                type(exc).__name__,
            )
            continue

        data = response.data or {}
        scores_raw = data.get("scores") if isinstance(data, dict) else None
        if not isinstance(scores_raw, list):
            continue
        result: dict[str, float] = {}
        valid_ids = {item.id for item in pool}
        for entry in scores_raw:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("id") or "")
            if item_id not in valid_ids:
                continue
            try:
                score = float(entry.get("score", 0.0))
            except (TypeError, ValueError):
                continue
            result[item_id] = max(0.0, min(1.0, score))
        if result:
            _cache_put(key, result, cache_ttl_seconds)
            return result
    return {}


def merge_cross_encoder_channel(
    fused_order: list[str],
    fused_scores: dict[str, float],
    ce_scores: dict[str, float],
    *,
    weight: float = 1.15,
    k: int = 60,
) -> dict[str, float]:
    """把 CE 通道以 RRF 方式并入已有融合分。"""
    if not ce_scores:
        return fused_scores
    ce_order = sorted(ce_scores.keys(), key=lambda item: ce_scores[item], reverse=True)
    merged = dict(fused_scores)
    for rank, doc_id in enumerate(ce_order, start=1):
        merged[doc_id] = merged.get(doc_id, 0.0) + weight / (k + rank)
    return merged