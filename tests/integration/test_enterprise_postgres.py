from __future__ import annotations

import os
from uuid import uuid4

import pytest

from xhs_skill.core.config import Settings
from xhs_skill.enterprise.postgres import EnterprisePostgresStore


@pytest.mark.asyncio
async def test_enterprise_postgres_rls_state_and_outbox() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 48,
        database_url=database_url,
    )
    store = EnterprisePostgresStore(settings)
    tenant_id = f"tenant-{uuid4().hex[:12]}"
    state_id = f"state-{uuid4().hex[:12]}"
    try:
        await store.migrate()
        assert await store.ping() is True
        await store.bootstrap_tenant(
            tenant_id,
            "Enterprise Integration",
            {"allowed_regions": ["global"], "publish_approval_quorum": 2},
        )
        created = await store.create_publish_state(
            tenant_id=tenant_id,
            state_id=state_id,
            account_id="account-1",
            draft_id="draft-1",
            state="DRAFT",
            payload={"status": "DRAFT"},
            content_hash="hash-1",
            fingerprint="fingerprint-1",
        )
        assert created["version"] == 1
        transitioned = await store.transition_publish_state(
            tenant_id=tenant_id,
            state_id=state_id,
            expected_version=1,
            from_states={"DRAFT"},
            to_state="APPROVED",
            payload={"status": "APPROVED"},
            outbox_event_type="publish.approved",
            idempotency_key=f"approve-{state_id}",
        )
        assert transitioned["state"] == "APPROVED"
        claimed = await store.claim_outbox(
            tenant_id=tenant_id,
            worker_id="test-worker",
            limit=10,
        )
        assert len(claimed) == 1
        await store.complete_outbox(tenant_id, int(claimed[0]["id"]))
    finally:
        await store.close()
