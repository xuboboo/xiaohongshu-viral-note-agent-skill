from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.orchestrator import ContentWorkflow  # noqa: E402
from xhs_skill.schemas.content import GenerateRequest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="研究当前趋势并生成完整小红书内容包")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--objective", default="search_growth")
    parser.add_argument("--format", default="graphic")
    parser.add_argument("--audience")
    parser.add_argument("--search-provider", action="append", default=[])
    parser.add_argument("--no-research", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    async def run() -> dict:
        package = await ContentWorkflow().run(
            GenerateRequest(
                topic=args.topic,
                objective=args.objective,
                format=args.format,
                target_audience=args.audience,
                research_current_trends=not args.no_research,
            ),
            search_providers=args.search_provider or None,
        )
        return package.model_dump(mode="json")

    payload = asyncio.run(run())
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
