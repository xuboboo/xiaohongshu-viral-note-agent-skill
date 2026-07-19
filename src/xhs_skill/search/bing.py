from __future__ import annotations

from datetime import UTC, datetime

from xhs_skill.core.errors import SearchError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.schemas.research import SearchQuery, SearchResult


class BingSearchProvider:
    name = "bing"

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        try:
            client = await get_http_pool().get()
            response = await client.get(
                self.base_url,
                headers={"Ocp-Apim-Subscription-Key": self.api_key},
                params={
                    "q": query.query,
                    "count": min(query.limit, 50),
                    "mkt": "zh-CN",
                    "textDecorations": False,
                    "textFormat": "Raw",
                },
            )
            response.raise_for_status()
            values = response.json().get("webPages", {}).get("value", [])
            out: list[SearchResult] = []
            for index, item in enumerate(values, start=1):
                date_published = item.get("datePublished") or item.get("dateLastCrawled")
                published_at = None
                if date_published:
                    try:
                        published_at = datetime.fromisoformat(str(date_published).replace("Z", "+00:00"))
                    except ValueError:
                        published_at = None
                out.append(
                    SearchResult(
                        url=item.get("url", ""),
                        title=item.get("name", ""),
                        snippet=item.get("snippet"),
                        published_at=published_at,
                        source_provider=self.name,
                        source_rank=index,
                        metadata={"indexed_at": datetime.now(UTC).isoformat()},
                    )
                )
            return [item for item in out if item.url and item.title]
        except Exception as exc:
            raise SearchError(f"Bing search failed: {exc}") from exc
