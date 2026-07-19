from __future__ import annotations

import asyncio
from typing import Any

from xhs_skill.core.cache import SingleFlight, get_cache
from xhs_skill.core.concurrency import get_concurrency_controller
from xhs_skill.core.config import get_settings
from xhs_skill.research.deduplicator import deduplicate
from xhs_skill.research.distiller import distill_mechanisms
from xhs_skill.research.hot_insights import build_hot_insights
from xhs_skill.research.normalizer import result_to_candidate
from xhs_skill.research.quality import assess_search_quality
from xhs_skill.research.query_expansion import expand_query, sanitize_query
from xhs_skill.research.ranker import rank_hot_notes
from xhs_skill.research.search_memory import (
    SearchQualityMemory,
    plan_search_strategy,
    quality_delta,
)
from xhs_skill.research.topic_suggest import suggest_topics_from_report
from xhs_skill.research.trend_detector import detect_content_gaps, extract_topics
from xhs_skill.schemas.research import HotNotesReport, ScoreType, SearchQuery, SearchResult
from xhs_skill.search.adaptive import (
    ClientWebSearchRequired,
    normalize_web_results,
    resolve_provider_names,
    trust_score,
)
from xhs_skill.search.registry import SearchRegistry


class ResearchService:
    def __init__(
        self,
        registry: SearchRegistry | None = None,
        *,
        quality_memory: SearchQualityMemory | None = None,
    ) -> None:
        self.registry = registry or SearchRegistry()
        self.concurrency = get_concurrency_controller()
        self.cache = get_cache()
        self.singleflight: SingleFlight[HotNotesReport] = SingleFlight()
        self.settings = get_settings()
        self.quality_memory = quality_memory or SearchQualityMemory()

    async def _search_one(
        self, provider_name: str, query: SearchQuery, *, max_retries: int = 1
    ) -> list[SearchResult]:
        """带重试的单 provider 搜索。重试间退避 + 断路器保护。"""
        provider = self.registry.get(provider_name)
        circuit = await self.concurrency.circuits.get(f"search:{provider_name}")
        last_exc: Exception | None = None
        for attempt in range(max(1, max_retries)):
            await self.concurrency.provider_rate_limiter.require(f"search:{provider_name}")
            async with self.concurrency.operation_slot("research", provider=provider_name):
                await circuit.before_call()
                try:
                    result = await provider.search(query)
                    await circuit.record_success()
                    return result
                except Exception as exc:
                    await circuit.record_failure()
                    last_exc = exc
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.3 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    async def search_hot_notes(
        self,
        query: SearchQuery,
        *,
        providers: list[str] | None = None,
        expand: bool = True,
        web_results: list[dict[str, Any]] | list[SearchResult] | None = None,
    ) -> HotNotesReport:
        # 清洗查询
        cleaned = sanitize_query(query.query)
        if cleaned != query.query:
            query = query.model_copy(update={"query": cleaned})

        # 上次质量 → 自适应策略（扩词/重试/TTL/多源）
        previous_quality = self.quality_memory.load(query.query)
        from xhs_skill.search.adaptive import available_live_providers

        live_registered = available_live_providers(self.registry.list())
        strategy = plan_search_strategy(
            previous_quality, registered_live=live_registered
        )

        normalized_web = normalize_web_results(web_results or [])
        if normalized_web:
            from xhs_skill.search.adaptive import filter_low_quality_web_results

            normalized_web = filter_low_quality_web_results(normalized_web)
            # 可信度高的结果排前，提升后续截断后的样本质量
            normalized_web = sorted(
                normalized_web, key=trust_score, reverse=True
            )
        if normalized_web:
            self.registry.configure_client_web(normalized_web)

        provider_names = resolve_provider_names(
            registered=self.registry.list(),
            explicit=providers,
            has_web_results=bool(normalized_web),
            fallback=self.settings.search_auto_fallback,
            query=query.query,
            time_range=query.time_range,
            limit=query.limit,
            preferred_order=list(strategy.get("provider_priority") or []),
            max_live_providers=int(strategy.get("max_live_providers") or 0) or None,
        )
        # client_web / authorized_import / manual are request-scoped inputs — never cache.
        cacheable = not any(
            name in {"authorized_import", "manual", "client_web"} for name in provider_names
        )
        cache_key = self.cache.key(
            "hot-notes",
            {
                "query": query.model_dump(mode="json"),
                "providers": sorted(provider_names),
                "expand": expand,
                "strategy_max_variants": strategy.get("max_variants"),
            },
        )
        if cacheable:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return HotNotesReport.model_validate_json(cached)

        async def compute() -> HotNotesReport:
            report = await self._compute_hot_notes(
                query,
                provider_names=provider_names,
                expand=expand,
                strategy=strategy,
                previous_quality=previous_quality,
            )
            if cacheable:
                quality = report.search_quality or {}
                multiplier = float(quality.get("cache_ttl_multiplier", 1.0))
                multiplier *= float(strategy.get("ttl_multiplier_boost") or 1.0)
                ttl = max(10, int(self.settings.search_cache_ttl_seconds * multiplier))
                await self.cache.set(cache_key, report.model_dump_json(), ttl)
            return report

        return await self.singleflight.run(cache_key, compute)

    async def _compute_hot_notes(
        self,
        query: SearchQuery,
        *,
        provider_names: list[str],
        expand: bool,
        strategy: dict[str, Any] | None = None,
        previous_quality: dict[str, Any] | None = None,
    ) -> HotNotesReport:
        strategy = strategy or plan_search_strategy(None)
        # Host already searched; do not re-expand against client_web.
        if provider_names == ["client_web"]:
            expand = False

        max_variants = int(strategy.get("max_variants") or 6)
        variant_cap = int(strategy.get("variant_cap") or 5)
        live_retries = int(strategy.get("live_retries") or 2)

        if expand:
            query_variants = expand_query(
                query.query,
                max_variants=max_variants,
                prefer_crowd_angles=bool(strategy.get("prefer_crowd_angles")),
                force_site_queries=bool(strategy.get("force_site_queries")),
            )
        else:
            query_variants = [query.query]

        live_providers = {"brave", "bing", "google_cse", "searxng", "openai_web"}
        calls = []
        for provider_name in provider_names:
            retries = live_retries if provider_name in live_providers else 1
            for variant in query_variants[:variant_cap]:
                calls.append(
                    self._search_one(
                        provider_name,
                        SearchQuery(
                            query=variant,
                            time_range=query.time_range,
                            limit=min(query.limit, 25),
                            language=query.language,
                            country=query.country,
                        ),
                        max_retries=retries,
                    )
                )

        batches = await asyncio.gather(*calls, return_exceptions=True)
        results: list[SearchResult] = []
        failures: list[str] = []
        for batch in batches:
            if isinstance(batch, BaseException):
                failures.append(type(batch).__name__)
                continue
            results.extend(batch)

        # client_web 已按 trust 排过；live 结果再按 trust 轻排后去重
        results = sorted(results, key=trust_score, reverse=True)
        candidates = deduplicate([result_to_candidate(item) for item in results])[: query.limit]
        candidates = _enforce_source_diversity(candidates, max_share=0.75)

        score_type, ranked = rank_hot_notes(candidates, query.query)
        warning = (
            "该结果基于用户授权的互动数据与公开索引混合排序，仍不代表小红书官方内部热榜。"
            if score_type == ScoreType.METRIC_HOT_SCORE
            else "该结果基于公开网页索引，不代表小红书站内全量热门排名。"
        )
        if "client_web" in provider_names:
            warning += " 搜索结果由宿主 agent websearch 提供（client_web）。"
        if failures:
            warning += f" 部分搜索分片失败，已降级返回可用结果（{len(failures)}/{len(calls)}）。"
        if strategy.get("has_baseline"):
            warning += f" 自适应策略：{strategy.get('reason')}"

        trends = extract_topics(ranked)
        gaps = detect_content_gaps(ranked, trends)
        mechanisms = distill_mechanisms(ranked, query.query)

        trend_memory: dict = {}
        try:
            from xhs_skill.research.trend_memory import apply_trend_memory

            score_label = (
                score_type.value if hasattr(score_type, "value") else str(score_type)
            )
            trend_memory = apply_trend_memory(
                query=query.query,
                score_type=score_label,
                notes=ranked,
                trends=trends,
            )
        except Exception:
            trend_memory = {}

        search_quality = assess_search_quality(
            ranked,
            score_type=score_type,
            query=query.query,
            failures=len(failures),
            total_calls=max(len(calls), 1),
        )
        # 挂策略与 Δ 质量
        search_quality = dict(search_quality)
        search_quality["strategy"] = {
            "max_variants": max_variants,
            "variant_cap": variant_cap,
            "live_retries": live_retries,
            "prefer_crowd_angles": bool(strategy.get("prefer_crowd_angles")),
            "force_site_queries": bool(strategy.get("force_site_queries")),
            "prefer_multi_provider": bool(strategy.get("prefer_multi_provider")),
            "max_live_providers": strategy.get("max_live_providers"),
            "providers_used": list(provider_names),
            "provider_priority": list(strategy.get("provider_priority") or [])[:8],
            "reason": strategy.get("reason"),
            "has_baseline": bool(strategy.get("has_baseline")),
        }
        search_quality["delta"] = quality_delta(search_quality, previous_quality)

        # 持久化本次质量，供下次自适应
        try:
            self.quality_memory.save(
                query.query, search_quality, note_count=len(ranked)
            )
        except Exception:
            pass

        report = HotNotesReport(
            query=query.query,
            time_range=query.time_range,
            score_type=score_type,
            notes=ranked,
            trends=trends,
            mechanisms=mechanisms,
            content_gaps=gaps,
            hot_insights=build_hot_insights(
                ranked,
                trends,
                query=query.query,
                score_type=score_type,
                content_gaps=gaps,
                trend_memory=trend_memory,
            ),
            coverage_warning=warning,
            search_quality=search_quality,
        )
        # 把质量策略摘要塞进 hot_insights，便于 Agent 一眼看到
        insights = dict(report.hot_insights or {})
        insights["search_quality"] = {
            "score": search_quality.get("score"),
            "label": search_quality.get("label"),
            "delta": search_quality.get("delta"),
            "strategy_reason": strategy.get("reason"),
            "recommendations": search_quality.get("recommendations") or [],
        }
        report = report.model_copy(update={"hot_insights": insights})
        return report.model_copy(
            update={"topic_suggestions": suggest_topics_from_report(report)}
        )


def _enforce_source_diversity(
    notes: list, *, max_share: float = 0.75
) -> list:
    """截断被单一源垄断的结果，避免排序偏斜。"""
    if len(notes) <= 3:
        return notes
    source_counts: dict[str, int] = {}
    for n in notes:
        src = getattr(n, "source_provider", "unknown") or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1

    dominant_src, dominant_count = max(source_counts.items(), key=lambda x: x[1])
    if dominant_count / len(notes) <= max_share:
        return notes

    target = max(3, int(len(notes) * max_share))
    result = []
    dominant_seen = 0
    for n in notes:
        src = getattr(n, "source_provider", "unknown") or "unknown"
        if src == dominant_src:
            if dominant_seen < target:
                result.append(n)
                dominant_seen += 1
        else:
            result.append(n)
    return result


# Re-export for callers that catch the delegation signal.
__all__ = ["ResearchService", "ClientWebSearchRequired"]