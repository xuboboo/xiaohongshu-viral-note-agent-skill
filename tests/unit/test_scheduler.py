from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from xhs_skill.publishing.repository import PublishingRepository
from xhs_skill.publishing.scheduler import InProcessScheduler


@pytest.mark.asyncio
async def test_local_scheduler_executes_callback(tmp_path):
    called = asyncio.Event()

    async def callback(draft_id: str, approval_id: str, tenant_id: str, schedule_id: str):
        assert draft_id == "draft"
        assert approval_id == "approval"
        assert tenant_id == "local"
        assert schedule_id
        called.set()

    scheduler = InProcessScheduler(PublishingRepository(tmp_path))
    schedule = await scheduler.create(
        draft_id="draft",
        account_id="account",
        tenant_id="local",
        approval_id="approval",
        scheduled_at=datetime.now(UTC) + timedelta(milliseconds=20),
        callback=callback,
    )
    await asyncio.wait_for(called.wait(), timeout=1)
    await asyncio.sleep(0)
    saved = scheduler.repository.load_schedule(schedule.id)
    assert saved.status == "COMPLETED"
