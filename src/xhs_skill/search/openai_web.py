from __future__ import annotations

import json

from xhs_skill.core.errors import SearchError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.schemas.research import SearchQuery, SearchResult


class OpenAIWebSearchProvider:
    name = "openai_web"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        schema = {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "title": {"type": "string"},
                            "snippet": {"type": "string"},
                            "published_at": {"type": ["string", "null"]},
                        },
                        "required": ["url", "title", "snippet", "published_at"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        }
        payload = {
            "model": self.model,
            "tools": [{"type": "web_search"}],
            "input": (
                "搜索公开网页中与以下主题相关、近期可访问的小红书笔记或相关页面。"
                "只返回真实 URL，不得虚构互动指标。主题：" + query.query
            ),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "search_results",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        try:
            client = await get_http_pool().get()
            response = await client.post(
                f"{self.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=90,
            )
            response.raise_for_status()
            raw = response.json()
            text = raw.get("output_text", "")
            if not text:
                chunks = []
                for item in raw.get("output", []):
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            chunks.append(content.get("text", ""))
                text = "".join(chunks)
            data = json.loads(text)
            return [
                SearchResult(
                    url=row["url"],
                    title=row["title"],
                    snippet=row.get("snippet"),
                    published_at=row.get("published_at"),
                    source_provider=self.name,
                    source_rank=index,
                )
                for index, row in enumerate(data.get("results", [])[: query.limit], start=1)
            ]
        except Exception as exc:
            raise SearchError(f"OpenAI web search failed: {exc}") from exc
