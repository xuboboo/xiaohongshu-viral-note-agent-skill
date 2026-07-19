from __future__ import annotations

import argparse
import asyncio
import json
import sys

from xhs_skill.core.auth import Principal
from xhs_skill.mcp.protocol import MCPProtocol


async def run_stdio() -> None:
    protocol = MCPProtocol()
    principal = Principal(
        subject="local-mcp",
        tenant_id="local",
        scopes=frozenset({"*"}),
        auth_level=2,
        token_id="stdio",
    )
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        try:
            message = json.loads(line)
            response = await protocol.handle(message, principal)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(exc)}},
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio"], default="stdio")
    parser.parse_args()
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
