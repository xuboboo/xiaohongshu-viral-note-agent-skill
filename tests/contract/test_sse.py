import pytest

from xhs_skill.streaming.broker import EventBroker


@pytest.mark.asyncio
async def test_event_replay_is_ordered():
    broker = EventBroker()
    await broker.publish("job", "job.started")
    await broker.publish("job", "job.completed", {"ok": True})
    events = broker.replay("job", 0)
    assert [event.event_id for event in events] == [1, 2]
    assert events[-1].payload == {"ok": True}
