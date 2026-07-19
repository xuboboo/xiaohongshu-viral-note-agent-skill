from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import PublishBlockedError
from xhs_skill.enterprise.postgres import EnterprisePostgresStore
from xhs_skill.schemas.publishing import (
    PublishApproval,
    PublishDraft,
    PublishResult,
    PublishSchedule,
)

if TYPE_CHECKING:
    from xhs_skill.publishing.service import PublishingService


class PostgresPublishCoordinator:
    """Cross-Pod persistent scheduler and publish state machine.

    Draft and approval snapshots are stored transactionally in PostgreSQL. Workers claim due
    schedules with SKIP LOCKED and a lease token, so only one Pod may execute a schedule.
    """

    def __init__(
        self,
        service: PublishingService,
        settings: Settings | None = None,
        store: EnterprisePostgresStore | None = None,
    ) -> None:
        self.service = service
        self.settings = settings or get_settings()
        self.store = store or EnterprisePostgresStore(self.settings)
        self._stop = asyncio.Event()

    async def schedule(
        self,
        draft: PublishDraft,
        approval: PublishApproval,
        scheduled_at: datetime,
    ) -> PublishSchedule:
        schedule_id = str(uuid4())
        fingerprint = await self.service._preflight(draft, approval)
        payload = {
            "schedule_id": schedule_id,
            "draft": draft.model_dump(mode="json"),
            "approval": approval.model_dump(mode="json", exclude={"approval_token"}),
            "enterprise_quorum_prevalidated": bool(approval.enterprise_approval_id),
            "enterprise_quorum_verified_at": datetime.now(UTC).isoformat(),
        }
        state = await self.store.create_publish_state(
            tenant_id=draft.tenant_id,
            state_id=schedule_id,
            account_id=draft.account_id,
            draft_id=draft.id,
            state="SCHEDULED",
            payload=payload,
            content_hash=draft.content_hash,
            fingerprint=fingerprint,
            scheduled_at=scheduled_at,
        )
        return PublishSchedule(
            id=str(state["id"]),
            tenant_id=draft.tenant_id,
            account_id=draft.account_id,
            draft_id=draft.id,
            approval_id=approval.id,
            scheduled_at=scheduled_at,
            status="SCHEDULED",
        )

    async def cancel(self, tenant_id: str, schedule_id: str) -> bool:
        return bool(await self.store.request_publish_cancel(tenant_id, schedule_id))

    async def _execute_state(self, tenant_id: str, row: dict[str, Any], worker_id: str) -> None:
        state_id = str(row["id"])
        lease_token = str(row["lease_token"])
        cancel_epoch = int(row.get("cancellation_epoch", 0))
        started = await self.store.start_claimed_publish(
            tenant_id, state_id, worker_id, lease_token
        )
        if started is None:
            return
        payload = dict(started["payload"])
        draft = PublishDraft.model_validate(payload["draft"])
        approval = PublishApproval.model_validate(payload["approval"])
        if approval.expires_at <= datetime.now(UTC):
            await self.store.finish_claimed_publish(
                tenant_id=tenant_id,
                state_id=state_id,
                worker_id=worker_id,
                lease_token=lease_token,
                final_state="FAILED",
                payload=payload,
                observed_cancel_epoch=cancel_epoch,
                error={"code": "APPROVAL_EXPIRED", "message": "Scheduled approval expired"},
            )
            return
        heartbeat_stop = asyncio.Event()

        async def heartbeat() -> None:
            while not heartbeat_stop.is_set():
                await asyncio.sleep(max(5, self.settings.scheduler_lease_seconds // 3))
                if heartbeat_stop.is_set():
                    return
                renewed = await self.store.heartbeat_publish_lease(
                    tenant_id,
                    state_id,
                    worker_id,
                    lease_token,
                    self.settings.scheduler_lease_seconds,
                )
                if not renewed:
                    return

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            # Cancellation is checked immediately before the irreversible submit call.
            if await self.store.publish_cancel_epoch(tenant_id, state_id) != cancel_epoch:
                raise asyncio.CancelledError
            await self.service._preflight(
                draft,
                approval,
                enterprise_quorum_prevalidated=bool(
                    payload.get("enterprise_quorum_prevalidated", False)
                ),
            )
            await self.service.publisher.prepare(draft)
            if await self.store.publish_cancel_epoch(tenant_id, state_id) != cancel_epoch:
                raise asyncio.CancelledError
            marked_submitting = await self.store.mark_publish_submitting(
                tenant_id=tenant_id,
                state_id=state_id,
                worker_id=worker_id,
                lease_token=lease_token,
                observed_cancel_epoch=cancel_epoch,
            )
            if not marked_submitting:
                raise PublishBlockedError(
                    "Publish lease, cancellation epoch or state changed before external submission"
                )
            result_payload = await self.service.publisher.submit(draft)
            result = PublishResult(
                job_id=state_id,
                draft_id=draft.id,
                account_id=draft.account_id,
                status="VERIFIED" if result_payload.get("verified") else "SUBMITTED_UNVERIFIED",
                note_url=result_payload.get("url"),
                note_id=result_payload.get("note_id"),
                published_at=datetime.now(UTC),
                audit={"distributed": True, "worker_id": worker_id},
            )
            if result.status == "VERIFIED" and (result.note_id or result.note_url):
                from xhs_skill.core.security import content_hash

                sync_note_id = result.note_id or content_hash(result.note_url or "")[:24]
                tasks = await self.service.post_publish_sync.enqueue_for_result(
                    tenant_id=draft.tenant_id,
                    account_id=draft.account_id,
                    note_id=sync_note_id,
                    note_url=result.note_url,
                )
                result.audit["post_publish_sync_task_ids"] = [task.id for task in tasks]
            completed = await self.store.finish_claimed_publish(
                tenant_id=tenant_id,
                state_id=state_id,
                worker_id=worker_id,
                lease_token=lease_token,
                final_state=result.status,
                payload={**payload, "result": result.model_dump(mode="json")},
                observed_cancel_epoch=cancel_epoch,
            )
            if not completed:
                await self.store.mark_publish_reconciliation(
                    tenant_id=tenant_id,
                    state_id=state_id,
                    worker_id=worker_id,
                    lease_token=lease_token,
                    payload={**payload, "result": result.model_dump(mode="json")},
                    error={
                        "code": "STATE_CHANGED_DURING_EXTERNAL_SUBMIT",
                        "message": "External submission may have succeeded; manual reconciliation is required",
                    },
                )
                return
        except asyncio.CancelledError:
            await self.store.finish_claimed_publish(
                tenant_id=tenant_id,
                state_id=state_id,
                worker_id=worker_id,
                lease_token=lease_token,
                final_state="CANCELLED",
                payload=payload,
                observed_cancel_epoch=cancel_epoch,
            )
        except Exception as exc:
            error = {"code": type(exc).__name__, "message": str(exc)}
            completed = await self.store.finish_claimed_publish(
                tenant_id=tenant_id,
                state_id=state_id,
                worker_id=worker_id,
                lease_token=lease_token,
                final_state="FAILED",
                payload=payload,
                observed_cancel_epoch=cancel_epoch,
                error=error,
            )
            if not completed:
                await self.store.mark_publish_reconciliation(
                    tenant_id=tenant_id,
                    state_id=state_id,
                    worker_id=worker_id,
                    lease_token=lease_token,
                    payload=payload,
                    error={
                        **error,
                        "reconciliation_reason": "Failure occurred at or after the external-submit boundary",
                    },
                )
        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

    async def run_worker(self, worker_id: str | None = None) -> None:
        worker = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        while not self._stop.is_set():
            claimed = 0
            for tenant_id in await self.store.list_tenant_ids():
                rows = await self.store.claim_due_schedules(
                    tenant_id=tenant_id,
                    worker_id=worker,
                    limit=self.settings.scheduler_claim_batch_size,
                    lease_seconds=self.settings.scheduler_lease_seconds,
                )
                claimed += len(rows)
                if rows:
                    await asyncio.gather(
                        *(self._execute_state(tenant_id, row, worker) for row in rows),
                        return_exceptions=True,
                    )
            if not claimed:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.settings.xhs_schedule_poll_seconds
                    )
                except TimeoutError:
                    pass

    async def stop(self) -> None:
        self._stop.set()
        await self.store.close()
