from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from xhs_skill.operations.models import (
        AssetRecord,
        ContentCalendarItem,
        Experiment,
        ExperimentAssignment,
        ExperimentOutcome,
        PostPublishSyncTask,
        PublishedMetrics,
        Retrospective,
        SeriesPlan,
    )
    from xhs_skill.schemas.account import AccountProfile, AccountWeightSnapshot

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import validate_identifier

_SHARED_POOLS: dict[tuple[str, int], dict[str, Any]] = {}
_SHARED_POOL_LOCKS: dict[tuple[str, int], asyncio.Lock] = {}


def _pool_key(database_url: str) -> tuple[str, int]:
    return database_url, id(asyncio.get_running_loop())


class EnterprisePostgresStore:
    """PostgreSQL state store with RLS tenant binding, optimistic concurrency and outbox."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.pool = None
        self._shared_pool_key: tuple[str, int] | None = None

    def _require_pool(self) -> Any:
        if self.pool is None:
            raise RuntimeError("PostgreSQL pool is not initialized")
        return self.pool

    async def connect(self) -> None:
        if self.pool is not None:
            return
        if not self.settings.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be PostgreSQL for enterprise state")
        try:
            import asyncpg
        except ImportError as exc:
            raise RuntimeError("Install the postgres optional dependency") from exc
        key = _pool_key(self.settings.database_url)
        lock = _SHARED_POOL_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            entry = _SHARED_POOLS.get(key)
            if entry is None:
                pool = await asyncpg.create_pool(
                    self.settings.database_url,
                    min_size=2,
                    max_size=min(100, max(4, self.settings.uvicorn_workers * 8)),
                    command_timeout=self.settings.request_timeout_seconds,
                    max_inactive_connection_lifetime=300,
                )
                entry = {"pool": pool, "references": 0}
                _SHARED_POOLS[key] = entry
            entry["references"] = int(entry["references"]) + 1
            self.pool = entry["pool"]
            self._shared_pool_key = key

    async def close(self) -> None:
        key = self._shared_pool_key
        if key is None:
            self.pool = None
            return
        lock = _SHARED_POOL_LOCKS.setdefault(key, asyncio.Lock())
        pool_to_close = None
        async with lock:
            entry = _SHARED_POOLS.get(key)
            if entry is not None:
                entry["references"] = max(0, int(entry["references"]) - 1)
                if int(entry["references"]) == 0:
                    pool_to_close = entry["pool"]
                    _SHARED_POOLS.pop(key, None)
                    _SHARED_POOL_LOCKS.pop(key, None)
            self.pool = None
            self._shared_pool_key = None
        if pool_to_close is not None:
            await pool_to_close.close()

    async def ping(self) -> bool:
        await self.connect()
        pool = self._require_pool()
        return bool(await pool.fetchval("SELECT TRUE"))

    async def migrate(self, migration_path: Path | None = None) -> None:
        await self.connect()
        if migration_path is not None:
            migrations = [migration_path.read_text(encoding="utf-8")]
        else:
            migrations = [
                files("xhs_skill").joinpath(resource).read_text(encoding="utf-8")
                for resource in (
                    "resources/0003_enterprise_v5.sql",
                    "resources/0004_consistency_intelligence_operations.sql",
                )
            ]
        pool = self._require_pool()
        async with pool.acquire() as connection:
            for sql in migrations:
                await connection.execute(sql)

    @asynccontextmanager
    async def tenant_transaction(self, tenant_id: str) -> AsyncIterator[Any]:
        await self.connect()
        safe_tenant = validate_identifier(tenant_id, field="tenant_id")
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT set_config('app.tenant_id', $1, true)", safe_tenant)
                yield connection

    async def bootstrap_tenant(self, tenant_id: str, display_name: str, policy: dict[str, Any]) -> None:
        async with self.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                """
                INSERT INTO enterprise_tenants(id, display_name, status, plan, policy)
                VALUES($1, $2, 'ACTIVE', 'ENTERPRISE', $3::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    display_name = excluded.display_name,
                    policy = excluded.policy,
                    updated_at = now()
                """,
                tenant_id,
                display_name,
                json.dumps(policy),
            )

    async def create_publish_state(
        self,
        *,
        tenant_id: str,
        state_id: str,
        account_id: str,
        draft_id: str,
        state: str,
        payload: dict[str, Any],
        content_hash: str,
        fingerprint: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO enterprise_publish_state(
                    tenant_id, id, account_id, draft_id, state, payload,
                    content_hash, publish_fingerprint, scheduled_at
                ) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9)
                ON CONFLICT (tenant_id, account_id, publish_fingerprint)
                DO UPDATE SET updated_at=enterprise_publish_state.updated_at
                RETURNING *
                """,
                tenant_id,
                state_id,
                account_id,
                draft_id,
                state,
                json.dumps(payload),
                content_hash,
                fingerprint,
                scheduled_at,
            )
            return dict(row)

    async def transition_publish_state(
        self,
        *,
        tenant_id: str,
        state_id: str,
        expected_version: int,
        from_states: set[str],
        to_state: str,
        payload: dict[str, Any],
        outbox_event_type: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                UPDATE enterprise_publish_state
                SET state=$4, payload=$5::jsonb, version=version+1, updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND version=$3 AND state = ANY($6::text[])
                RETURNING *
                """,
                tenant_id,
                state_id,
                expected_version,
                to_state,
                json.dumps(payload),
                list(from_states),
            )
            if row is None:
                raise RuntimeError("Publish state transition conflict")
            await connection.execute(
                """
                INSERT INTO enterprise_outbox(
                    tenant_id, aggregate_type, aggregate_id, event_type,
                    payload, idempotency_key
                ) VALUES($1,'publish',$2,$3,$4::jsonb,$5)
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                """,
                tenant_id,
                state_id,
                outbox_event_type,
                json.dumps(payload),
                idempotency_key,
            )
            return dict(row)

    async def claim_due_schedules(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 120,
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                """
                WITH due AS (
                    SELECT tenant_id, id
                    FROM enterprise_publish_state
                    WHERE tenant_id=$1 AND scheduled_at <= now()
                      AND cancel_requested_at IS NULL
                      AND (
                        (state='SCHEDULED' AND (lease_expires_at IS NULL OR lease_expires_at < now()))
                        OR (state IN ('CLAIMED','RUNNING') AND lease_expires_at < now())
                      )
                    ORDER BY scheduled_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT $2
                )
                UPDATE enterprise_publish_state p
                SET state='CLAIMED', lease_owner=$3, lease_token=md5(random()::text || clock_timestamp()::text),
                    lease_expires_at=now()+($4::text || ' seconds')::interval,
                    version=version+1, updated_at=now()
                FROM due
                WHERE p.tenant_id=due.tenant_id AND p.id=due.id
                RETURNING p.*
                """,
                tenant_id,
                limit,
                worker_id,
                lease_seconds,
            )
            return [dict(row) for row in rows]

    async def claim_outbox(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                """
                WITH claimed AS (
                    SELECT id FROM enterprise_outbox
                    WHERE tenant_id=$1 AND status IN ('PENDING','RETRY')
                      AND available_at <= now()
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT $2
                )
                UPDATE enterprise_outbox o
                SET status='PROCESSING', locked_by=$3, locked_at=now(), attempts=attempts+1
                FROM claimed WHERE o.id=claimed.id AND o.tenant_id=$1
                RETURNING o.*
                """,
                tenant_id,
                limit,
                worker_id,
            )
            return [dict(row) for row in rows]

    async def complete_outbox(self, tenant_id: str, outbox_id: int) -> None:
        async with self.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                """
                UPDATE enterprise_outbox SET status='DELIVERED', delivered_at=now()
                WHERE tenant_id=$1 AND id=$2
                """,
                tenant_id,
                outbox_id,
            )

    async def retry_outbox(self, tenant_id: str, outbox_id: int, attempts: int) -> None:
        delay = min(3600, 2 ** min(attempts, 10))
        async with self.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                """
                UPDATE enterprise_outbox
                SET status='RETRY', available_at=now()+($3::text || ' seconds')::interval,
                    locked_by=NULL, locked_at=NULL
                WHERE tenant_id=$1 AND id=$2
                """,
                tenant_id,
                outbox_id,
                delay,
            )

    async def get_publish_state_for_draft(
        self, tenant_id: str, draft_id: str
    ) -> dict[str, Any] | None:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                SELECT * FROM enterprise_publish_state
                WHERE tenant_id=$1 AND draft_id=$2
                  AND state NOT IN ('FAILED','CANCELLED')
                ORDER BY created_at DESC LIMIT 1
                """,
                tenant_id,
                draft_id,
            )
            return dict(row) if row else None

    async def get_publish_state(self, tenant_id: str, state_id: str) -> dict[str, Any] | None:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM enterprise_publish_state WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                state_id,
            )
            return dict(row) if row else None

    async def request_publish_cancel(self, tenant_id: str, state_id: str) -> int:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                UPDATE enterprise_publish_state
                SET cancellation_epoch=cancellation_epoch+1, cancel_requested_at=now(),
                    state=CASE WHEN state IN ('SCHEDULED','CLAIMED','RUNNING') THEN 'CANCEL_REQUESTED' ELSE state END,
                    version=version+1, updated_at=now()
                WHERE tenant_id=$1 AND id=$2
                  AND state NOT IN ('VERIFIED','FAILED','CANCELLED')
                RETURNING cancellation_epoch
                """,
                tenant_id,
                state_id,
            )
            return int(row["cancellation_epoch"]) if row else 0

    async def publish_cancel_epoch(self, tenant_id: str, state_id: str) -> int:
        async with self.tenant_transaction(tenant_id) as connection:
            value = await connection.fetchval(
                "SELECT cancellation_epoch FROM enterprise_publish_state WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                state_id,
            )
            return int(value or 0)

    async def heartbeat_publish_lease(
        self,
        tenant_id: str,
        state_id: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> bool:
        async with self.tenant_transaction(tenant_id) as connection:
            result = await connection.execute(
                """
                UPDATE enterprise_publish_state
                SET lease_expires_at=now()+($5::text || ' seconds')::interval, updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND lease_owner=$3 AND lease_token=$4
                  AND state IN ('CLAIMED','RUNNING','SUBMITTING')
                """,
                tenant_id,
                state_id,
                worker_id,
                lease_token,
                lease_seconds,
            )
            return bool(result.endswith("1"))

    async def start_claimed_publish(
        self,
        tenant_id: str,
        state_id: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                UPDATE enterprise_publish_state
                SET state='RUNNING', version=version+1, updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND lease_owner=$3 AND lease_token=$4
                  AND state='CLAIMED' AND cancel_requested_at IS NULL
                RETURNING *
                """,
                tenant_id,
                state_id,
                worker_id,
                lease_token,
            )
            return dict(row) if row else None

    async def mark_publish_submitting(
        self,
        *,
        tenant_id: str,
        state_id: str,
        worker_id: str,
        lease_token: str,
        observed_cancel_epoch: int,
    ) -> bool:
        """Commit the irreversible-submit boundary while holding the current fenced lease."""
        async with self.tenant_transaction(tenant_id) as connection:
            result = await connection.execute(
                """
                UPDATE enterprise_publish_state
                SET state='SUBMITTING', version=version+1, updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND lease_owner=$3 AND lease_token=$4
                  AND state='RUNNING' AND cancellation_epoch=$5
                  AND cancel_requested_at IS NULL
                """,
                tenant_id,
                state_id,
                worker_id,
                lease_token,
                observed_cancel_epoch,
            )
            return bool(result.endswith("1"))

    async def mark_publish_reconciliation(
        self,
        *,
        tenant_id: str,
        state_id: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
        error: dict[str, Any],
    ) -> bool:
        """Persist an uncertain external-submit outcome without retrying the side effect."""
        async with self.tenant_transaction(tenant_id) as connection:
            result = await connection.execute(
                """
                UPDATE enterprise_publish_state
                SET state='RECONCILIATION_REQUIRED', payload=$5::jsonb, last_error=$6::jsonb,
                    completed_at=now(), lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL,
                    version=version+1, updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND lease_owner=$3 AND lease_token=$4
                  AND state='SUBMITTING'
                """,
                tenant_id,
                state_id,
                worker_id,
                lease_token,
                json.dumps(payload),
                json.dumps(error),
            )
            return bool(result.endswith("1"))

    async def finish_claimed_publish(
        self,
        *,
        tenant_id: str,
        state_id: str,
        worker_id: str,
        lease_token: str,
        final_state: str,
        payload: dict[str, Any],
        observed_cancel_epoch: int,
        error: dict[str, Any] | None = None,
    ) -> bool:
        if final_state not in {"VERIFIED", "FAILED", "CANCELLED", "SUBMITTED_UNVERIFIED"}:
            raise ValueError("Unsupported terminal publish state")
        async with self.tenant_transaction(tenant_id) as connection:
            result = await connection.execute(
                """
                UPDATE enterprise_publish_state
                SET state=$5, payload=$6::jsonb, last_error=$7::jsonb,
                    completed_at=now(), lease_owner=NULL, lease_token=NULL,
                    lease_expires_at=NULL, version=version+1, updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND lease_owner=$3 AND lease_token=$4
                  AND cancellation_epoch=$8 AND state IN ('CLAIMED','RUNNING','SUBMITTING')
                """,
                tenant_id,
                state_id,
                worker_id,
                lease_token,
                final_state,
                json.dumps(payload),
                json.dumps(error) if error else None,
                observed_cancel_epoch,
            )
            return bool(result.endswith("1"))

    async def create_job_control(
        self,
        tenant_id: str,
        job_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO enterprise_job_control(tenant_id, job_id, state, payload)
                VALUES($1,$2,'PENDING',$3::jsonb)
                ON CONFLICT (tenant_id, job_id) DO UPDATE SET payload=excluded.payload
                RETURNING *
                """,
                tenant_id,
                job_id,
                json.dumps(payload or {}),
            )
            return dict(row)

    async def request_job_cancel(self, tenant_id: str, job_id: str) -> int:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                UPDATE enterprise_job_control
                SET state='CANCEL_REQUESTED', cancel_epoch=cancel_epoch+1,
                    cancel_requested_at=now(), version=version+1
                WHERE tenant_id=$1 AND job_id=$2
                  AND state NOT IN ('COMPLETED','FAILED','CANCELLED')
                RETURNING cancel_epoch
                """,
                tenant_id,
                job_id,
            )
            return int(row["cancel_epoch"]) if row else 0

    async def job_cancel_epoch(self, tenant_id: str, job_id: str) -> int:
        async with self.tenant_transaction(tenant_id) as connection:
            value = await connection.fetchval(
                "SELECT cancel_epoch FROM enterprise_job_control WHERE tenant_id=$1 AND job_id=$2",
                tenant_id,
                job_id,
            )
            return int(value or 0)

    async def finalize_job(
        self,
        *,
        tenant_id: str,
        job_id: str,
        state: str,
        observed_cancel_epoch: int,
        payload: dict[str, Any],
    ) -> bool:
        async with self.tenant_transaction(tenant_id) as connection:
            result = await connection.execute(
                """
                UPDATE enterprise_job_control
                SET state=$3, terminal_at=now(), payload=$5::jsonb, version=version+1
                WHERE tenant_id=$1 AND job_id=$2 AND cancel_epoch=$4
                  AND state NOT IN ('CANCEL_REQUESTED','CANCELLED')
                """,
                tenant_id,
                job_id,
                state,
                observed_cancel_epoch,
                json.dumps(payload),
            )
            return bool(result.endswith("1"))

    async def claim_outbox_v2(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        limit: int = 100,
        lease_seconds: int = 120,
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                """
                WITH claimed AS (
                    SELECT id FROM enterprise_outbox
                    WHERE tenant_id=$1
                      AND attempts < max_attempts
                      AND available_at <= now()
                      AND (
                        status IN ('PENDING','RETRY') OR
                        (status='PROCESSING' AND lease_expires_at < now())
                      )
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT $2
                )
                UPDATE enterprise_outbox o
                SET status='PROCESSING', locked_by=$3, locked_at=now(),
                    lease_expires_at=now()+($4::text || ' seconds')::interval,
                    attempts=attempts+1
                FROM claimed WHERE o.id=claimed.id AND o.tenant_id=$1
                RETURNING o.*
                """,
                tenant_id,
                limit,
                worker_id,
                lease_seconds,
            )
            return [dict(row) for row in rows]

    async def fail_outbox(
        self,
        tenant_id: str,
        outbox_id: int,
        error: dict[str, Any],
    ) -> str:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM enterprise_outbox WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                tenant_id,
                outbox_id,
            )
            if row is None:
                raise KeyError(outbox_id)
            if int(row["attempts"]) >= int(row["max_attempts"]):
                await connection.execute(
                    """
                    INSERT INTO enterprise_dead_letters(
                        tenant_id, source, source_id, payload, error, attempts
                    ) VALUES($1,'outbox',$2,$3::jsonb,$4::jsonb,$5)
                    ON CONFLICT (tenant_id, source, source_id) DO UPDATE SET
                        payload=excluded.payload, error=excluded.error,
                        attempts=excluded.attempts, status='OPEN'
                    """,
                    tenant_id,
                    str(outbox_id),
                    json.dumps(dict(row)),
                    json.dumps(error),
                    int(row["attempts"]),
                )
                await connection.execute(
                    "UPDATE enterprise_outbox SET status='DEAD', last_error=$3::jsonb WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    outbox_id,
                    json.dumps(error),
                )
                return "DEAD"
            delay = min(3600, 2 ** min(int(row["attempts"]), 10))
            await connection.execute(
                """
                UPDATE enterprise_outbox
                SET status='RETRY', available_at=now()+($3::text || ' seconds')::interval,
                    locked_by=NULL, locked_at=NULL, lease_expires_at=NULL, last_error=$4::jsonb
                WHERE tenant_id=$1 AND id=$2
                """,
                tenant_id,
                outbox_id,
                delay,
                json.dumps(error),
            )
            return "RETRY"

    async def list_dead_letters(self, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                "SELECT * FROM enterprise_dead_letters WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2",
                tenant_id,
                limit,
            )
            return [dict(row) for row in rows]

    async def replay_dead_letter(self, tenant_id: str, dead_letter_id: int) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM enterprise_dead_letters WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                tenant_id,
                dead_letter_id,
            )
            if row is None:
                raise KeyError(dead_letter_id)
            payload = dict(row["payload"])
            if row["source"] != "outbox":
                raise ValueError("Only outbox dead letters can be replayed through this method")
            await connection.execute(
                """
                UPDATE enterprise_outbox
                SET status='RETRY', attempts=0, available_at=now(), locked_by=NULL,
                    locked_at=NULL, lease_expires_at=NULL, last_error=NULL
                WHERE tenant_id=$1 AND id=$2
                """,
                tenant_id,
                int(row["source_id"]),
            )
            await connection.execute(
                """
                UPDATE enterprise_dead_letters
                SET status='REPLAYED', replay_count=replay_count+1, replayed_at=now()
                WHERE tenant_id=$1 AND id=$2
                """,
                tenant_id,
                dead_letter_id,
            )
            return payload

    async def list_tenant_ids(self) -> list[str]:
        """Return worker-assigned tenants without silently bypassing RLS boundaries.

        A normal application role cannot enumerate all tenants because `enterprise_tenants` is
        protected by RLS. Production workers must either receive an explicit tenant shard list or
        use a dedicated control-plane database role with BYPASSRLS.
        """
        configured = [
            validate_identifier(item, field="enterprise_worker_tenant_id")
            for item in self.settings.enterprise_worker_tenant_ids
        ]
        if configured:
            return sorted(set(configured))
        await self.connect()
        pool = self._require_pool()
        async with pool.acquire() as connection:
            bypass_rls = bool(
                await connection.fetchval(
                    "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname=current_user"
                )
            )
            if not bypass_rls:
                raise RuntimeError(
                    "Background tenant discovery requires ENTERPRISE_WORKER_TENANT_IDS or a dedicated BYPASSRLS database role"
                )
            rows = await connection.fetch(
                "SELECT id FROM enterprise_tenants WHERE status='ACTIVE' ORDER BY id"
            )
            return [str(row["id"]) for row in rows]

    async def reserve_cost(
        self,
        *,
        tenant_id: str,
        operation: str,
        estimated_cost_usd: float,
        provider: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int = 900,
    ) -> dict[str, Any]:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated cost cannot be negative")
        reservation_id = str(uuid4())
        async with self.tenant_transaction(tenant_id) as connection:
            tenant = await connection.fetchrow(
                "SELECT policy FROM enterprise_tenants WHERE id=$1 FOR UPDATE",
                tenant_id,
            )
            if tenant is None:
                raise KeyError(tenant_id)
            policy = dict(tenant["policy"])
            daily_limit = float(policy.get("daily_cost_limit_usd", self.settings.enterprise_default_daily_budget_usd))
            monthly_limit = float(policy.get("monthly_cost_limit_usd", self.settings.enterprise_default_monthly_budget_usd))
            committed = await connection.fetchrow(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN created_at >= date_trunc('day', now())
                        THEN COALESCE(actual_cost_usd, estimated_cost_usd) ELSE 0 END), 0) AS daily,
                    COALESCE(SUM(CASE WHEN created_at >= date_trunc('month', now())
                        THEN COALESCE(actual_cost_usd, estimated_cost_usd) ELSE 0 END), 0) AS monthly
                FROM enterprise_usage_ledger
                WHERE tenant_id=$1 AND (
                    status='SETTLED' OR (status='RESERVED' AND expires_at > now())
                )
                """,
                tenant_id,
            )
            daily = float(committed["daily"])
            monthly = float(committed["monthly"])
            if daily + estimated_cost_usd > daily_limit:
                raise PermissionError("Daily tenant cost budget would be exceeded")
            if monthly + estimated_cost_usd > monthly_limit:
                raise PermissionError("Monthly tenant cost budget would be exceeded")
            row = await connection.fetchrow(
                """
                INSERT INTO enterprise_usage_ledger(
                    tenant_id,id,operation,status,estimated_cost_usd,provider,model,
                    metadata,created_at,expires_at
                ) VALUES($1,$2,$3,'RESERVED',$4,$5,$6,$7::jsonb,now(),
                    now()+($8::text || ' seconds')::interval)
                RETURNING *
                """,
                tenant_id,
                reservation_id,
                operation,
                estimated_cost_usd,
                provider,
                model,
                json.dumps(metadata or {}),
                ttl_seconds,
            )
            return dict(row)

    async def settle_cost(self, tenant_id: str, reservation_id: str, actual_cost_usd: float) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                UPDATE enterprise_usage_ledger
                SET status='SETTLED', actual_cost_usd=$3
                WHERE tenant_id=$1 AND id=$2 AND status='RESERVED'
                RETURNING *
                """,
                tenant_id,
                reservation_id,
                actual_cost_usd,
            )
            if row is None:
                raise KeyError(reservation_id)
            return dict(row)

    async def release_cost(self, tenant_id: str, reservation_id: str) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                UPDATE enterprise_usage_ledger SET status='RELEASED'
                WHERE tenant_id=$1 AND id=$2 AND status='RESERVED'
                RETURNING *
                """,
                tenant_id,
                reservation_id,
            )
            if row is None:
                raise KeyError(reservation_id)
            return dict(row)

    async def cost_summary(self, tenant_id: str) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            tenant = await connection.fetchrow("SELECT policy FROM enterprise_tenants WHERE id=$1", tenant_id)
            if tenant is None:
                raise KeyError(tenant_id)
            policy = dict(tenant["policy"])
            row = await connection.fetchrow(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN created_at >= date_trunc('day', now())
                        THEN COALESCE(actual_cost_usd, estimated_cost_usd) ELSE 0 END), 0) AS daily,
                    COALESCE(SUM(CASE WHEN created_at >= date_trunc('month', now())
                        THEN COALESCE(actual_cost_usd, estimated_cost_usd) ELSE 0 END), 0) AS monthly,
                    COUNT(*) FILTER (WHERE status='RESERVED' AND expires_at > now()) AS active
                FROM enterprise_usage_ledger
                WHERE tenant_id=$1 AND (
                    status='SETTLED' OR (status='RESERVED' AND expires_at > now())
                )
                """,
                tenant_id,
            )
            daily_limit = float(policy.get("daily_cost_limit_usd", self.settings.enterprise_default_daily_budget_usd))
            monthly_limit = float(policy.get("monthly_cost_limit_usd", self.settings.enterprise_default_monthly_budget_usd))
            daily = float(row["daily"])
            monthly = float(row["monthly"])
            return {
                "tenant_id": tenant_id,
                "daily_limit_usd": daily_limit,
                "monthly_limit_usd": monthly_limit,
                "daily_committed_usd": daily,
                "monthly_committed_usd": monthly,
                "daily_remaining_usd": max(0.0, daily_limit - daily),
                "monthly_remaining_usd": max(0.0, monthly_limit - monthly),
                "active_reservations": int(row["active"]),
            }

    async def enqueue_post_publish_sync(self, task: PostPublishSyncTask) -> dict[str, Any]:
        async with self.tenant_transaction(task.tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO post_publish_sync_tasks(
                    tenant_id,id,account_id,note_id,note_url,due_at,status,attempts,
                    max_attempts,payload,created_at
                ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11)
                ON CONFLICT (tenant_id,id) DO UPDATE SET
                    due_at=excluded.due_at, status=excluded.status,
                    max_attempts=excluded.max_attempts, payload=excluded.payload
                RETURNING *
                """,
                task.tenant_id,
                task.id,
                task.account_id,
                task.note_id,
                task.note_url,
                task.due_at,
                task.status,
                task.attempts,
                task.max_attempts,
                task.model_dump_json(),
                task.created_at,
            )
            return dict(row)

    async def claim_post_publish_sync(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        limit: int = 20,
        lease_seconds: int = 180,
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                """
                WITH claimed AS (
                    SELECT id FROM post_publish_sync_tasks
                    WHERE tenant_id=$1 AND due_at<=now() AND attempts<max_attempts
                      AND (
                        status IN ('PENDING','RETRY') OR
                        (status='RUNNING' AND lease_expires_at<now())
                      )
                    ORDER BY due_at
                    FOR UPDATE SKIP LOCKED LIMIT $2
                )
                UPDATE post_publish_sync_tasks t
                SET status='RUNNING', attempts=t.attempts+1, lease_owner=$3,
                    lease_expires_at=now()+($4::text || ' seconds')::interval,
                    payload=jsonb_set(
                        jsonb_set(t.payload,'{status}','\"RUNNING\"'::jsonb,true),
                        '{attempts}',to_jsonb(t.attempts+1),true
                    )
                FROM claimed WHERE t.tenant_id=$1 AND t.id=claimed.id
                RETURNING t.*
                """,
                tenant_id,
                limit,
                worker_id,
                lease_seconds,
            )
            return [dict(row) for row in rows]

    async def finish_post_publish_sync(
        self,
        *,
        tenant_id: str,
        task_id: str,
        worker_id: str,
        success: bool,
        retry_at: datetime | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        async with self.tenant_transaction(tenant_id) as connection:
            current = await connection.fetchrow(
                """SELECT * FROM post_publish_sync_tasks
                WHERE tenant_id=$1 AND id=$2 AND lease_owner=$3 FOR UPDATE""",
                tenant_id,
                task_id,
                worker_id,
            )
            if current is None:
                return None
            terminal = bool(success or int(current["attempts"]) >= int(current["max_attempts"]))
            status = "COMPLETED" if success else ("DEAD" if terminal else "RETRY")
            due_at = current["due_at"] if success else (retry_at or current["due_at"])
            payload = dict(current["payload"])
            payload.update(
                {
                    "status": status,
                    "attempts": int(current["attempts"]),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error": error,
                    "due_at": due_at.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat() if success else None,
                }
            )
            row = await connection.fetchrow(
                """
                UPDATE post_publish_sync_tasks
                SET status=$4, due_at=$5, lease_owner=NULL, lease_expires_at=NULL,
                    last_error=$6, completed_at=CASE WHEN $7 THEN now() ELSE NULL END,
                    payload=$8::jsonb
                WHERE tenant_id=$1 AND id=$2 AND lease_owner=$3
                RETURNING *
                """,
                tenant_id,
                task_id,
                worker_id,
                status,
                due_at,
                error,
                success,
                json.dumps(payload),
            )
            return dict(row) if row else None

    async def save_published_metrics(self, metrics: PublishedMetrics) -> dict[str, Any]:
        async with self.tenant_transaction(metrics.tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO published_note_metrics(tenant_id,account_id,note_id,snapshot_at,payload)
                VALUES($1,$2,$3,$4,$5::jsonb)
                ON CONFLICT (tenant_id,note_id,snapshot_at) DO UPDATE SET payload=excluded.payload
                RETURNING *
                """,
                metrics.tenant_id,
                metrics.account_id,
                metrics.note_id,
                metrics.snapshot_at,
                metrics.model_dump_json(),
            )
            return dict(row)

    async def list_published_metrics(
        self, tenant_id: str, account_id: str, note_id: str | None = None
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            if note_id:
                rows = await connection.fetch(
                    """SELECT payload FROM published_note_metrics
                    WHERE tenant_id=$1 AND account_id=$2 AND note_id=$3 ORDER BY snapshot_at""",
                    tenant_id,
                    account_id,
                    note_id,
                )
            else:
                rows = await connection.fetch(
                    """SELECT payload FROM published_note_metrics
                    WHERE tenant_id=$1 AND account_id=$2 ORDER BY snapshot_at""",
                    tenant_id,
                    account_id,
                )
            return [dict(row["payload"]) for row in rows]

    async def save_calendar_items(self, items: list[ContentCalendarItem]) -> None:
        if not items:
            return
        tenant_id = items[0].tenant_id
        if any(item.tenant_id != tenant_id for item in items):
            raise ValueError("Calendar batch must belong to one tenant")
        async with self.tenant_transaction(tenant_id) as connection:
            await connection.executemany(
                """
                INSERT INTO content_calendar_items(
                    tenant_id,id,account_id,scheduled_at,status,payload
                ) VALUES($1,$2,$3,$4,$5,$6::jsonb)
                ON CONFLICT (tenant_id,id) DO UPDATE SET
                    account_id=excluded.account_id, scheduled_at=excluded.scheduled_at,
                    status=excluded.status, payload=excluded.payload,
                    version=content_calendar_items.version+1
                """,
                [
                    (
                        item.tenant_id,
                        item.id,
                        item.account_id,
                        item.scheduled_at,
                        item.status,
                        item.model_dump_json(),
                    )
                    for item in items
                ],
            )

    async def list_calendar_items(
        self, tenant_id: str, account_id: str
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                """SELECT payload FROM content_calendar_items
                WHERE tenant_id=$1 AND account_id=$2 ORDER BY scheduled_at""",
                tenant_id,
                account_id,
            )
            return [dict(row["payload"]) for row in rows]

    async def save_series_plan(self, plan: SeriesPlan) -> dict[str, Any]:
        async with self.tenant_transaction(plan.tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO content_series_plans(tenant_id,id,account_id,payload,created_at)
                VALUES($1,$2,$3,$4::jsonb,$5)
                ON CONFLICT (tenant_id,id) DO UPDATE SET payload=excluded.payload
                RETURNING *
                """,
                plan.tenant_id,
                plan.id,
                plan.account_id,
                plan.model_dump_json(),
                plan.created_at,
            )
            return dict(row)

    async def save_content_experiment(self, experiment: Experiment) -> dict[str, Any]:
        async with self.tenant_transaction(experiment.tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO content_experiments(
                    tenant_id,id,account_id,status,primary_metric,payload,created_at
                ) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7)
                ON CONFLICT (tenant_id,id) DO UPDATE SET
                    status=excluded.status, primary_metric=excluded.primary_metric,
                    payload=excluded.payload, version=content_experiments.version+1
                RETURNING *
                """,
                experiment.tenant_id,
                experiment.id,
                experiment.account_id,
                experiment.status,
                experiment.primary_metric,
                experiment.model_dump_json(),
                experiment.created_at,
            )
            return dict(row)

    async def get_content_experiment(
        self, tenant_id: str, experiment_id: str
    ) -> dict[str, Any] | None:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT payload FROM content_experiments WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                experiment_id,
            )
            return dict(row["payload"]) if row else None

    async def save_experiment_assignment(
        self, tenant_id: str, assignment: ExperimentAssignment
    ) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO content_experiment_assignments(
                    tenant_id,experiment_id,subject_id,variant_id,payload,assigned_at
                ) VALUES($1,$2,$3,$4,$5::jsonb,$6)
                ON CONFLICT (tenant_id,experiment_id,subject_id) DO NOTHING
                RETURNING payload
                """,
                tenant_id,
                assignment.experiment_id,
                assignment.subject_id,
                assignment.variant_id,
                assignment.model_dump_json(),
                assignment.assigned_at,
            )
            if row:
                return dict(row["payload"])
            existing = await connection.fetchrow(
                """SELECT payload FROM content_experiment_assignments
                WHERE tenant_id=$1 AND experiment_id=$2 AND subject_id=$3""",
                tenant_id,
                assignment.experiment_id,
                assignment.subject_id,
            )
            if existing is None:
                raise RuntimeError("Experiment assignment was not persisted")
            return dict(existing["payload"])

    async def save_experiment_outcome(
        self, tenant_id: str, outcome: ExperimentOutcome
    ) -> dict[str, Any]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO content_experiment_outcomes(
                    tenant_id,experiment_id,subject_id,metric,recorded_at,payload
                ) VALUES($1,$2,$3,$4,$5,$6::jsonb)
                ON CONFLICT (tenant_id,experiment_id,subject_id,metric,recorded_at)
                DO UPDATE SET payload=excluded.payload
                RETURNING payload
                """,
                tenant_id,
                outcome.experiment_id,
                outcome.subject_id,
                outcome.metric,
                outcome.recorded_at,
                outcome.model_dump_json(),
            )
            return dict(row["payload"])

    async def list_experiment_outcomes(
        self, tenant_id: str, experiment_id: str
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                """SELECT payload FROM content_experiment_outcomes
                WHERE tenant_id=$1 AND experiment_id=$2 ORDER BY recorded_at""",
                tenant_id,
                experiment_id,
            )
            return [dict(row["payload"]) for row in rows]

    async def load_bandit_arm(
        self, tenant_id: str, policy_id: str, arm_id: str, dimension: int
    ) -> tuple[list[list[float]], list[float], int]:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """SELECT a_matrix,b_vector,pulls,dimension FROM contextual_bandit_state
                WHERE tenant_id=$1 AND policy_id=$2 AND arm_id=$3""",
                tenant_id,
                policy_id,
                arm_id,
            )
            if row:
                if int(row["dimension"]) != dimension:
                    raise ValueError("Context dimension changed for existing bandit arm")
                return (
                    [[float(v) for v in r] for r in row["a_matrix"]],
                    [float(v) for v in row["b_vector"]],
                    int(row["pulls"]),
                )
            identity = [
                [1.0 if i == j else 0.0 for j in range(dimension)]
                for i in range(dimension)
            ]
            return identity, [0.0] * dimension, 0

    async def update_bandit_arm(
        self,
        tenant_id: str,
        policy_id: str,
        arm_id: str,
        context: list[float],
        reward: float,
    ) -> None:
        dimension = len(context)
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                """SELECT a_matrix,b_vector,pulls,dimension FROM contextual_bandit_state
                WHERE tenant_id=$1 AND policy_id=$2 AND arm_id=$3 FOR UPDATE""",
                tenant_id,
                policy_id,
                arm_id,
            )
            if row:
                if int(row["dimension"]) != dimension:
                    raise ValueError("Context dimension changed for existing bandit arm")
                a = [[float(v) for v in r] for r in row["a_matrix"]]
                b = [float(v) for v in row["b_vector"]]
                pulls = int(row["pulls"])
            else:
                a = [
                    [1.0 if i == j else 0.0 for j in range(dimension)]
                    for i in range(dimension)
                ]
                b = [0.0] * dimension
                pulls = 0
            for i in range(dimension):
                b[i] += reward * context[i]
                for j in range(dimension):
                    a[i][j] += context[i] * context[j]
            await connection.execute(
                """
                INSERT INTO contextual_bandit_state(
                    tenant_id,policy_id,arm_id,dimension,pulls,a_matrix,b_vector
                ) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb)
                ON CONFLICT (tenant_id,policy_id,arm_id) DO UPDATE SET
                    dimension=excluded.dimension, pulls=excluded.pulls,
                    a_matrix=excluded.a_matrix, b_vector=excluded.b_vector,
                    version=contextual_bandit_state.version+1, updated_at=now()
                """,
                tenant_id,
                policy_id,
                arm_id,
                dimension,
                pulls + 1,
                json.dumps(a),
                json.dumps(b),
            )

    async def save_asset_record(self, asset: AssetRecord) -> dict[str, Any]:
        async with self.tenant_transaction(asset.tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO content_asset_library(tenant_id,id,sha256,payload,created_at)
                VALUES($1,$2,$3,$4::jsonb,$5)
                ON CONFLICT (tenant_id,sha256) DO UPDATE SET payload=excluded.payload
                RETURNING payload
                """,
                asset.tenant_id,
                asset.id,
                asset.sha256,
                asset.model_dump_json(),
                asset.created_at,
            )
            return dict(row["payload"])

    async def search_asset_records(
        self, tenant_id: str, tags: list[str] | None = None
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                "SELECT payload FROM content_asset_library WHERE tenant_id=$1 ORDER BY created_at DESC",
                tenant_id,
            )
            items = [dict(row["payload"]) for row in rows]
            if tags:
                required = set(tags)
                items = [item for item in items if required.issubset(set(item.get("tags", [])))]
            return items

    async def save_retrospective_record(self, item: Retrospective) -> dict[str, Any]:
        async with self.tenant_transaction(item.tenant_id) as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO content_retrospectives(
                    tenant_id,id,account_id,note_id,payload,created_at
                ) VALUES($1,$2,$3,$4,$5::jsonb,$6)
                ON CONFLICT (tenant_id,id) DO UPDATE SET payload=excluded.payload
                RETURNING payload
                """,
                item.tenant_id,
                item.id,
                item.account_id,
                item.note_id,
                item.model_dump_json(),
                item.created_at,
            )
            return dict(row["payload"])

    async def save_account_weight_snapshot(
        self, tenant_id: str, snapshot: AccountWeightSnapshot
    ) -> None:
        async with self.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                """
                INSERT INTO account_weight_snapshots(
                    tenant_id,account_id,recorded_at,score,payload
                ) VALUES($1,$2,$3,$4,$5::jsonb)
                ON CONFLICT (tenant_id,account_id,recorded_at) DO UPDATE SET
                    score=excluded.score,payload=excluded.payload
                """,
                tenant_id,
                snapshot.account_id,
                snapshot.recorded_at,
                snapshot.score,
                snapshot.model_dump_json(),
            )

    async def list_account_weight_snapshots(
        self, tenant_id: str, account_id: str
    ) -> list[dict[str, Any]]:
        async with self.tenant_transaction(tenant_id) as connection:
            rows = await connection.fetch(
                """SELECT payload FROM account_weight_snapshots
                WHERE tenant_id=$1 AND account_id=$2 ORDER BY recorded_at""",
                tenant_id,
                account_id,
            )
            return [dict(row["payload"]) for row in rows]

    async def save_account_profile(self, profile: AccountProfile) -> None:
        async with self.tenant_transaction(profile.tenant_id) as connection:
            await connection.execute(
                """
                INSERT INTO account_profiles(tenant_id,account_id,payload,updated_at)
                VALUES($1,$2,$3::jsonb,now())
                ON CONFLICT (tenant_id,account_id) DO UPDATE SET
                    payload=excluded.payload,updated_at=now()
                """,
                profile.tenant_id,
                profile.account_id,
                profile.model_dump_json(),
            )

    async def get_account_profile(
        self, tenant_id: str, account_id: str
    ) -> dict[str, Any] | None:
        async with self.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT payload FROM account_profiles WHERE tenant_id=$1 AND account_id=$2",
                tenant_id,
                account_id,
            )
            return dict(row["payload"]) if row else None
