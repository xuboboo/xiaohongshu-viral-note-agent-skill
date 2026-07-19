from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.jobs.models import Job
from xhs_skill.schemas.common import JobStatus
from xhs_skill.storage.redis_runtime import get_redis_runtime


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create(self, job: Job) -> Job:
        async with self._lock:
            self._jobs[job.id] = job.model_copy(deep=True)
        return job

    async def get(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        return job.model_copy(deep=True) if job else None

    async def update(self, job: Job) -> Job:
        job.updated_at = datetime.now(UTC)
        async with self._lock:
            self._jobs[job.id] = job.model_copy(deep=True)
        return job


class RedisJobRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.runtime = get_redis_runtime(self.settings)

    def _key(self, job_id: str) -> str:
        return f"{self.settings.redis_stream_prefix}:job:{job_id}"

    def _cancel_key(self, job_id: str) -> str:
        return f"{self.settings.redis_stream_prefix}:job-cancel:{job_id}"

    async def create(self, job: Job) -> Job:
        redis = await self.runtime.get()
        await redis.set(
            self._key(job.id),
            job.model_dump_json(),
            ex=self.settings.redis_job_ttl_seconds,
            nx=True,
        )
        return job

    async def get(self, job_id: str) -> Job | None:
        redis = await self.runtime.get()
        raw = await redis.get(self._key(job_id))
        return Job.model_validate_json(raw) if raw else None

    async def update(self, job: Job) -> Job:
        redis = await self.runtime.get()
        job.updated_at = datetime.now(UTC)
        await redis.set(
            self._key(job.id),
            job.model_dump_json(),
            ex=self.settings.redis_job_ttl_seconds,
        )
        return job

    async def cancel(self, job: Job) -> bool:
        redis = await self.runtime.get()
        job.status = JobStatus.CANCELLED
        job.updated_at = datetime.now(UTC)
        script = """
        if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
        local current = cjson.decode(redis.call('GET', KEYS[1]))
        if current['status'] == 'COMPLETED' or current['status'] == 'FAILED' or current['status'] == 'CANCELLED' then
          return 0
        end
        redis.call('SET', KEYS[2], '1', 'EX', ARGV[2])
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
        return 1
        """
        result = await redis.eval(
            script,
            2,
            self._key(job.id),
            self._cancel_key(job.id),
            job.model_dump_json(),
            self.settings.redis_job_ttl_seconds,
        )
        return bool(result)

    async def complete_if_not_cancelled(self, job: Job) -> bool:
        redis = await self.runtime.get()
        job.updated_at = datetime.now(UTC)
        script = """
        if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
        local raw = redis.call('GET', KEYS[1])
        if not raw then return 0 end
        local current = cjson.decode(raw)
        if current['status'] == 'CANCELLED' then return 0 end
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
        return 1
        """
        result = await redis.eval(
            script,
            2,
            self._key(job.id),
            self._cancel_key(job.id),
            job.model_dump_json(),
            self.settings.redis_job_ttl_seconds,
        )
        return bool(result)

    async def close(self) -> None:
        return None


class JobRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if self.settings.redis_url and self.settings.distributed_jobs_enabled:
            self.backend: InMemoryJobRepository | RedisJobRepository = RedisJobRepository(
                self.settings
            )
        else:
            self.backend = InMemoryJobRepository()

    async def create(self, job: Job) -> Job:
        return await self.backend.create(job)

    async def get(self, job_id: str) -> Job | None:
        return await self.backend.get(job_id)

    async def update(self, job: Job) -> Job:
        return await self.backend.update(job)

    async def cancel(self, job: Job) -> bool:
        method = getattr(self.backend, "cancel", None)
        if method is None:
            job.status = JobStatus.CANCELLED
            await self.backend.update(job)
            return True
        return bool(await method(job))

    async def complete_if_not_cancelled(self, job: Job) -> bool:
        method = getattr(self.backend, "complete_if_not_cancelled", None)
        if method is None:
            current = await self.backend.get(job.id)
            if current is None or current.status == JobStatus.CANCELLED:
                return False
            await self.backend.update(job)
            return True
        return bool(await method(job))

    async def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if close is not None:
            await close()
