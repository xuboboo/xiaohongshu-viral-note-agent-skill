from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from xhs_skill import __version__
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.mcp.tools import MCPToolService
from xhs_skill.ux.catalog import group_for, label_for


def _category(tool: str) -> str:
    return group_for(tool)


def _category_label(tool: str) -> str:
    return label_for(group_for(tool))


router = APIRouter(tags=["a2a"])
_tools = MCPToolService()
_TASK_TTL = timedelta(hours=1)
_MAX_TASKS = 1_000
_tasks: dict[str, dict[str, Any]] = {}
_task_lock = asyncio.Lock()

_SKILL_TO_TOOL = {
    "research-hot-notes": "search_hot_notes",
    "research-trends": "search_trending_topics",
    "analyze-hot-notes": "analyze_hot_notes",
    "generate-note": "generate_xhs_note",
    "account-analysis": "query_account_weight",
    "authorized-publishing": "create_publish_draft",
    "enterprise-controls": "get_enterprise_controls",
    "enterprise-budget": "get_enterprise_budget",
    "enterprise-approval-create": "create_enterprise_approval",
    "enterprise-approval-decide": "decide_enterprise_approval",
    "enterprise-audit-verify": "verify_enterprise_audit",
    "enterprise-dlp": "enterprise_dlp_scan",
}


def _validate_payload(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [10_000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 32:
        raise ValueError("A2A payload is too deep or complex")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError("Invalid A2A object key")
            _validate_payload(item, depth=depth + 1, budget=budget)
    elif isinstance(value, list):
        for item in value:
            _validate_payload(item, depth=depth + 1, budget=budget)
    elif isinstance(value, str) and len(value) > 1_000_000:
        raise ValueError("A2A string is too large")


def _now() -> datetime:
    return datetime.now(UTC)


async def _cleanup_tasks() -> None:
    now = _now()
    async with _task_lock:
        expired = [task_id for task_id, record in _tasks.items() if record["expires_at"] <= now]
        for task_id in expired:
            record = _tasks.pop(task_id, None)
            task = record.get("async_task") if record else None
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
        if len(_tasks) > _MAX_TASKS:
            ordered = sorted(_tasks.items(), key=lambda item: item[1]["created_at"])
            for task_id, record in ordered[: len(_tasks) - _MAX_TASKS]:
                task = record.get("async_task")
                if isinstance(task, asyncio.Task) and not task.done():
                    task.cancel()
                _tasks.pop(task_id, None)


@router.get("/.well-known/agent-card.json")
async def agent_card(
    _: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict[str, Any]:
    return {
        "name": "小红书爆款笔记生成 agent Skill",
        "description": (
            "研究公开热门内容、生成原创笔记、估算账号健康并执行经批准的发布流程。"
            "搜索质量自适应：同 query 质量记忆驱动扩词/重试/多源；"
            "低质量样本时自动注入边界约束，高质量时放宽缓存与扩词。"
        ),
        "version": __version__,
        "supportedInterfaces": [
            {"url": "/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
            {"url": "/a2a/stream", "protocolBinding": "JSONRPC+SSE", "protocolVersion": "1.0"},
        ],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "search_quality": {
                "adaptive": True,
                "memory": "per-query quality persisted under data/search_quality/",
                "features": [
                    "quality-driven expand/retry/TTL",
                    "provider priority exploration on poor quality",
                    "generation guards on poor/fair quality",
                    "confidence modulation on topic suggestions",
                    "quality delta tracking across searches",
                ],
                "ux_fields": [
                    "search_quality.score (0-100)",
                    "search_quality.label (good/fair/poor/empty)",
                    "search_quality.delta.score_delta",
                    "search_quality.guards.strength (none/soft/hard)",
                ],
            },
        },
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "skills": [
            {
                "id": key,
                "name": key,
                "description": f"[{_category_label(tool)}] Executes {tool}. Read ux.status → ux.summary → ux.next_step.",
                "tags": [_category(tool)],
            }
            for key, tool in _SKILL_TO_TOOL.items()
        ],
    }


def _arguments(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    metadata = params.get("metadata", {}) or {}
    skill_id = metadata.get("skill_id") or params.get("skill_id") or "generate-note"
    arguments = params.get("arguments")
    if isinstance(arguments, dict):
        return str(skill_id), arguments
    message = params.get("message", {}) or {}
    parts = message.get("parts", []) or []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("data"), dict):
            return str(skill_id), dict(part["data"])
    text = "\n".join(
        str(part.get("text", "")) for part in parts if isinstance(part, dict) and part.get("text")
    )
    return str(skill_id), {"topic": text or "小红书内容"}


async def _run_task(
    task_id: str,
    tool: str,
    arguments: dict[str, Any],
    principal: Principal,
) -> None:
    record = _tasks[task_id]
    task = record["task"]
    try:
        data = await _tools.call(tool, arguments, principal)
        task["status"] = {"state": "completed", "timestamp": _now().isoformat()}
        task["artifacts"] = [
            {
                "artifactId": str(uuid4()),
                "name": tool,
                "parts": [
                    {"kind": "data", "data": data},
                    {"kind": "text", "text": json.dumps(data, ensure_ascii=False)},
                ],
            }
        ]
    except asyncio.CancelledError:
        task["status"] = {"state": "canceled", "timestamp": _now().isoformat()}
        raise
    except Exception as exc:
        task["status"] = {
            "state": "failed",
            "timestamp": _now().isoformat(),
            "message": str(exc),
        }


async def _execute(payload: dict[str, Any], principal: Principal) -> dict[str, Any]:
    await _cleanup_tasks()
    method = payload.get("method")
    id_ = payload.get("id")
    if method in {"message/send", "tasks/send"}:
        params = payload.get("params", {}) or {}
        skill_id, arguments = _arguments(params)
        tool = _SKILL_TO_TOOL.get(skill_id)
        if not tool:
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": -32602, "message": f"Unknown skill: {skill_id}"},
            }
        task_id = str(uuid4())
        task: dict[str, Any] = {
            "id": task_id,
            "contextId": str(params.get("contextId") or uuid4()),
            "metadata": {"clientTaskId": str(params.get("id") or "")[:128]},
            "status": {"state": "working", "timestamp": _now().isoformat()},
            "artifacts": [],
        }
        record = {
            "task": task,
            "tenant_id": principal.tenant_id,
            "created_by": principal.subject,
            "created_at": _now(),
            "expires_at": _now() + _TASK_TTL,
            "async_task": None,
        }
        async with _task_lock:
            _tasks[task_id] = record
        async_task = asyncio.create_task(
            _run_task(task_id, tool, arguments, principal),
            name=f"a2a-{task_id}",
        )
        record["async_task"] = async_task
        await async_task
        return {"jsonrpc": "2.0", "id": id_, "result": task}
    if method == "tasks/get":
        task_id = str((payload.get("params") or {}).get("id", ""))
        found = _tasks.get(task_id)
        if not found or found["tenant_id"] != principal.tenant_id:
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": -32001, "message": "Task not found"},
            }
        return {"jsonrpc": "2.0", "id": id_, "result": found["task"]}
    if method == "tasks/cancel":
        task_id = str((payload.get("params") or {}).get("id", ""))
        found = _tasks.get(task_id)
        if not found or found["tenant_id"] != principal.tenant_id:
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "error": {"code": -32001, "message": "Task not found"},
            }
        cancel_task = found.get("async_task")
        if isinstance(cancel_task, asyncio.Task) and not cancel_task.done():
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
        return {"jsonrpc": "2.0", "id": id_, "result": found["task"]}
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


@router.post("/a2a")
async def a2a_endpoint(
    payload: dict[str, Any],
    principal: Principal = Depends(require_scopes("a2a:invoke")),
) -> dict[str, Any]:
    _validate_payload(payload)
    return await _execute(payload, principal)


@router.post("/a2a/stream")
async def a2a_stream(
    request: Request,
    principal: Principal = Depends(require_scopes("a2a:invoke")),
):
    payload = await request.json()
    _validate_payload(payload)

    async def stream():
        yield (
            "event: status\ndata: " + json.dumps({"state": "working"}, ensure_ascii=False) + "\n\n"
        )
        response = await _execute(payload, principal)
        yield "event: result\ndata: " + json.dumps(response, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
