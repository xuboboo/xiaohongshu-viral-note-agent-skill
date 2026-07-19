"""Contextual bandit 上下文特征工程。

固定维度向量，保证 LinUCB A 矩阵维度稳定：
  [bias, hour_sin, hour_cos, weekday_sin, weekday_cos,
   account_weight_norm, is_weekend, format_graphic, format_video,
   objective_search, objective_growth, category_hash]
"""
from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

BANDIT_CONTEXT_DIM = 12
BANDIT_CONTEXT_NAMES = [
    "bias",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "account_weight",
    "is_weekend",
    "format_graphic",
    "format_video",
    "objective_search",
    "objective_growth",
    "category_hash",
]


class BanditContextFeatures(BaseModel):
    """结构化上下文；服务端编码为固定长度向量。"""

    account_weight: float | None = Field(default=None, ge=0, le=100)
    hour: int | None = Field(default=None, ge=0, le=23)
    weekday: int | None = Field(default=None, ge=0, le=6)  # 0=Mon
    category: str | None = None
    content_pillar: str | None = None
    objective: str | None = None  # search_growth / recommendation / hybrid ...
    format: str | None = None  # graphic / video
    now: datetime | None = None


def _unit_hash(text: str) -> float:
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big") / float(2**64 - 1)
    return round(value, 6)


def build_bandit_context(features: BanditContextFeatures | dict[str, Any] | None = None) -> list[float]:
    """编码为长度 BANDIT_CONTEXT_DIM 的 float 向量。"""
    if features is None:
        features = BanditContextFeatures()
    elif isinstance(features, dict):
        features = BanditContextFeatures.model_validate(features)

    now = features.now or datetime.now(UTC)
    hour = features.hour if features.hour is not None else now.hour
    weekday = features.weekday if features.weekday is not None else now.weekday()

    hour_angle = 2 * math.pi * (hour / 24.0)
    weekday_angle = 2 * math.pi * (weekday / 7.0)
    weight = features.account_weight
    weight_norm = 0.5 if weight is None else max(0.0, min(1.0, float(weight) / 100.0))

    fmt = (features.format or "").strip().lower()
    objective = (features.objective or "").strip().lower()
    category = (features.category or features.content_pillar or "").strip().lower()

    vector = [
        1.0,  # bias
        math.sin(hour_angle),
        math.cos(hour_angle),
        math.sin(weekday_angle),
        math.cos(weekday_angle),
        weight_norm,
        1.0 if weekday >= 5 else 0.0,
        1.0 if fmt in {"graphic", "image", "图文"} else 0.0,
        1.0 if fmt in {"video", "视频"} else 0.0,
        1.0 if "search" in objective or objective in {"search_growth", "搜索"} else 0.0,
        1.0 if "growth" in objective or "recommend" in objective else 0.0,
        _unit_hash(category) if category else 0.0,
    ]
    assert len(vector) == BANDIT_CONTEXT_DIM
    return [round(float(value), 8) for value in vector]


def describe_bandit_context(vector: list[float]) -> dict[str, float]:
    names = BANDIT_CONTEXT_NAMES
    return {
        names[index] if index < len(names) else f"dim_{index}": value
        for index, value in enumerate(vector)
    }