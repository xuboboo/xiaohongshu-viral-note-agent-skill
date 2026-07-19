from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import QueueFullError
from xhs_skill.jobs.distributed import RedisDistributedJobQueue
from xhs_skill.jobs.models import Job
from xhs_skill.jobs.repository import JobRepository
from xhs_skill.schemas.common import JobStatus
from xhs_skill.streaming.broker import EventBroker

JobRunner = Callable[[Job], Awaitable[dict[str, Any]]]


class JobService:
    """Bounded in-process worker pool.

    This avoids one asyncio task per incoming request. For multi-instance deployments,
    configure Redis-backed events and run API replicas behind a load balancer; jobs remain
    bounded per replica. The public task contract is deliberately serializable so a Temporal
    or Redis Streams dispatcher can replace this worker pool without changing the API.
    """

    def __init__(
        self,
        repository: JobRepository | None = None,
        broker: EventBroker | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or JobRepository()
        self.broker = broker or EventBroker(self.settings)
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.settings.job_queue_capacity)
        self._runners: dict[str, JobRunner] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._active_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._cancelled: set[str] = set()
        self._start_lock = asyncio.Lock()
        self._closed = False
        self.distributed = (
            RedisDistributedJobQueue(self.repository, self.broker, self.settings)
            if self.settings.redis_url and self.settings.distributed_jobs_enabled
            else None
        )

    async def _ensure_workers(self) -> None:
        if self.distributed is not None:
            return
        if self._workers or self._closed:
            return
        async with self._start_lock:
            if self._workers or self._closed:
                return
            self._workers = [
                asyncio.create_task(self._worker(index), name=f"xhs-job-worker-{index}")
                for index in range(self.settings.job_worker_concurrency)
            ]

    async def submit(
        self,
        task_type: str,
        input_: dict,
        runner: JobRunner,
        *,
        tenant_id: str = "local",
        created_by: str = "local-cli",
    ) -> Job:
        await self._ensure_workers()
        if self._closed:
            raise QueueFullError("Job service is shutting down")
        job = await self.repository.create(
            Job(task_type=task_type, input=input_, tenant_id=tenant_id, created_by=created_by)
        )
        backend = "redis-streams" if self.distributed is not None else "bounded-memory"
        await self.broker.publish(
            job.id,
            "job.accepted",
            {"task_type": task_type, "backend": backend},
            trace_id=job.trace_id,
        )
        if self.distributed is not None:
            try:
                await self.distributed.enqueue(job)
            except QueueFullError:
                job.status = JobStatus.FAILED
                job.error = {
                    "code": "JOB_QUEUE_FULL",
                    "message": "The distributed job queue is full",
                }
                await self.repository.update(job)
                await self.broker.publish(job.id, "job.failed", job.error, trace_id=job.trace_id)
                raise
            return job

        self._runners[job.id] = runner
        try:
            async with asyncio.timeout(self.settings.job_enqueue_timeout_seconds):
                await self._queue.put(job.id)
        except TimeoutError as exc:
            self._runners.pop(job.id, None)
            job.status = JobStatus.FAILED
            job.error = {
                "code": "JOB_QUEUE_FULL",
                "message": "The job queue is full",
                "details": {"capacity": self.settings.job_queue_capacity},
            }
            await self.repository.update(job)
            await self.broker.publish(job.id, "job.failed", job.error, trace_id=job.trace_id)
            raise QueueFullError(
                "The job queue is full",
                details={"capacity": self.settings.job_queue_capacity, "retry_after_seconds": 1},
            ) from exc
        return job

    async def _worker(self, _: int) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if job_id in self._cancelled:
                    self._cancelled.discard(job_id)
                    continue
                job = await self.repository.get(job_id)
                runner = self._runners.pop(job_id, None)
                if job is None or runner is None:
                    continue
                await self._execute(job, runner)
            finally:
                self._queue.task_done()

    async def _execute(self, job: Job, runner: JobRunner) -> None:
        job.status = JobStatus.RUNNING
        await self.repository.update(job)
        await self.broker.publish(job.id, "job.started", trace_id=job.trace_id)

        async def invoke() -> dict[str, Any]:
            return await runner(job)

        task: asyncio.Task[dict[str, Any]] = asyncio.create_task(invoke(), name=f"xhs-job-{job.id}")
        self._active_tasks[job.id] = task
        try:
            job.result = await task
            job.status = JobStatus.COMPLETED
            await self.repository.update(job)
            await self.broker.publish(job.id, "job.completed", job.result, trace_id=job.trace_id)
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            await self.repository.update(job)
            await self.broker.publish(job.id, "job.cancelled", trace_id=job.trace_id)
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = {
                "code": getattr(exc, "code", type(exc).__name__),
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
            await self.repository.update(job)
            await self.broker.publish(job.id, "job.failed", job.error, trace_id=job.trace_id)
        finally:
            self._active_tasks.pop(job.id, None)

    async def cancel(self, job_id: str) -> bool:
        if self.distributed is not None:
            job = await self.repository.get(job_id)
            if job is None or job.status in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                return False
            await self.distributed.request_cancel(job_id)
            cancelled = await self.repository.cancel(job)
            if cancelled:
                await self.broker.publish(job.id, "job.cancelled", trace_id=job.trace_id)
            return cancelled
        task = self._active_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        job = await self.repository.get(job_id)
        if job and job.status == JobStatus.PENDING and job_id in self._runners:
            self._cancelled.add(job_id)
            self._runners.pop(job_id, None)
            job.status = JobStatus.CANCELLED
            await self.repository.update(job)
            await self.broker.publish(job.id, "job.cancelled", trace_id=job.trace_id)
            return True
        return False

    def stats(self) -> dict[str, int]:
        return {
            "queue_depth": self._queue.qsize() if self.distributed is None else -1,
            "queue_capacity": self.settings.job_queue_capacity,
            "workers": len(self._workers),
            "active_jobs": len(self._active_tasks),
            "distributed": int(self.distributed is not None),
        }

    async def async_stats(self) -> dict[str, int]:
        stats = self.stats()
        if self.distributed is not None:
            stats["queue_depth"] = await self.distributed.queue_depth()
        return stats

    async def run_worker(self, consumer_name: str | None = None) -> None:
        if self.distributed is None:
            raise RuntimeError("Distributed jobs are not enabled")
        await self.distributed.run_worker(consumer_name)

    async def shutdown(self) -> None:
        self._closed = True
        if self.distributed is not None:
            await self.distributed.stop()
            return
        try:
            async with asyncio.timeout(self.settings.graceful_shutdown_seconds):
                await self._queue.join()
        except TimeoutError:
            pass
        for task in self._active_tasks.values():
            task.cancel()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
