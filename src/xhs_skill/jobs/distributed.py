from __future__ import annotations

import asyncio
import json
import socket
from datetime import UTC, datetime
from uuid import uuid4

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import QueueFullError
from xhs_skill.jobs.handlers import TaskHandlerRegistry
from xhs_skill.jobs.models import Job
from xhs_skill.jobs.repository import JobRepository
from xhs_skill.schemas.common import JobStatus
from xhs_skill.storage.redis_runtime import get_redis_runtime
from xhs_skill.streaming.broker import EventBroker

_ENQUEUE_SCRIPT = """
local current = redis.call('XLEN', KEYS[1])
if current >= tonumber(ARGV[1]) then
  return false
end
return redis.call(
  'XADD', KEYS[1], '*',
  'job_id', ARGV[2],
  'task_type', ARGV[3],
  'input', ARGV[4],
  'attempt', ARGV[5],
  'enqueued_at', ARGV[6]
)
"""


class RedisDistributedJobQueue:
    """Durable Redis Streams queue with consumer groups, retries, and dead letters."""

    def __init__(
        self,
        repository: JobRepository,
        broker: EventBroker,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository
        self.broker = broker
        self.runtime = get_redis_runtime(self.settings)
        self.handlers = TaskHandlerRegistry()
        self.stream = f"{self.settings.redis_stream_prefix}:jobs"
        self.dead_letter_stream = f"{self.settings.redis_stream_prefix}:jobs:dead-letter"
        self.group = self.settings.redis_consumer_group
        self._stop = asyncio.Event()

    async def ensure_group(self) -> None:
        redis = await self.runtime.get()
        try:
            await redis.xgroup_create(self.stream, self.group, id="0-0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, job: Job, *, attempt: int = 0) -> str:
        redis = await self.runtime.get()
        message_id = await redis.eval(
            _ENQUEUE_SCRIPT,
            1,
            self.stream,
            self.settings.job_queue_capacity,
            job.id,
            job.task_type,
            json.dumps(job.input, ensure_ascii=False),
            attempt,
            datetime.now(UTC).isoformat(),
        )
        if not message_id:
            raise QueueFullError(
                "The distributed job queue is full",
                details={"capacity": self.settings.job_queue_capacity, "retry_after_seconds": 1},
            )
        return str(message_id)

    async def _finish_message(self, redis, message_id: str) -> None:
        """Acknowledge and delete completed entries so XLEN reflects live backlog."""
        pipe = redis.pipeline(transaction=True)
        pipe.xack(self.stream, self.group, message_id)
        pipe.xdel(self.stream, message_id)
        await pipe.execute()

    def _cancel_key(self, job_id: str) -> str:
        return f"{self.settings.redis_stream_prefix}:job-cancel:{job_id}"

    async def request_cancel(self, job_id: str) -> None:
        redis = await self.runtime.get()
        await redis.set(
            self._cancel_key(job_id),
            "1",
            ex=self.settings.redis_job_ttl_seconds,
        )

    async def _is_cancelled(self, redis, job_id: str) -> bool:
        return bool(await redis.exists(self._cancel_key(job_id)))

    async def _mark_cancelled(self, redis, job: Job, message_id: str) -> None:
        job.status = JobStatus.CANCELLED
        await self.repository.update(job)
        await self.broker.publish(job.id, "job.cancelled", trace_id=job.trace_id)
        await self._finish_message(redis, message_id)

    async def _process(
        self, message_id: str, fields: dict[str, str], semaphore: asyncio.Semaphore
    ) -> None:
        redis = await self.runtime.get()
        async with semaphore:
            job_id = fields["job_id"]
            attempt = int(fields.get("attempt", 0))
            job = await self.repository.get(job_id)
            if job is None or job.status in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                await self._finish_message(redis, message_id)
                return
            if await self._is_cancelled(redis, job_id):
                await self._mark_cancelled(redis, job, message_id)
                return
            job.status = JobStatus.RUNNING
            await self.repository.update(job)
            await self.broker.publish(
                job.id, "job.started", {"attempt": attempt}, trace_id=job.trace_id
            )
            try:
                payload = json.loads(fields.get("input", "{}"))
                execution = asyncio.create_task(
                    self.handlers.execute(fields["task_type"], payload, tenant_id=job.tenant_id),
                    name=f"distributed-job-{job.id}",
                )
                while not execution.done():
                    done, _ = await asyncio.wait({execution}, timeout=0.5)
                    if done:
                        break
                    if await self._is_cancelled(redis, job.id):
                        execution.cancel()
                        await asyncio.gather(execution, return_exceptions=True)
                        await self._mark_cancelled(redis, job, message_id)
                        return
                job.result = await execution
                if await self._is_cancelled(redis, job.id):
                    await self._mark_cancelled(redis, job, message_id)
                    return
                job.status = JobStatus.COMPLETED
                if not await self.repository.complete_if_not_cancelled(job):
                    job.status = JobStatus.CANCELLED
                    await self.broker.publish(job.id, "job.cancelled", trace_id=job.trace_id)
                    await self._finish_message(redis, message_id)
                    return
                await self.broker.publish(
                    job.id, "job.completed", job.result, trace_id=job.trace_id
                )
                await self._finish_message(redis, message_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if attempt < self.settings.job_max_retries:
                    job.status = JobStatus.PENDING
                    await self.repository.update(job)
                    await redis.xadd(
                        self.stream,
                        {
                            "job_id": job.id,
                            "task_type": fields["task_type"],
                            "input": fields.get("input", "{}"),
                            "attempt": attempt + 1,
                            "enqueued_at": datetime.now(UTC).isoformat(),
                        },
                    )
                    await self._finish_message(redis, message_id)
                    await self.broker.publish(
                        job.id,
                        "job.retry_scheduled",
                        {"attempt": attempt + 1, "error": str(exc)},
                        trace_id=job.trace_id,
                    )
                    return
                job.status = JobStatus.FAILED
                job.error = {
                    "code": getattr(exc, "code", type(exc).__name__),
                    "message": str(exc),
                    "details": getattr(exc, "details", {}),
                }
                await self.repository.update(job)
                await self.broker.publish(job.id, "job.failed", job.error, trace_id=job.trace_id)
                await redis.xadd(
                    self.dead_letter_stream,
                    {
                        **fields,
                        "failed_at": datetime.now(UTC).isoformat(),
                        "error": json.dumps(job.error, ensure_ascii=False),
                    },
                    maxlen=self.settings.job_dead_letter_capacity,
                    approximate=True,
                )
                await self._finish_message(redis, message_id)

    async def _claim_stale(self, consumer: str, count: int) -> list[tuple[str, dict[str, str]]]:
        redis = await self.runtime.get()
        try:
            response = await redis.xautoclaim(
                self.stream,
                self.group,
                consumer,
                min_idle_time=self.settings.job_visibility_timeout_ms,
                start_id="0-0",
                count=count,
            )
        except Exception:
            return []
        if not response or len(response) < 2:
            return []
        return list(response[1])

    async def run_worker(self, consumer_name: str | None = None) -> None:
        await self.ensure_group()
        redis = await self.runtime.get()
        consumer = consumer_name or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        semaphore = asyncio.Semaphore(self.settings.job_worker_concurrency)
        active: set[asyncio.Task[None]] = set()
        empty_polls = 0
        while not self._stop.is_set():
            active = {task for task in active if not task.done()}
            available = self.settings.job_worker_concurrency - len(active)
            if available <= 0:
                done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                active.difference_update(done)
                continue

            messages: list[tuple[str, dict[str, str]]] = []
            if empty_polls % 12 == 0:
                messages.extend(await self._claim_stale(consumer, available))
            if not messages:
                rows = await redis.xreadgroup(
                    groupname=self.group,
                    consumername=consumer,
                    streams={self.stream: ">"},
                    count=min(self.settings.job_worker_fetch_count, available),
                    block=self.settings.job_worker_block_ms,
                )
                for _, batch in rows or []:
                    messages.extend(batch)
            if not messages:
                empty_polls += 1
                continue
            empty_polls = 0
            for message_id, fields in messages[:available]:
                task = asyncio.create_task(self._process(message_id, fields, semaphore))
                active.add(task)
                task.add_done_callback(active.discard)
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    async def stop(self) -> None:
        self._stop.set()

    async def queue_depth(self) -> int:
        redis = await self.runtime.get()
        return int(await redis.xlen(self.stream))
