from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from xhs_skill.publishing.repository import PublishingRepository
from xhs_skill.schemas.publishing import PublishSchedule

PublishCallback = Callable[[str, str, str, str], Awaitable[object]]


class InProcessScheduler:
    """Safe single-process scheduler.

    This scheduler intentionally does not claim cross-replica durability. v5.1.0 uses PostgreSQL for cross-Pod schedules; local mode keeps
    Redis scheduling because the previous Redis+local-JSON design could execute a schedule
    on a replica that did not own its draft. PostgreSQL-backed scheduling is planned for v4.1.
    """

    def __init__(self, repository: PublishingRepository) -> None:
        self.repository = repository
        self.tasks: dict[str, asyncio.Task[None]] = {}

    async def create(
        self,
        *,
        draft_id: str,
        account_id: str,
        tenant_id: str,
        approval_id: str,
        scheduled_at: datetime,
        callback: PublishCallback,
    ) -> PublishSchedule:
        if scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone")
        schedule = PublishSchedule(
            id=str(uuid4()),
            draft_id=draft_id,
            account_id=account_id,
            tenant_id=tenant_id,
            approval_id=approval_id,
            scheduled_at=scheduled_at,
        )
        self.repository.save_schedule(schedule)
        self.tasks[schedule.id] = asyncio.create_task(self._run(schedule, callback))
        return schedule

    async def _run(self, schedule: PublishSchedule, callback: PublishCallback) -> None:
        delay = max(
            0.0, (schedule.scheduled_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        )
        try:
            await asyncio.sleep(delay)
            await callback(schedule.draft_id, schedule.approval_id, schedule.tenant_id, schedule.id)
            schedule.status = "COMPLETED"
        except asyncio.CancelledError:
            schedule.status = "CANCELLED"
            raise
        except Exception as exc:
            schedule.status = "FAILED"
            schedule.failure_message = str(exc)
        finally:
            self.repository.save_schedule(schedule)
            self.tasks.pop(schedule.id, None)

    async def cancel(self, schedule_id: str, tenant_id: str = "local") -> bool:
        task = self.tasks.get(schedule_id)
        if not task or task.done():
            return False
        task.cancel()
        schedule = self.repository.load_schedule(schedule_id, tenant_id)
        schedule.status = "CANCELLED"
        self.repository.save_schedule(schedule)
        return True

    async def stop(self) -> None:
        active = list(self.tasks.values())
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
