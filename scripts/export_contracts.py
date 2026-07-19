from __future__ import annotations

import asyncio
import json

import yaml
from _bootstrap import bootstrap

ROOT = bootstrap()

from xhs_skill.a2a.server import agent_card  # noqa: E402
from xhs_skill.api.app import create_app  # noqa: E402
from xhs_skill.mcp.tools import TOOL_DEFINITIONS  # noqa: E402


async def main() -> None:
    contracts = ROOT / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    openapi = create_app().openapi()
    (contracts / "openapi.json").write_text(
        json.dumps(openapi, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (contracts / "openapi.yaml").write_text(
        yaml.safe_dump(openapi, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (contracts / "mcp-tools.json").write_text(
        json.dumps(TOOL_DEFINITIONS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    from xhs_skill.ux.catalog import tools_list_meta  # noqa: E402

    (contracts / "mcp-tool-groups.json").write_text(
        json.dumps(
            tools_list_meta([str(t.get("name")) for t in TOOL_DEFINITIONS]),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (contracts / "a2a-agent-card.json").write_text(
        json.dumps(await agent_card(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "openapi_paths": len(openapi.get("paths", {})),
        "mcp_tools": len(TOOL_DEFINITIONS),
        "contracts": str(contracts),
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
