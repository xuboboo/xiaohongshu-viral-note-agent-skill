from __future__ import annotations

import argparse
import asyncio
import json

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.research import ResearchService  # noqa: E402
from xhs_skill.schemas.research import SearchQuery  # noqa: E402


async def run(args: argparse.Namespace) -> None:
    report = await ResearchService().search_hot_notes(
        SearchQuery(query=args.query, time_range=args.time_range, limit=args.limit),
        providers=args.provider or None,
    )
    print(json.dumps({
        "query": report.query,
        "trends": [item.model_dump(mode="json") for item in report.trends],
        "coverage_warning": report.coverage_warning,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="搜索当前小红书公开索引趋势")
    parser.add_argument("--query", required=True)
    parser.add_argument("--time-range", default="7d")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--provider", action="append", default=[])
    asyncio.run(run(parser.parse_args()))
