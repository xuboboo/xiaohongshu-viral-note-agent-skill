from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.schemas.streaming import StreamEvent
from xhs_skill.storage.redis_runtime import get_redis_runtime

_TERMINAL_EVENTS = {"job.completed", "job.failed", "job.cancelled"}


class InMemoryEventBroker:
    """Process-local SSE broker with bounded replay and subscriber wake-up."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._events: dict[str, deque[StreamEvent]] = defaultdict(
            lambda: deque(maxlen=self.settings.sse_retention_events)
        )
        self._conditions: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        self._sequence: dict[str, int] = defaultdict(int)
        self._publish_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._terminal_at: dict[str, float] = {}
        self._subscribers: dict[str, int] = defaultdict(int)
        self._operations = 0


    def _cleanup(self, *, force: bool = False) -> None:
        self._operations += 1
        if not force and self._operations % 100:
            return
        cutoff = time.monotonic() - self.settings.redis_event_ttl_seconds
        expired = [
            job_id
            for job_id, terminal_at in self._terminal_at.items()
            if terminal_at <= cutoff and self._subscribers.get(job_id, 0) == 0
        ]
        for job_id in expired:
            self._events.pop(job_id, None)
            self._conditions.pop(job_id, None)
            self._sequence.pop(job_id, None)
            self._publish_locks.pop(job_id, None)
            self._terminal_at.pop(job_id, None)
            self._subscribers.pop(job_id, None)

    async def publish(
        self,
        job_id: str,
        event_type: str,
        payload: dict | None = None,
        *,
        trace_id: str | None = None,
    ) -> StreamEvent:
        self._cleanup()
        async with self._publish_locks[job_id]:
            self._sequence[job_id] += 1
            sequence = self._sequence[job_id]
            event = StreamEvent(
                event_id=sequence,
                event_type=event_type,
                job_id=job_id,
                sequence=sequence,
                payload=payload or {},
                trace_id=trace_id or str(uuid4()),
            )
            self._events[job_id].append(event)
            if event_type in _TERMINAL_EVENTS:
                self._terminal_at[job_id] = time.monotonic()
        async with self._conditions[job_id]:
            self._conditions[job_id].notify_all()
        return event

    def replay(self, job_id: str, after_id: int = 0) -> list[StreamEvent]:
        self._cleanup()
        return [event for event in self._events.get(job_id, ()) if event.event_id > after_id]

    async def subscribe(
        self,
        job_id: str,
        *,
        after_id: int = 0,
        heartbeat_seconds: int | None = None,
    ) -> AsyncIterator[StreamEvent | None]:
        heartbeat = heartbeat_seconds or self.settings.sse_heartbeat_seconds
        cursor = after_id
        self._subscribers[job_id] += 1
        try:
            while True:
                events = self.replay(job_id, cursor)
                if events:
                    for event in events:
                        cursor = event.event_id
                        yield event
                        if event.event_type in _TERMINAL_EVENTS:
                            return
                    continue
                try:
                    async with self._conditions[job_id]:
                        await asyncio.wait_for(
                            self._conditions[job_id].wait(), timeout=heartbeat
                        )
                except TimeoutError:
                    yield None
        finally:
            self._subscribers[job_id] = max(0, self._subscribers[job_id] - 1)
            self._cleanup(force=True)


class RedisStreamsEventBroker:
    """Cross-instance broker using one capped Redis Stream per job."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.runtime = get_redis_runtime(self.settings)

    def _stream(self, job_id: str) -> str:
        return f"{self.settings.redis_stream_prefix}:events:{job_id}"

    def _sequence_key(self, job_id: str) -> str:
        return f"{self.settings.redis_stream_prefix}:events-sequence:{job_id}"

    async def publish(
        self,
        job_id: str,
        event_type: str,
        payload: dict | None = None,
        *,
        trace_id: str | None = None,
    ) -> StreamEvent:
        redis = await self.runtime.get()
        sequence = int(await redis.incr(self._sequence_key(job_id)))
        event = StreamEvent(
            event_id=sequence,
            event_type=event_type,
            job_id=job_id,
            sequence=sequence,
            payload=payload or {},
            trace_id=trace_id or str(uuid4()),
        )
        key = self._stream(job_id)
        fields = {"event": event.model_dump_json()}
        await redis.xadd(
            key,
            fields,
            id=f"{sequence}-0",
            maxlen=self.settings.sse_retention_events,
            approximate=True,
        )
        ttl = self.settings.redis_event_ttl_seconds
        await redis.expire(key, ttl)
        await redis.expire(self._sequence_key(job_id), ttl)
        return event

    def replay(self, job_id: str, after_id: int = 0) -> list[StreamEvent]:
        raise RuntimeError("Use async subscribe() for Redis-backed replay")

    async def _read_range(self, job_id: str, after_id: int) -> list[StreamEvent]:
        redis = await self.runtime.get()
        key = self._stream(job_id)
        rows = await redis.xrange(key, min=f"({after_id}-0", max="+", count=500)
        return [StreamEvent.model_validate_json(fields["event"]) for _, fields in rows]

    async def subscribe(
        self,
        job_id: str,
        *,
        after_id: int = 0,
        heartbeat_seconds: int | None = None,
    ) -> AsyncIterator[StreamEvent | None]:
        redis = await self.runtime.get()
        heartbeat = heartbeat_seconds or self.settings.sse_heartbeat_seconds
        cursor = after_id
        key = self._stream(job_id)
        while True:
            events = await self._read_range(job_id, cursor)
            if events:
                for event in events:
                    cursor = event.event_id
                    yield event
                    if event.event_type in _TERMINAL_EVENTS:
                        return
                continue
            rows = await redis.xread(
                streams={key: f"{cursor}-0"},
                count=100,
                block=int(heartbeat * 1000),
            )
            if not rows:
                yield None
                continue
            for _, messages in rows:
                for _, fields in messages:
                    event = StreamEvent.model_validate_json(fields["event"])
                    if event.event_id <= cursor:
                        continue
                    cursor = event.event_id
                    yield event
                    if event.event_type in _TERMINAL_EVENTS:
                        return

    async def close(self) -> None:
        return None


class EventBroker:
    """Backend-selecting facade kept stable for callers and tests."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.backend: InMemoryEventBroker | RedisStreamsEventBroker
        if self.settings.redis_url and self.settings.redis_events_enabled:
            self.backend = RedisStreamsEventBroker(self.settings)
        else:
            self.backend = InMemoryEventBroker(self.settings)

    async def publish(self, *args: Any, **kwargs: Any) -> StreamEvent:
        return await self.backend.publish(*args, **kwargs)

    def replay(self, job_id: str, after_id: int = 0) -> list[StreamEvent]:
        return self.backend.replay(job_id, after_id)

    def subscribe(self, *args: Any, **kwargs: Any) -> AsyncIterator[StreamEvent | None]:
        return self.backend.subscribe(*args, **kwargs)

    async def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if close is not None:
            await close()
