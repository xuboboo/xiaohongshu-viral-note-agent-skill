from __future__ import annotations

import json
from collections.abc import AsyncIterator

from xhs_skill.schemas.streaming import StreamEvent
from xhs_skill.streaming.broker import EventBroker


def encode_event(event: StreamEvent) -> dict[str, str]:
    return {
        "id": str(event.event_id),
        "event": event.event_type,
        "retry": "3000",
        "data": json.dumps(event.model_dump(mode="json"), ensure_ascii=False),
    }


async def event_stream(
    broker: EventBroker,
    job_id: str,
    after_id: int = 0,
) -> AsyncIterator[dict[str, str]]:
    async for event in broker.subscribe(job_id, after_id=after_id):
        if event is None:
            yield {"event": "heartbeat", "data": "{}"}
        else:
            yield encode_event(event)
