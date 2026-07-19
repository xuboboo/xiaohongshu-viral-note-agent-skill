from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import validate_identifier
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


class OperationsRepository:
    """Durable single-node operations store.

    SQLite WAL provides safe local multi-process reads/writes. Enterprise multi-Pod installs use
    the PostgreSQL tables and workers shipped in the same Skill.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = Path(self.settings.operations_db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS published_metrics (
                    tenant_id TEXT NOT NULL, account_id TEXT NOT NULL, note_id TEXT NOT NULL,
                    snapshot_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, note_id, snapshot_at)
                );
                CREATE INDEX IF NOT EXISTS metrics_account_idx
                    ON published_metrics(tenant_id, account_id, snapshot_at);
                CREATE TABLE IF NOT EXISTS content_calendar (
                    tenant_id TEXT NOT NULL, id TEXT NOT NULL, account_id TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, id)
                );
                CREATE TABLE IF NOT EXISTS content_series (
                    tenant_id TEXT NOT NULL, id TEXT NOT NULL, account_id TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY (tenant_id, id)
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    tenant_id TEXT NOT NULL, id TEXT NOT NULL, account_id TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (tenant_id, id)
                );
                CREATE TABLE IF NOT EXISTS experiment_assignments (
                    tenant_id TEXT NOT NULL, experiment_id TEXT NOT NULL, subject_id TEXT NOT NULL,
                    variant_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, experiment_id, subject_id)
                );
                CREATE TABLE IF NOT EXISTS experiment_outcomes (
                    tenant_id TEXT NOT NULL, experiment_id TEXT NOT NULL, subject_id TEXT NOT NULL,
                    metric TEXT NOT NULL, recorded_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, experiment_id, subject_id, metric, recorded_at)
                );
                CREATE TABLE IF NOT EXISTS bandit_state (
                    tenant_id TEXT NOT NULL, policy_id TEXT NOT NULL, arm_id TEXT NOT NULL,
                    dimension INTEGER NOT NULL, pulls INTEGER NOT NULL, a_json TEXT NOT NULL,
                    b_json TEXT NOT NULL, PRIMARY KEY (tenant_id, policy_id, arm_id)
                );
                CREATE TABLE IF NOT EXISTS assets (
                    tenant_id TEXT NOT NULL, id TEXT NOT NULL, sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY (tenant_id, id), UNIQUE (tenant_id, sha256)
                );
                CREATE TABLE IF NOT EXISTS retrospectives (
                    tenant_id TEXT NOT NULL, id TEXT NOT NULL, account_id TEXT NOT NULL,
                    note_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, id)
                );
                CREATE TABLE IF NOT EXISTS post_publish_sync_tasks (
                    tenant_id TEXT NOT NULL, id TEXT NOT NULL, account_id TEXT NOT NULL,
                    note_id TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, lease_owner TEXT,
                    lease_expires_at TEXT, payload TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, id)
                );
                CREATE INDEX IF NOT EXISTS post_publish_sync_due_idx
                    ON post_publish_sync_tasks(tenant_id, status, due_at);
                """
            )

    @staticmethod
    def _tenant(tenant_id: str) -> str:
        return validate_identifier(tenant_id, field="tenant_id")

    def save_metrics(self, metrics: PublishedMetrics) -> PublishedMetrics:
        tenant = self._tenant(metrics.tenant_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO published_metrics VALUES(?,?,?,?,?)",
                (tenant, metrics.account_id, metrics.note_id, metrics.snapshot_at.isoformat(), metrics.model_dump_json()),
            )
        return metrics

    def list_metrics(self, tenant_id: str, account_id: str, note_id: str | None = None) -> list[PublishedMetrics]:
        tenant = self._tenant(tenant_id)
        query = "SELECT payload FROM published_metrics WHERE tenant_id=? AND account_id=?"
        params: list[Any] = [tenant, account_id]
        if note_id:
            query += " AND note_id=?"
            params.append(note_id)
        query += " ORDER BY snapshot_at"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [PublishedMetrics.model_validate_json(row["payload"]) for row in rows]

    def save_calendar_items(self, items: list[ContentCalendarItem]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in items:
                connection.execute(
                    "INSERT OR REPLACE INTO content_calendar VALUES(?,?,?,?,?,?)",
                    (item.tenant_id, item.id, item.account_id, item.scheduled_at.isoformat(), item.status, item.model_dump_json()),
                )
            connection.execute("COMMIT")

    def list_calendar(self, tenant_id: str, account_id: str) -> list[ContentCalendarItem]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM content_calendar WHERE tenant_id=? AND account_id=? ORDER BY scheduled_at",
                (self._tenant(tenant_id), account_id),
            ).fetchall()
        return [ContentCalendarItem.model_validate_json(row["payload"]) for row in rows]

    def save_series(self, plan: SeriesPlan) -> SeriesPlan:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO content_series VALUES(?,?,?,?)",
                (plan.tenant_id, plan.id, plan.account_id, plan.model_dump_json()),
            )
        return plan

    def save_experiment(self, experiment: Experiment) -> Experiment:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO experiments VALUES(?,?,?,?,?)",
                (experiment.tenant_id, experiment.id, experiment.account_id, experiment.status, experiment.model_dump_json()),
            )
        return experiment

    def get_experiment(self, tenant_id: str, experiment_id: str) -> Experiment | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM experiments WHERE tenant_id=? AND id=?",
                (self._tenant(tenant_id), experiment_id),
            ).fetchone()
        return Experiment.model_validate_json(row["payload"]) if row else None

    def save_assignment(self, tenant_id: str, assignment: ExperimentAssignment) -> ExperimentAssignment:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO experiment_assignments VALUES(?,?,?,?,?)",
                (self._tenant(tenant_id), assignment.experiment_id, assignment.subject_id, assignment.variant_id, assignment.model_dump_json()),
            )
            row = connection.execute(
                "SELECT payload FROM experiment_assignments WHERE tenant_id=? AND experiment_id=? AND subject_id=?",
                (tenant_id, assignment.experiment_id, assignment.subject_id),
            ).fetchone()
        return ExperimentAssignment.model_validate_json(row["payload"])

    def save_outcome(self, tenant_id: str, outcome: ExperimentOutcome) -> ExperimentOutcome:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO experiment_outcomes VALUES(?,?,?,?,?,?)",
                (self._tenant(tenant_id), outcome.experiment_id, outcome.subject_id, outcome.metric, outcome.recorded_at.isoformat(), outcome.model_dump_json()),
            )
        return outcome

    def experiment_outcomes(self, tenant_id: str, experiment_id: str) -> list[ExperimentOutcome]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM experiment_outcomes WHERE tenant_id=? AND experiment_id=?",
                (self._tenant(tenant_id), experiment_id),
            ).fetchall()
        return [ExperimentOutcome.model_validate_json(row["payload"]) for row in rows]

    def load_bandit_arm(self, tenant_id: str, policy_id: str, arm_id: str, dimension: int) -> tuple[list[list[float]], list[float], int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT a_json,b_json,pulls FROM bandit_state WHERE tenant_id=? AND policy_id=? AND arm_id=?",
                (self._tenant(tenant_id), policy_id, arm_id),
            ).fetchone()
        if row:
            return json.loads(row["a_json"]), json.loads(row["b_json"]), int(row["pulls"])
        identity = [[1.0 if i == j else 0.0 for j in range(dimension)] for i in range(dimension)]
        return identity, [0.0] * dimension, 0

    def save_bandit_arm(self, tenant_id: str, policy_id: str, arm_id: str, a: list[list[float]], b: list[float], pulls: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO bandit_state VALUES(?,?,?,?,?,?,?)",
                (self._tenant(tenant_id), policy_id, arm_id, len(b), pulls, json.dumps(a), json.dumps(b)),
            )

    def save_asset(self, asset: AssetRecord) -> AssetRecord:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload FROM assets WHERE tenant_id=? AND sha256=?",
                (self._tenant(asset.tenant_id), asset.sha256),
            ).fetchone()
            if existing:
                return AssetRecord.model_validate_json(existing["payload"])
            connection.execute(
                "INSERT INTO assets VALUES(?,?,?,?)",
                (asset.tenant_id, asset.id, asset.sha256, asset.model_dump_json()),
            )
        return asset

    def search_assets(self, tenant_id: str, tags: list[str] | None = None) -> list[AssetRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM assets WHERE tenant_id=?",
                (self._tenant(tenant_id),),
            ).fetchall()
        assets = [AssetRecord.model_validate_json(row["payload"]) for row in rows]
        if tags:
            required = set(tags)
            assets = [asset for asset in assets if required.issubset(set(asset.tags))]
        return assets

    def save_retrospective(self, item: Retrospective) -> Retrospective:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO retrospectives VALUES(?,?,?,?,?,?)",
                (item.tenant_id, item.id, item.account_id, item.note_id, item.created_at.isoformat(), item.model_dump_json()),
            )
        return item


    def enqueue_post_publish_sync(self, task: PostPublishSyncTask) -> PostPublishSyncTask:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO post_publish_sync_tasks VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    self._tenant(task.tenant_id),
                    task.id,
                    task.account_id,
                    task.note_id,
                    task.due_at.isoformat(),
                    task.status,
                    task.attempts,
                    task.lease_owner,
                    task.lease_expires_at.isoformat() if task.lease_expires_at else None,
                    task.model_dump_json(),
                ),
            )
        return task

    def claim_post_publish_sync(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int = 20,
    ) -> list[PostPublishSyncTask]:
        from datetime import timedelta

        tenant = self._tenant(tenant_id)
        lease_expires = now + timedelta(seconds=lease_seconds)
        claimed: list[PostPublishSyncTask] = []
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT payload FROM post_publish_sync_tasks
                WHERE tenant_id=? AND due_at<=?
                  AND attempts < json_extract(payload, '$.max_attempts')
                  AND (status IN ('PENDING','RETRY')
                    OR (status='RUNNING' AND lease_expires_at<?))
                ORDER BY due_at LIMIT ?
                """,
                (tenant, now.isoformat(), now.isoformat(), limit),
            ).fetchall()
            for row in rows:
                task = PostPublishSyncTask.model_validate_json(row["payload"]).model_copy(
                    update={
                        "status": "RUNNING",
                        "attempts": PostPublishSyncTask.model_validate_json(row["payload"]).attempts + 1,
                        "lease_owner": worker_id,
                        "lease_expires_at": lease_expires,
                    }
                )
                connection.execute(
                    """UPDATE post_publish_sync_tasks
                    SET status='RUNNING', attempts=?, lease_owner=?, lease_expires_at=?, payload=?
                    WHERE tenant_id=? AND id=?""",
                    (
                        task.attempts, worker_id, lease_expires.isoformat(),
                        task.model_dump_json(), tenant, task.id,
                    ),
                )
                claimed.append(task)
            connection.execute("COMMIT")
        return claimed

    def finish_post_publish_sync(
        self,
        task: PostPublishSyncTask,
        *,
        success: bool,
        error: str | None = None,
        retry_at: datetime | None = None,
    ) -> PostPublishSyncTask:
        from datetime import UTC, datetime

        status = "COMPLETED" if success else ("RETRY" if task.attempts < task.max_attempts else "DEAD")
        updated = task.model_copy(
            update={
                "status": status,
                "last_error": error,
                "due_at": retry_at or task.due_at,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": datetime.now(UTC) if success else None,
            }
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE post_publish_sync_tasks
                SET due_at=?, status=?, attempts=?, lease_owner=NULL, lease_expires_at=NULL, payload=?
                WHERE tenant_id=? AND id=?""",
                (
                    updated.due_at.isoformat(), updated.status, updated.attempts,
                    updated.model_dump_json(), self._tenant(updated.tenant_id), updated.id,
                ),
            )
        return updated
