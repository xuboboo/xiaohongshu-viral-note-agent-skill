from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xhs_skill.schemas.research import SearchQuery, SearchResult

_ALLOWED_METADATA_FIELDS = {
    "id",
    "author_name",
    "likes",
    "saves",
    "comments",
    "shares",
    "views",
    "followers",
    "commercial_probability",
    "include_all",
}


def _limited_text(value: Any, limit: int) -> str:
    text = str(value or "")
    return text[:limit]


def _safe_metadata(row: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {"rights_status": "AUTHORIZED"}
    for key in _ALLOWED_METADATA_FIELDS:
        value = row.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    return safe


class AuthorizedImportProvider:
    name = "authorized_import"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, dict) and isinstance(raw.get("notes"), list):
            rows = raw["notes"]
        else:
            raise ValueError(
                "Authorized import must be a JSON array or an object with a notes array"
            )
        if len(rows) > 10_000:
            raise ValueError("Authorized import contains too many notes")
        results: list[SearchResult] = []
        for index, raw_row in enumerate(rows, start=1):
            if not isinstance(raw_row, dict):
                raise ValueError(f"Authorized note at index {index} must be an object")
            title = _limited_text(raw_row.get("title"), 500)
            body = _limited_text(raw_row.get("body") or raw_row.get("snippet"), 20_000)
            haystack = f"{title} {body}"
            if query.query.casefold() not in haystack.casefold() and not raw_row.get("include_all"):
                continue
            url = _limited_text(
                raw_row.get("url")
                or f"authorized://{_limited_text(raw_row.get('id'), 128) or index}",
                2_048,
            )
            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=body or None,
                    published_at=raw_row.get("published_at"),
                    source_provider=self.name,
                    source_rank=index,
                    metadata=_safe_metadata(raw_row),
                )
            )
            if len(results) >= query.limit:
                break
        return results
