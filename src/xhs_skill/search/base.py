from __future__ import annotations

from typing import Protocol

from xhs_skill.schemas.research import SearchQuery, SearchResult


class SearchProvider(Protocol):
    name: str

    async def search(self, query: SearchQuery) -> list[SearchResult]: ...
