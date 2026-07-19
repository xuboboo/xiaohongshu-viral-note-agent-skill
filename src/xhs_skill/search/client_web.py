from __future__ import annotations

from xhs_skill.schemas.research import SearchQuery, SearchResult


class ClientWebSearchProvider:
    """Search provider fed by host-agent / client websearch results.

    The skill never calls the host's websearch API itself. The host agent
    (Cursor, Claude, etc.) runs websearch, then passes structured hits here.
    """

    name = "client_web"

    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self._results = list(results or [])

    def load(self, results: list[SearchResult]) -> None:
        self._results = list(results)

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        # Host already ran query expansion / websearch; return ranked hits as-is.
        return self._results[: query.limit]