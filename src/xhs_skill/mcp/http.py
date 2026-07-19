from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.core.config import get_settings
from xhs_skill.mcp.protocol import MCPProtocol

router = APIRouter(prefix="/mcp", tags=["mcp"])
protocol = MCPProtocol()


def _validate_origin(origin: str | None) -> None:
    if not origin:
        return
    allowed = {
        item.strip()
        for item in get_settings().mcp_allowed_origins.split(",")
        if item.strip()
    }
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def _validate_json_shape(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [10_000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 32:
        raise HTTPException(status_code=400, detail="JSON payload is too deep or complex")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise HTTPException(status_code=400, detail="Invalid JSON object key")
            _validate_json_shape(item, depth=depth + 1, budget=budget)
    elif isinstance(value, list):
        for item in value:
            _validate_json_shape(item, depth=depth + 1, budget=budget)
    elif isinstance(value, str) and len(value) > 1_000_000:
        raise HTTPException(status_code=400, detail="JSON string is too large")


@router.post("")
async def mcp_post(
    request: Request,
    origin: str | None = Header(default=None),
    accept: str | None = Header(default=None),
    principal: Principal = Depends(require_scopes("mcp:invoke")),
):
    _validate_origin(origin)
    try:
        message = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    _validate_json_shape(message)
    response = await protocol.handle(message, principal)
    if response is None:
        return JSONResponse(status_code=202, content={})
    if accept and "text/event-stream" in accept:

        async def stream():
            yield f"event: message\ndata: {json.dumps(response, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return JSONResponse(response)


@router.get("")
async def mcp_get(
    origin: str | None = Header(default=None),
    _: Principal = Depends(require_scopes("mcp:invoke")),
):
    _validate_origin(origin)

    async def stream():
        yield ": connected\n\n"
        yield 'event: server.info\ndata: {"name":"xiaohongshu-viral-note-agent-skill"}\n\n'

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
