from __future__ import annotations

import json
from typing import Any

from xhs_skill import __version__
from xhs_skill.core.auth import Principal
from xhs_skill.mcp.tools import TOOL_DEFINITIONS, TOOL_SCOPES, MCPToolService


class MCPProtocol:
    def __init__(self, tools: MCPToolService | None = None) -> None:
        self.tools = tools or MCPToolService()

    async def handle(
        self,
        message: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any] | None:
        method = message.get("method")
        id_ = message.get("id")
        if method == "initialize":
            result = {
                "protocolVersion": message.get("params", {}).get(
                    "protocolVersion", "2025-11-25"
                ),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "xiaohongshu-viral-note-agent-skill",
                    "version": __version__,
                },
            }
        elif method == "notifications/initialized":
            return None
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            from xhs_skill.ux.catalog import tools_list_meta

            allowed = [
                tool
                for tool in TOOL_DEFINITIONS
                if principal.has(*TOOL_SCOPES.get(str(tool.get("name")), ()))
            ]
            result = {
                "tools": allowed,
                "_meta": tools_list_meta([str(t.get("name")) for t in allowed]),
            }
        elif method == "tools/call":
            params = message.get("params", {})
            try:
                data = await self.tools.call(
                    str(params["name"]),
                    dict(params.get("arguments", {})),
                    principal,
                )
                result = {
                    "content": [
                        {"type": "text", "text": json.dumps(data, ensure_ascii=False)}
                    ],
                    "structuredContent": data,
                    "isError": False,
                }
            except PermissionError as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": id_,
                    "error": {"code": -32003, "message": str(exc)},
                }
            except Exception as exc:
                result = {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return {"jsonrpc": "2.0", "id": id_, "result": result}
