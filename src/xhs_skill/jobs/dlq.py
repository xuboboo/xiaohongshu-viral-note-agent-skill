from __future__ import annotations

from typing import Any

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.storage.redis_runtime import get_redis_runtime


class RedisDeadLetterQueue:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.runtime = get_redis_runtime(self.settings)
        self.job_stream = f"{self.settings.redis_stream_prefix}:jobs"
        self.dead_letter_stream = f"{self.settings.redis_stream_prefix}:jobs:dead-letter"

    async def list(self, *, count: int = 100, start: str = "-", end: str = "+") -> list[dict[str, Any]]:
        redis = await self.runtime.get()
        rows = await redis.xrange(self.dead_letter_stream, min=start, max=end, count=count)
        return [{"message_id": message_id, "fields": fields} for message_id, fields in rows]

    async def replay(self, message_id: str, *, delete_after: bool = True) -> str:
        redis = await self.runtime.get()
        rows = await redis.xrange(self.dead_letter_stream, min=message_id, max=message_id, count=1)
        if not rows:
            raise KeyError(message_id)
        _, fields = rows[0]
        required = {"job_id", "task_type", "input"}
        if not required.issubset(fields):
            raise ValueError("Dead-letter message is missing required job fields")
        new_id = await redis.xadd(
            self.job_stream,
            {
                "job_id": fields["job_id"],
                "task_type": fields["task_type"],
                "input": fields["input"],
                "attempt": "0",
                "enqueued_at": fields.get("failed_at", ""),
                "replayed_from": message_id,
            },
            maxlen=self.settings.job_queue_capacity,
            approximate=True,
        )
        if delete_after:
            await redis.xdel(self.dead_letter_stream, message_id)
        return str(new_id)

    async def delete(self, message_id: str) -> bool:
        redis = await self.runtime.get()
        return bool(await redis.xdel(self.dead_letter_stream, message_id))

    async def purge(self, *, max_count: int = 1000) -> int:
        redis = await self.runtime.get()
        rows = await redis.xrange(self.dead_letter_stream, min="-", max="+", count=max_count)
        if not rows:
            return 0
        return int(await redis.xdel(self.dead_letter_stream, *[message_id for message_id, _ in rows]))
