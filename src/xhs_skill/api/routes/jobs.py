from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from xhs_skill.api.dependencies import content_workflow, job_service
from xhs_skill.api.routes.research import HotNotesRequest, _run_search
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.jobs.dlq import RedisDeadLetterQueue
from xhs_skill.jobs.models import Job
from xhs_skill.schemas.content import GenerateRequest

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.post("/research/hot-notes", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
async def submit_hot_notes(
    request: HotNotesRequest,
    principal: Principal = Depends(require_scopes("jobs:write", "research:read")),
) -> Job:
    async def runner(_: Job) -> dict:
        report = await _run_search(request, principal)
        return report.model_dump(mode="json")

    return await job_service().submit(
        "SEARCH_HOT_NOTES",
        request.model_dump(mode="json"),
        runner,
        tenant_id=principal.tenant_id,
        created_by=principal.subject,
    )


@router.post("/content/generate", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
async def submit_generate(
    request: GenerateRequest,
    principal: Principal = Depends(require_scopes("jobs:write", "content:generate")),
) -> Job:
    async def runner(_: Job) -> dict:
        package = await content_workflow().run(request, tenant_id=principal.tenant_id)
        return package.model_dump(mode="json")

    return await job_service().submit(
        "CREATE_NOTE",
        request.model_dump(mode="json"),
        runner,
        tenant_id=principal.tenant_id,
        created_by=principal.subject,
    )


@router.get("/stats")
async def job_stats(
    _: Principal = Depends(require_scopes("jobs:read")),
) -> dict:
    return await job_service().async_stats()


async def _owned_job(job_id: str, principal: Principal) -> Job:
    job = await job_service().repository.get(job_id)
    if job is None or job.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/dead-letters")
async def list_dead_letters(
    count: int = 100,
    _: Principal = Depends(require_scopes("jobs:admin")),
) -> dict:
    if job_service().distributed is None:
        raise HTTPException(status_code=409, detail="Redis distributed jobs are not enabled")
    return {"items": await RedisDeadLetterQueue().list(count=min(max(count, 1), 1000))}


@router.post("/dead-letters/{message_id}/replay")
async def replay_dead_letter(
    message_id: str,
    _: Principal = Depends(require_scopes("jobs:admin")),
) -> dict:
    if job_service().distributed is None:
        raise HTTPException(status_code=409, detail="Redis distributed jobs are not enabled")
    return {"message_id": message_id, "replayed_as": await RedisDeadLetterQueue().replay(message_id)}


@router.delete("/dead-letters/{message_id}")
async def delete_dead_letter(
    message_id: str,
    _: Principal = Depends(require_scopes("jobs:admin")),
) -> dict:
    if job_service().distributed is None:
        raise HTTPException(status_code=409, detail="Redis distributed jobs are not enabled")
    return {"deleted": await RedisDeadLetterQueue().delete(message_id)}


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    principal: Principal = Depends(require_scopes("jobs:read")),
) -> Job:
    return await _owned_job(job_id, principal)


@router.get("/{job_id}/events")
async def events(
    job_id: str,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    principal: Principal = Depends(require_scopes("jobs:read")),
):
    await _owned_job(job_id, principal)
    try:
        after_id = int(last_event_id or 0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc
    if after_id < 0 or after_id > 2**63 - 1:
        raise HTTPException(status_code=400, detail="Last-Event-ID is out of range")

    async def generate():
        async for event in job_service().broker.subscribe(job_id, after_id=after_id):
            if event is None:
                yield ": heartbeat\n\n"
                continue
            data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            yield f"id: {event.event_id}\nevent: {event.event_type}\nretry: 3000\ndata: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{job_id}/cancel")
async def cancel(
    job_id: str,
    principal: Principal = Depends(require_scopes("jobs:write")),
) -> dict:
    await _owned_job(job_id, principal)
    return {"cancelled": await job_service().cancel(job_id)}
