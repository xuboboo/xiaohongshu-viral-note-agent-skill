from __future__ import annotations

from xhs_skill.schemas.research import SearchQuery, SearchResult


class ManualURLProvider:
    name = "manual"

    def __init__(self, urls: list[str]) -> None:
        self.urls = urls

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        return [
            SearchResult(
                url=url,
                title=f"用户提供的小红书参考 {index}",
                snippet=query.query,
                source_provider=self.name,
                source_rank=index,
            )
            for index, url in enumerate(self.urls[: query.limit], start=1)
        ]
