from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from xhs_skill.core.config import Settings
from xhs_skill.jobs.repository import JobRepository
from xhs_skill.jobs.service import JobService
from xhs_skill.schemas.common import JobStatus
from xhs_skill.streaming.broker import EventBroker

pytestmark = pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="TEST_REDIS_URL not set")


@pytest.mark.asyncio
async def test_redis_distributed_job_and_cross_instance_event_replay() -> None:
    prefix = f"xhs-test-{uuid4().hex}"
    settings = Settings(
        redis_url=os.environ["TEST_REDIS_URL"],
        redis_stream_prefix=prefix,
        redis_events_enabled=True,
        distributed_jobs_enabled=True,
        distributed_rate_limit_enabled=True,
        distributed_locks_enabled=True,
        job_worker_concurrency=4,
        job_worker_block_ms=100,
        job_queue_capacity=100,
    )
    repository = JobRepository(settings)
    broker = EventBroker(settings)
    service = JobService(repository=repository, broker=broker, settings=settings)
    worker = asyncio.create_task(service.run_worker("pytest-worker"))

    async def ignored(_):
        return {}

    job = await service.submit(
        "SEARCH_HOT_NOTES",
        {"query": "防晒", "time_range": "7d", "limit": 5, "sources": ["fixture"]},
        ignored,
    )
    loaded = None
    for _ in range(200):
        loaded = await repository.get(job.id)
        if loaded and loaded.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            break
        await asyncio.sleep(0.02)
    assert loaded is not None
    assert loaded.status == JobStatus.COMPLETED, loaded.error
    assert loaded.result and loaded.result["notes"]

    event_types: list[str] = []
    async for event in broker.subscribe(job.id, after_id=0, heartbeat_seconds=1):
        if event is not None:
            event_types.append(event.event_type)
    assert event_types[:2] == ["job.accepted", "job.started"]
    assert event_types[-1] == "job.completed"

    await service.shutdown()
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
