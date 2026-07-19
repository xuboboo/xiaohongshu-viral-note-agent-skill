from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.research import ResearchService  # noqa: E402
from xhs_skill.schemas.research import SearchQuery  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="联网搜索当前公开索引或授权数据中的热门小红书笔记")
    parser.add_argument("--query", required=True)
    parser.add_argument("--time-range", default="7d")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--provider", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    async def run() -> dict:
        report = await ResearchService().search_hot_notes(
            SearchQuery(query=args.query, time_range=args.time_range, limit=args.limit),
            providers=args.provider or None,
        )
        return report.model_dump(mode="json")

    payload = asyncio.run(run())
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
