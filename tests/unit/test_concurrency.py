from __future__ import annotations

import asyncio

import pytest

from xhs_skill.core.config import Settings
from xhs_skill.core.errors import CircuitOpenError, OverloadedError
from xhs_skill.core.resilience import Bulkhead, CircuitBreaker, LocalTokenBucket
from xhs_skill.jobs.service import JobService
from xhs_skill.schemas.common import JobStatus
from xhs_skill.streaming.broker import EventBroker


@pytest.mark.asyncio
async def test_bulkhead_rejects_beyond_active_and_waiter_capacity() -> None:
    bulkhead = Bulkhead("test", max_active=1, max_waiters=1, wait_timeout=1)
    release = asyncio.Event()
    entered = asyncio.Event()

    async def first() -> None:
        async with bulkhead.slot():
            entered.set()
            await release.wait()

    task = asyncio.create_task(first())
    await entered.wait()
    queued = asyncio.create_task(_hold_slot(bulkhead, release))
    await asyncio.sleep(0)
    with pytest.raises(OverloadedError):
        async with bulkhead.slot():
            pass
    release.set()
    await asyncio.gather(task, queued)
    assert bulkhead.active == 0
    assert bulkhead.waiters == 0


async def _hold_slot(bulkhead: Bulkhead, release: asyncio.Event) -> None:
    async with bulkhead.slot():
        await release.wait()


@pytest.mark.asyncio
async def test_local_token_bucket_refills() -> None:
    bucket = LocalTokenBucket(rate=100, burst=2)
    assert (await bucket.consume("tenant"))[0]
    assert (await bucket.consume("tenant"))[0]
    allowed, _, retry = await bucket.consume("tenant")
    assert not allowed
    assert retry > 0
    await asyncio.sleep(0.02)
    assert (await bucket.consume("tenant"))[0]


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(
        "provider", failure_threshold=2, recovery_seconds=0.01, window_seconds=1
    )
    await breaker.record_failure()
    await breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        await breaker.before_call()
    await asyncio.sleep(0.02)
    await breaker.before_call()
    await breaker.record_success()
    await breaker.before_call()


@pytest.mark.asyncio
async def test_concurrent_event_publication_has_unique_sequence() -> None:
    settings = Settings(redis_url=None, redis_events_enabled=False, sse_retention_events=1000)
    broker = EventBroker(settings)
    events = await asyncio.gather(
        *(broker.publish("job", "rank.updated", {"index": index}) for index in range(200))
    )
    ids = sorted(event.event_id for event in events)
    assert ids == list(range(1, 201))
    assert [event.event_id for event in broker.replay("job")] == list(range(1, 201))


@pytest.mark.asyncio
async def test_job_service_never_exceeds_worker_concurrency() -> None:
    settings = Settings(
        redis_url=None,
        distributed_jobs_enabled=False,
        redis_events_enabled=False,
        job_worker_concurrency=4,
        job_queue_capacity=100,
        graceful_shutdown_seconds=2,
    )
    service = JobService(settings=settings)
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def runner(job):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return {"job_id": job.id}

    jobs = [await service.submit("TEST", {"i": i}, runner) for i in range(30)]
    for _ in range(200):
        loaded = [await service.repository.get(job.id) for job in jobs]
        if all(item and item.status == JobStatus.COMPLETED for item in loaded):
            break
        await asyncio.sleep(0.01)
    assert peak <= 4
    final_jobs = [await service.repository.get(job.id) for job in jobs]
    assert all(item and item.status == JobStatus.COMPLETED for item in final_jobs)
    event_types = [event.event_type for event in service.broker.replay(jobs[0].id)]
    assert event_types == ["job.accepted", "job.started", "job.completed"]
    await service.shutdown()


@pytest.mark.asyncio
async def test_many_sse_subscribers_receive_terminal_event() -> None:
    settings = Settings(redis_url=None, redis_events_enabled=False, sse_retention_events=100)
    broker = EventBroker(settings)

    async def collect() -> list[str]:
        values: list[str] = []
        async for event in broker.subscribe("fanout", heartbeat_seconds=1):
            if event is not None:
                values.append(event.event_type)
        return values

    subscribers = [asyncio.create_task(collect()) for _ in range(100)]
    await asyncio.sleep(0)
    await broker.publish("fanout", "job.started")
    await broker.publish("fanout", "job.completed", {"ok": True})
    results = await asyncio.gather(*subscribers)
    assert all(value == ["job.started", "job.completed"] for value in results)


@pytest.mark.asyncio
async def test_bounded_job_queue_fails_fast_when_full() -> None:
    from xhs_skill.core.errors import QueueFullError

    settings = Settings(
        redis_url=None,
        distributed_jobs_enabled=False,
        redis_events_enabled=False,
        job_worker_concurrency=1,
        job_queue_capacity=1,
        job_enqueue_timeout_seconds=0.01,
        graceful_shutdown_seconds=0.05,
    )
    service = JobService(settings=settings)
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow(job):
        started.set()
        await release.wait()
        return {"job_id": job.id}

    await service.submit("TEST", {}, slow)
    await started.wait()
    await service.submit("TEST", {}, slow)
    with pytest.raises(QueueFullError):
        await service.submit("TEST", {}, slow)
    release.set()
    await service.shutdown()
