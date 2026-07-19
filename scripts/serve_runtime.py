from __future__ import annotations

import argparse

from _bootstrap import bootstrap

bootstrap()

import uvicorn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Skill 自带的高并发 HTTP/SSE/MCP/A2A 运行时")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    uvicorn.run(
        "xhs_skill.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=args.workers,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
