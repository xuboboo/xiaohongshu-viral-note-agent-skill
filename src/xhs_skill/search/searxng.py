from __future__ import annotations

from datetime import datetime

from xhs_skill.core.errors import SearchError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.schemas.research import SearchQuery, SearchResult


class SearxNGSearchProvider:
    name = "searxng"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        try:
            client = await get_http_pool().get()
            response = await client.get(
                f"{self.base_url}/search",
                params={"q": query.query, "format": "json", "language": query.language},
                timeout=30,
            )
            response.raise_for_status()
            results = []
            for index, row in enumerate(response.json().get("results", [])[: query.limit], start=1):
                published_at = None
                if row.get("publishedDate"):
                    try:
                        published_at = datetime.fromisoformat(
                            row["publishedDate"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass
                results.append(
                    SearchResult(
                        url=row["url"],
                        title=row.get("title", ""),
                        snippet=row.get("content"),
                        published_at=published_at,
                        source_provider=self.name,
                        source_rank=index,
                        metadata={"engine": row.get("engine")},
                    )
                )
            return results
        except Exception as exc:
            raise SearchError(f"SearxNG search failed: {exc}") from exc
