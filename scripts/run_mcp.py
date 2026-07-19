from __future__ import annotations

import argparse
import asyncio

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.mcp.server import run_stdio  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Skill 自带的 MCP stdio 服务")
    parser.add_argument("--transport", choices=["stdio"], default="stdio")
    parser.parse_args()
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
