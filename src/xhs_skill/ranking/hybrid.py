"""混合标题排序：规则 + LambdaMART + 语义相关 → RRF →（可选 CE）→ MMR。

产业实践（2025–2026）：
- LambdaMART/GBDT 仍是 LTR 强基线（尤其小样本）
- 生产 hybrid 常用 RRF 融合多路，而非硬拼分数
- Cross-encoder / LLM-as-CE 只在有 key 时旁路精排 top-k
- MMR 做多样性重排，避免标题同质化
"""
from __future__ import annotations

from collections.abc import Sequence

from xhs_skill.intelligence.embeddings import cosine_similarity
from xhs_skill.ranking.cross_encoder import (
    cross_encoder_scores,
    merge_cross_encoder_channel,
)
from xhs_skill.ranking.diversity import mmr_rerank
from xhs_skill.ranking.fusion import reciprocal_rank_fusion
from xhs_skill.ranking.learning_ranker import LambdaMARTRanker
from xhs_skill.ranking.rule_ranker import rank_titles
from xhs_skill.schemas.content import TitleCandidate


def _order_by_scores(ids: Sequence[str], scores: dict[str, float]) -> list[str]:
    return sorted(ids, key=lambda item: scores.get(item, 0.0), reverse=True)


def semantic_relevance_scores(
    candidates: Sequence[TitleCandidate],
    *,
    topic_vector: Sequence[float] | None,
    title_vectors: dict[str, list[float]] | None,
) -> dict[str, float]:
    """标题向量与主题向量的余弦相关（无 embedding 时退化为 0）。"""
    if not topic_vector or not title_vectors:
        return {item.id: 0.0 for item in candidates}
    scores: dict[str, float] = {}
    for item in candidates:
        vec = title_vectors.get(item.id)
        scores[item.id] = (
            round(cosine_similarity(topic_vector, vec), 6) if vec else 0.0
        )
    return scores


class HybridTitleRanker:
    """多路标题排序编排器（职责：融合，不训练模型）。"""

    def __init__(
        self,
        learning_ranker: LambdaMARTRanker | None = None,
        *,
        rrf_k: int = 60,
        mmr_lambda: float = 0.72,
        cross_encoder_enabled: bool = False,
        cross_encoder_weight: float = 1.15,
        cross_encoder_top_k: int = 12,
        cross_encoder_timeout_seconds: float = 4.0,
        cross_encoder_cache_ttl_seconds: float = 300.0,
        cross_encoder_max_provider_attempts: int = 1,
        providers=None,
        provider_name: str | None = None,
    ) -> None:
        self.learning_ranker = learning_ranker or LambdaMARTRanker()
        self.rrf_k = rrf_k
        self.mmr_lambda = mmr_lambda
        self.cross_encoder_enabled = cross_encoder_enabled
        self.cross_encoder_weight = cross_encoder_weight
        self.cross_encoder_top_k = cross_encoder_top_k
        self.cross_encoder_timeout_seconds = cross_encoder_timeout_seconds
        self.cross_encoder_cache_ttl_seconds = cross_encoder_cache_ttl_seconds
        self.cross_encoder_max_provider_attempts = cross_encoder_max_provider_attempts
        self.providers = providers
        self.provider_name = provider_name

    def rank(
        self,
        candidates: list[TitleCandidate],
        keyword: str,
        *,
        topic_vector: list[float] | None = None,
        title_vectors: dict[str, list[float]] | None = None,
        limit: int | None = None,
        apply_mmr: bool = True,
        ce_scores: dict[str, float] | None = None,
    ) -> tuple[list[TitleCandidate], dict[str, float], dict[str, object]]:
        """同步融合路径；CE 分可预先异步算好后传入。"""
        if not candidates:
            return [], {}, {"channels": []}

        rule_ranked, rule_scores = rank_titles(candidates, keyword)
        rule_order = [item.id for item in rule_ranked]

        learn_ranked, learn_scores = self.learning_ranker.rank(candidates, keyword)
        learn_order = [item.id for item in learn_ranked]
        learn_channel = (
            "lambdamart" if self.learning_ranker.model is not None else "audited-rule-fallback"
        )

        semantic_scores = semantic_relevance_scores(
            candidates,
            topic_vector=topic_vector,
            title_vectors=title_vectors,
        )
        has_semantic = bool(topic_vector and title_vectors and any(semantic_scores.values()))
        semantic_order = _order_by_scores([item.id for item in candidates], semantic_scores)

        ranked_lists = [rule_order, learn_order]
        weights = [1.0, 1.2 if self.learning_ranker.model is not None else 1.0]
        channels: list[str] = ["rule", learn_channel]
        if has_semantic:
            ranked_lists.append(semantic_order)
            weights.append(1.1)
            channels.append("semantic")

        fused = reciprocal_rank_fusion(ranked_lists, k=self.rrf_k, weights=weights)

        ce_active = bool(ce_scores)
        if ce_active and ce_scores:
            fused = merge_cross_encoder_channel(
                list(fused.keys()),
                fused,
                ce_scores,
                weight=self.cross_encoder_weight,
                k=self.rrf_k,
            )
            channels.append("cross_encoder")

        by_id = {item.id: item for item in candidates}
        fused_order = sorted(fused.keys(), key=lambda item: fused[item], reverse=True)
        ordered = [by_id[item_id] for item_id in fused_order if item_id in by_id]

        cap = limit if limit is not None else len(ordered)
        if apply_mmr and len(ordered) > 1:
            ordered = mmr_rerank(
                ordered,
                relevance=fused,
                limit=cap,
                lambda_=self.mmr_lambda,
                embeddings=title_vectors,
            )
        else:
            ordered = ordered[:cap]

        meta: dict[str, object] = {
            "channels": channels,
            "rrf_k": self.rrf_k,
            "mmr": apply_mmr,
            "learn_channel": learn_channel,
            "semantic_active": has_semantic,
            "cross_encoder_active": ce_active,
            "rule_top": rule_order[:3],
            "fused_top": [item.id for item in ordered[:3]],
        }
        for item in ordered:
            item.scores = {
                **(item.scores or {}),
                "rrf": round(fused.get(item.id, 0.0), 6),
                "rule": round(rule_scores.get(item.id, 0.0), 6),
                "learn": round(learn_scores.get(item.id, 0.0), 6),
                "semantic": round(semantic_scores.get(item.id, 0.0), 6),
                "cross_encoder": round((ce_scores or {}).get(item.id, 0.0), 6),
            }
        return ordered, fused, meta

    async def rank_async(
        self,
        candidates: list[TitleCandidate],
        keyword: str,
        *,
        topic_vector: list[float] | None = None,
        title_vectors: dict[str, list[float]] | None = None,
        limit: int | None = None,
        apply_mmr: bool = True,
    ) -> tuple[list[TitleCandidate], dict[str, float], dict[str, object]]:
        """异步路径：可选调用 CE 旁路后再融合。"""
        ce_scores: dict[str, float] | None = None
        if self.cross_encoder_enabled and candidates:
            pre, _, _ = self.rank(
                candidates,
                keyword,
                topic_vector=topic_vector,
                title_vectors=title_vectors,
                limit=min(len(candidates), self.cross_encoder_top_k),
                apply_mmr=False,
                ce_scores=None,
            )
            ce_scores = await cross_encoder_scores(
                keyword,
                pre,
                providers=self.providers,
                provider_name=self.provider_name,
                limit=self.cross_encoder_top_k,
                timeout_seconds=self.cross_encoder_timeout_seconds,
                cache_ttl_seconds=self.cross_encoder_cache_ttl_seconds,
                max_provider_attempts=self.cross_encoder_max_provider_attempts,
            ) or None
        ordered, fused, meta = self.rank(
            candidates,
            keyword,
            topic_vector=topic_vector,
            title_vectors=title_vectors,
            limit=limit,
            apply_mmr=apply_mmr,
            ce_scores=ce_scores,
        )
        meta["cross_encoder_timeout_seconds"] = self.cross_encoder_timeout_seconds
        meta["cross_encoder_cache_ttl_seconds"] = self.cross_encoder_cache_ttl_seconds
        meta["cross_encoder_max_provider_attempts"] = (
            self.cross_encoder_max_provider_attempts
        )
        return ordered, fused, meta