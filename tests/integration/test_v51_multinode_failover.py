from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from xhs_skill.core.config import Settings
from xhs_skill.enterprise.postgres import EnterprisePostgresStore
from xhs_skill.operations.models import PostPublishSyncTask


@pytest.mark.asyncio
async def test_postgres_schedule_outbox_and_sync_lease_failover() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 48,
        database_url=database_url,
        postgres_state_enabled=True,
        enterprise_worker_tenant_ids=[],
    )
    store = EnterprisePostgresStore(settings)
    tenant = f"tenant-{uuid4().hex[:10]}"
    try:
        await store.migrate()
        await store.bootstrap_tenant(tenant, "Failover", {})
        settings.enterprise_worker_tenant_ids = [tenant]
        assert await store.list_tenant_ids() == [tenant]
        state_id = f"state-{uuid4().hex[:10]}"
        await store.create_publish_state(
            tenant_id=tenant,
            state_id=state_id,
            account_id="account-1",
            draft_id="draft-1",
            state="SCHEDULED",
            payload={"draft": {}, "approval": {}},
            content_hash="hash",
            fingerprint=f"fingerprint-{uuid4().hex}",
            scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        first = await store.claim_due_schedules(
            tenant_id=tenant, worker_id="pod-a", limit=1, lease_seconds=1
        )
        assert len(first) == 1
        lease_token = str(first[0]["lease_token"])
        started = await store.start_claimed_publish(tenant, state_id, "pod-a", lease_token)
        assert started and started["state"] == "RUNNING"
        assert await store.claim_due_schedules(
            tenant_id=tenant, worker_id="pod-b", limit=1, lease_seconds=1
        ) == []
        await asyncio.sleep(1.1)
        recovered = await store.claim_due_schedules(
            tenant_id=tenant, worker_id="pod-b", limit=1, lease_seconds=30
        )
        assert len(recovered) == 1
        assert recovered[0]["lease_owner"] == "pod-b"
        assert recovered[0]["state"] == "CLAIMED"

        outbox_state_id = f"outbox-state-{uuid4().hex[:10]}"
        await store.create_publish_state(
            tenant_id=tenant,
            state_id=outbox_state_id,
            account_id="account-2",
            draft_id="draft-2",
            state="DRAFT",
            payload={"status": "DRAFT"},
            content_hash="hash-2",
            fingerprint=f"fingerprint-{uuid4().hex}",
        )
        await store.transition_publish_state(
            tenant_id=tenant,
            state_id=outbox_state_id,
            expected_version=1,
            from_states={"DRAFT"},
            to_state="APPROVED",
            payload={"status": "APPROVED"},
            outbox_event_type="publish.approved",
            idempotency_key=f"approve-{outbox_state_id}",
        )
        outbox_first = await store.claim_outbox_v2(
            tenant_id=tenant, worker_id="pod-a", limit=1, lease_seconds=1
        )
        assert len(outbox_first) == 1
        assert await store.claim_outbox_v2(
            tenant_id=tenant, worker_id="pod-b", limit=1, lease_seconds=1
        ) == []
        await asyncio.sleep(1.1)
        outbox_recovered = await store.claim_outbox_v2(
            tenant_id=tenant, worker_id="pod-b", limit=1, lease_seconds=30
        )
        assert len(outbox_recovered) == 1
        assert outbox_recovered[0]["locked_by"] == "pod-b"

        task = PostPublishSyncTask(
            tenant_id=tenant,
            account_id="account-1",
            note_id="note-1",
            due_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await store.enqueue_post_publish_sync(task)
        claimed = await store.claim_post_publish_sync(
            tenant_id=tenant, worker_id="pod-a", lease_seconds=1
        )
        assert len(claimed) == 1
        assert await store.claim_post_publish_sync(
            tenant_id=tenant, worker_id="pod-b", lease_seconds=1
        ) == []
        await asyncio.sleep(1.1)
        sync_recovered = await store.claim_post_publish_sync(
            tenant_id=tenant, worker_id="pod-b", lease_seconds=30
        )
        assert len(sync_recovered) == 1
        assert sync_recovered[0]["lease_owner"] == "pod-b"
    finally:
        await store.close()
