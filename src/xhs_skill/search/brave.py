from __future__ import annotations

from datetime import datetime

from xhs_skill.core.errors import SearchError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.schemas.research import SearchQuery, SearchResult


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        params: dict[str, str | int] = {
            "q": query.query,
            "count": min(query.limit, 20),
            "country": query.country.lower(),
            "search_lang": query.language,
            "safesearch": "moderate",
            "freshness": query.time_range,
        }
        try:
            client = await get_http_pool().get()
            response = await client.get(
                f"{self.base_url}/web/search",
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            rows = response.json().get("web", {}).get("results", [])
            results: list[SearchResult] = []
            for index, row in enumerate(rows, start=1):
                published = row.get("age") or row.get("page_age")
                try:
                    published_at = (
                        datetime.fromisoformat(published.replace("Z", "+00:00"))
                        if published
                        else None
                    )
                except (TypeError, ValueError):
                    published_at = None
                results.append(
                    SearchResult(
                        url=row["url"],
                        title=row.get("title", ""),
                        snippet=row.get("description"),
                        published_at=published_at,
                        source_provider=self.name,
                        source_rank=index,
                        metadata={"extra_snippets": row.get("extra_snippets", [])},
                    )
                )
            return results
        except Exception as exc:
            raise SearchError(f"Brave search failed: {exc}") from exc
