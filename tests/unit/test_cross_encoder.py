"""Cross-encoder：RRF 合并、超时、缓存。"""
import asyncio
from types import SimpleNamespace

import pytest

from xhs_skill.ranking.cross_encoder import (
    clear_cross_encoder_cache,
    cross_encoder_scores,
    merge_cross_encoder_channel,
)
from xhs_skill.ranking.hybrid import HybridTitleRanker
from xhs_skill.schemas.content import TitleCandidate


def test_merge_ce_channel_boosts_top():
    fused = {"a": 0.02, "b": 0.01}
    ce = {"b": 0.99, "a": 0.1}
    merged = merge_cross_encoder_channel(["a", "b"], fused, ce, weight=2.0, k=1)
    assert merged["b"] > merged["a"]


@pytest.mark.asyncio
async def test_cross_encoder_empty_without_provider():
    clear_cross_encoder_cache()
    candidates = [
        TitleCandidate(id="1", title="测试标题A", mechanism="m"),
        TitleCandidate(id="2", title="测试标题B", mechanism="m"),
    ]

    class EmptyRegistry:
        def candidates(self, name=None):
            return []

    scores = await cross_encoder_scores(
        "主题", candidates, providers=EmptyRegistry()  # type: ignore[arg-type]
    )
    assert scores == {}


@pytest.mark.asyncio
async def test_cross_encoder_timeout_and_cache():
    clear_cross_encoder_cache()
    candidates = [
        TitleCandidate(id="1", title="标题一", mechanism="m"),
        TitleCandidate(id="2", title="标题二", mechanism="m"),
    ]

    class SlowProvider:
        name = "slow"
        default_model = "m1"

        async def generate(self, request):
            await asyncio.sleep(0.2)
            return SimpleNamespace(
                data={
                    "scores": [
                        {"id": "1", "score": 0.9},
                        {"id": "2", "score": 0.2},
                    ]
                }
            )

    class Registry:
        def candidates(self, name=None):
            return [SlowProvider()]

    # timeout 太短 → 空
    empty = await cross_encoder_scores(
        "主题",
        candidates,
        providers=Registry(),  # type: ignore[arg-type]
        timeout_seconds=0.05,
        cache_ttl_seconds=0,
    )
    assert empty == {}

    # 正常完成 + 缓存
    first = await cross_encoder_scores(
        "主题",
        candidates,
        providers=Registry(),  # type: ignore[arg-type]
        timeout_seconds=1.0,
        cache_ttl_seconds=60.0,
    )
    assert first["1"] == 0.9

    class BoomRegistry:
        def candidates(self, name=None):
            raise RuntimeError("should not be called when cache hits")

    second = await cross_encoder_scores(
        "主题",
        candidates,
        providers=BoomRegistry(),  # type: ignore[arg-type]
        timeout_seconds=2.0,
        cache_ttl_seconds=60.0,
    )
    assert second == first


def test_hybrid_accepts_precomputed_ce():
    candidates = [
        TitleCandidate(id="1", title="空气炸锅怎么选", mechanism="搜索"),
        TitleCandidate(id="2", title="闭眼冲空气炸锅", mechanism="硬广"),
    ]
    ranker = HybridTitleRanker(cross_encoder_enabled=False)
    ordered, fused, meta = ranker.rank(
        candidates,
        "空气炸锅",
        ce_scores={"1": 0.9, "2": 0.1},
        apply_mmr=False,
    )
    assert meta["cross_encoder_active"] is True
    assert "cross_encoder" in meta["channels"]
    assert ordered[0].scores.get("cross_encoder") is not None
    assert fused