from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from dateutil.parser import parse as parse_date

from xhs_skill.schemas.research import SearchResult

__all__ = [
    "LIVE_SEARCH_PROVIDERS",
    "ClientWebSearchRequired",
    "available_live_providers",
    "filter_low_quality_web_results",
    "normalize_web_results",
    "resolve_provider_names",
    "trust_score",
]

# Live HTTP providers that need external keys/endpoints.
LIVE_SEARCH_PROVIDERS = (
    "brave",
    "bing",
    "google_cse",
    "searxng",
    "openai_web",
)


class ClientWebSearchRequired(Exception):
    """No live search key and no host-provided web_results — host should search."""

    def __init__(
        self,
        query: str,
        *,
        suggested_queries: list[str],
        time_range: str = "7d",
        limit: int = 30,
    ) -> None:
        self.query = query
        self.suggested_queries = suggested_queries
        self.time_range = time_range
        self.limit = limit
        super().__init__(
            "No configured search API and no web_results. "
            "Host agent should run websearch, then re-call with web_results."
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": "needs_web_search",
            "query": self.query,
            "time_range": self.time_range,
            "limit": self.limit,
            "suggested_queries": self.suggested_queries,
            "web_results_schema": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["url", "title"],
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                        "published_at": {"type": "string"},
                        "source_rank": {"type": "integer"},
                        "likes": {"type": "integer"},
                        "saves": {"type": "integer"},
                        "comments": {"type": "integer"},
                        "shares": {"type": "integer"},
                        "views": {"type": "integer"},
                        "author_name": {"type": "string"},
                    },
                },
            },
            "instructions": (
                "1) 用宿主自带 websearch 按 suggested_queries 检索小红书/公开网页结果；"
                "2) 把结果整理为 web_results（至少 url + title）；"
                "3) 再次调用同一 tool，并传入 web_results。"
                "skill 会负责去重、排序、趋势与机制蒸馏，不会静默使用 fixture 假数据。"
            ),
        }


def available_live_providers(registered: list[str]) -> list[str]:
    registered_set = set(registered)
    return [name for name in LIVE_SEARCH_PROVIDERS if name in registered_set]


def resolve_provider_names(
    *,
    registered: list[str],
    explicit: list[str] | None,
    has_web_results: bool,
    fallback: str = "delegate",
    query: str = "",
    time_range: str = "7d",
    limit: int = 30,
    preferred_order: list[str] | None = None,
    max_live_providers: int | None = None,
) -> list[str]:
    """Pick providers for this call.

    Priority:
    1. Host-provided web_results → client_web
    2. Explicit providers from caller
    3. Live providers（可按 preferred_order / max_live_providers 裁剪）
    4. fallback: delegate (raise) | fixture | error
    """
    if has_web_results:
        return ["client_web"]

    def _order_live(live: list[str]) -> list[str]:
        if preferred_order:
            ordered = [p for p in preferred_order if p in live]
            ordered.extend(p for p in live if p not in ordered)
            live = ordered
        if max_live_providers is not None and max_live_providers > 0:
            live = live[: max_live_providers]
        return live

    def _fallback_or_raise() -> list[str]:
        from xhs_skill.research.query_expansion import expand_query

        mode = (fallback or "delegate").strip().lower()
        if mode == "fixture" and "fixture" in registered:
            return ["fixture"]
        if mode == "error":
            raise ClientWebSearchRequired(
                query,
                suggested_queries=expand_query(query)[:6] if query else [],
                time_range=time_range,
                limit=limit,
            )
        raise ClientWebSearchRequired(
            query,
            suggested_queries=expand_query(query)[:6] if query else [],
            time_range=time_range,
            limit=limit,
        )

    if explicit:
        names = [name for name in explicit if name != "auto"]
        wants_auto = any(name == "auto" for name in explicit)
        if wants_auto or not names:
            live = _order_live(available_live_providers(registered))
            if live:
                names.extend(live)
            else:
                names.extend(_fallback_or_raise())
        seen: set[str] = set()
        ordered: list[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    live = _order_live(available_live_providers(registered))
    if live:
        return live
    return _fallback_or_raise()


def normalize_web_results(raw_items: list[dict[str, Any]] | list[SearchResult]) -> list[SearchResult]:
    """Convert host websearch hits into SearchResult rows."""
    results: list[SearchResult] = []
    for index, item in enumerate(raw_items, start=1):
        if isinstance(item, SearchResult):
            results.append(item)
            continue
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "").strip()
        title = str(item.get("title") or item.get("name") or "").strip()
        if not url or not title:
            continue
        snippet = item.get("snippet") or item.get("description") or item.get("content")
        published_at = item.get("published_at") or item.get("date") or item.get("published")
        parsed_published: datetime | None = None
        if isinstance(published_at, datetime):
            parsed_published = published_at if published_at.tzinfo else published_at.replace(tzinfo=UTC)
        elif isinstance(published_at, str) and published_at.strip():
            try:
                parsed = parse_date(published_at)
                parsed_published = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except (ValueError, TypeError, OverflowError):
                parsed_published = None

        metadata: dict[str, Any] = {}
        for key in (
            "likes",
            "saves",
            "comments",
            "shares",
            "views",
            "followers",
            "author_name",
            "body",
            "rights_status",
            "commercial_probability",
        ):
            if key in item and item[key] is not None:
                metadata[key] = item[key]
        # Allow nested metadata from host tools
        if isinstance(item.get("metadata"), dict):
            metadata = {**item["metadata"], **metadata}

        source_rank = item.get("source_rank")
        if source_rank is None:
            source_rank = index
        try:
            source_rank_int = int(source_rank)
        except (TypeError, ValueError):
            source_rank_int = index

        results.append(
            SearchResult(
                url=url,
                title=title,
                snippet=str(snippet).strip() if snippet is not None else None,
                published_at=parsed_published,
                source_provider=str(item.get("source_provider") or "client_web"),
                source_rank=source_rank_int,
                metadata=metadata,
            )
        )
    return results


# 常见低质/噪声 host 模式
_NOISE_HOSTS = frozenset({
    "pinterest.", "facebook.com", "twitter.com", "x.com", "tiktok.com",
    "reddit.com", "youtube.com", "instagram.com",
})

# 可信度较高的内容域名（公开网页索引，非绕过登录）
_TRUSTED_HOSTS = frozenset({
    "xiaohongshu.com", "xhslink.com",
    "zhihu.com", "sohu.com", "163.com", "sina.com.cn", "qq.com",
    "weixin.qq.com", "bilibili.com", "douyin.com",
    "smzdm.com",  # 什么值得买
})

_TITLE_SPAM = frozenset({
    "登录", "注册", "404", "not found", "页面不存在", "验证码",
})


def _host_of(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def filter_low_quality_web_results(results: list[SearchResult]) -> list[SearchResult]:
    """剔除噪声结果：垃圾 host、空标题、垃圾标题、重复 URL。

    返回过滤后的结果与原始列表等长或更短。
    """
    seen_urls: set[str] = set()
    kept: list[SearchResult] = []
    for item in results:
        url = (item.url or "").strip()
        title = (item.title or "").strip()
        host = _host_of(url)

        # URL 空 or 重复
        if not url or url in seen_urls:
            continue

        # 标题过短 or 纯垃圾
        if len(title) < 4:
            continue
        if any(spam in title.lower() for spam in _TITLE_SPAM):
            continue

        # 明确的社交平台噪声（非内容站）
        if any(host.endswith(h) or h in host for h in _NOISE_HOSTS) and "xiaohongshu" not in host:
            # 但 xiaohongshu 的分享链接要保留
            continue

        seen_urls.add(url)
        kept.append(item)
    return kept


def _trust_score(result: SearchResult) -> float:
    host = _host_of(result.url)
    score = 0.5
    if any(host.endswith(h) for h in _TRUSTED_HOSTS):
        score += 0.25
    if "xiaohongshu.com/explore" in result.url or "xiaohongshu.com/discovery" in result.url:
        score += 0.15  # 站内公开索引
    snippet = (result.snippet or "").strip()
    if len(snippet) >= 20:
        score += 0.05
    meta = result.metadata or {}
    if any(meta.get(k) is not None for k in ("likes", "saves", "comments")):
        score += 0.05  # 有互动数据更可信
    return min(1.0, score)


def trust_score(result: SearchResult) -> float:
    """公开 API：单条搜索结果可信度 0–1。"""
    return _trust_score(result)