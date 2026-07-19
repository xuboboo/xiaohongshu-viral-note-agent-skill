from __future__ import annotations

from datetime import datetime

from xhs_skill.core.errors import SearchError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.schemas.research import SearchQuery, SearchResult


class GoogleCustomSearchProvider:
    name = "google_cse"

    def __init__(self, api_key: str, cx: str, base_url: str) -> None:
        self.api_key = api_key
        self.cx = cx
        self.base_url = base_url

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            client = await get_http_pool().get()
            remaining = min(query.limit, 100)
            start = 1
            while remaining > 0:
                count = min(remaining, 10)
                response = await client.get(
                    self.base_url,
                    params={
                        "key": self.api_key,
                        "cx": self.cx,
                        "q": query.query,
                        "num": count,
                        "start": start,
                        "hl": "zh-CN",
                    },
                )
                response.raise_for_status()
                items = response.json().get("items", [])
                if not items:
                    break
                for item in items:
                    pagemap = item.get("pagemap", {})
                    meta = (pagemap.get("metatags") or [{}])[0]
                    raw_date = meta.get("article:published_time") or meta.get("date")
                    published_at = None
                    if raw_date:
                        try:
                            published_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                        except ValueError:
                            published_at = None
                    results.append(
                        SearchResult(
                            url=item.get("link", ""),
                            title=item.get("title", ""),
                            snippet=item.get("snippet"),
                            published_at=published_at,
                            source_provider=self.name,
                            source_rank=len(results) + 1,
                            metadata={"display_link": item.get("displayLink")},
                        )
                    )
                remaining -= len(items)
                start += len(items)
            return [item for item in results if item.url and item.title]
        except Exception as exc:
            raise SearchError(f"Google Custom Search failed: {exc}") from exc
