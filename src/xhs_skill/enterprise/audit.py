from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import validate_identifier
from xhs_skill.enterprise.filelock import process_file_lock
from xhs_skill.enterprise.models import AuditEvent, AuditVerification


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class S3ObjectLockAuditSink:
    """Optional WORM sink. The bucket must have Object Lock enabled by administrators."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.audit_s3_bucket:
            raise ValueError("AUDIT_S3_BUCKET is not configured")
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("Install the aws optional dependency for the S3 audit sink") from exc
        self.client = boto3.client("s3", region_name=self.settings.aws_region)

    def append(self, event: AuditEvent) -> None:
        key = (
            f"{self.settings.audit_s3_prefix.strip('/')}/{event.tenant_id}/"
            f"{event.timestamp:%Y/%m/%d}/{event.sequence:020d}-{event.id}.json"
        )
        retain_until = datetime.now(UTC) + timedelta(days=self.settings.audit_s3_object_lock_days)
        self.client.put_object(
            Bucket=self.settings.audit_s3_bucket,
            Key=key,
            Body=event.model_dump_json().encode("utf-8"),
            ContentType="application/json",
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=retain_until,
            Metadata={"event-hash": event.event_hash, "tenant-id": event.tenant_id},
        )


class AuditLedger:
    """Append-only HMAC-signed hash chain with optional external WORM replication."""

    def __init__(self, settings: Settings | None = None, sink: AuditSink | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = self.settings.audit_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._key = (self.settings.audit_hmac_key or self.settings.app_secret_key).encode("utf-8")
        self._lock = threading.RLock()
        self.sink = sink
        if sink is None and self.settings.audit_s3_bucket:
            self.sink = S3ObjectLockAuditSink(self.settings)

    def _path(self, tenant_id: str) -> Path:
        safe = validate_identifier(tenant_id, field="tenant_id")
        path = (self.root / f"{safe}.jsonl").resolve()
        if path.parent != self.root:
            raise ValueError("Invalid audit path")
        return path

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")

    def _last(self, path: Path) -> tuple[int, str]:
        if not path.exists() or path.stat().st_size == 0:
            return 0, "0" * 64
        # Audit records are bounded JSON objects. Reading the final non-empty line is
        # simpler and safer than hand-written reverse seeking, which can truncate the
        # first byte of a record around trailing newlines.
        lines = path.read_text(encoding="utf-8").splitlines()
        line = next((item for item in reversed(lines) if item.strip()), "")
        if not line:
            return 0, "0" * 64
        payload = json.loads(line)
        return int(payload["sequence"]), str(payload["event_hash"])

    def append(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        resource_type: str,
        outcome: str,
        resource_id: str | None = None,
        actor_type: str = "user",
        request_id: str | None = None,
        source_ip: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        path = self._path(tenant_id)
        with self._lock, process_file_lock(path.with_suffix(".lock")):
            sequence, previous_hash = self._last(path)
            base = {
                "id": os.urandom(16).hex(),
                "sequence": sequence + 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "actor_type": actor_type,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                "request_id": request_id,
                "source_ip_hash": (
                    hmac.new(self._key, source_ip.encode("utf-8"), hashlib.sha256).hexdigest()
                    if source_ip
                    else None
                ),
                "metadata": metadata or {},
                "previous_hash": previous_hash,
            }
            event_hash = hashlib.sha256(self._canonical(base)).hexdigest()
            signature = hmac.new(self._key, event_hash.encode("ascii"), hashlib.sha256).hexdigest()
            event = AuditEvent.model_validate({**base, "event_hash": event_hash, "signature": signature})
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                with os.fdopen(fd, "a", encoding="utf-8") as handle:
                    handle.write(event.model_dump_json() + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            if self.sink:
                self.sink.append(event)
            return event

    def events(self, tenant_id: str, *, limit: int = 1000) -> list[AuditEvent]:
        path = self._path(tenant_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 10_000)) :]
        return [AuditEvent.model_validate_json(line) for line in lines if line.strip()]

    def verify(self, tenant_id: str) -> AuditVerification:
        path = self._path(tenant_id)
        if not path.exists():
            return AuditVerification(tenant_id=tenant_id, valid=True, events_checked=0, root_hash="0" * 64)
        previous = "0" * 64
        count = 0
        first: int | None = None
        last: int | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            count += 1
            try:
                event = AuditEvent.model_validate_json(line)
            except Exception as exc:
                return AuditVerification(
                    tenant_id=tenant_id,
                    valid=False,
                    events_checked=count - 1,
                    failure_sequence=count,
                    failure_reason=f"Invalid event encoding: {type(exc).__name__}",
                    root_hash=previous,
                )
            first = first or event.sequence
            last = event.sequence
            base = event.model_dump(mode="json", exclude={"event_hash", "signature"})
            base["timestamp"] = event.timestamp.isoformat()
            expected_hash = hashlib.sha256(self._canonical(base)).hexdigest()
            expected_signature = hmac.new(self._key, expected_hash.encode("ascii"), hashlib.sha256).hexdigest()
            if event.previous_hash != previous:
                return AuditVerification(
                    tenant_id=tenant_id,
                    valid=False,
                    events_checked=count,
                    first_sequence=first,
                    last_sequence=last,
                    failure_sequence=event.sequence,
                    failure_reason="Previous hash mismatch",
                    root_hash=previous,
                )
            if not hmac.compare_digest(event.event_hash, expected_hash):
                return AuditVerification(
                    tenant_id=tenant_id,
                    valid=False,
                    events_checked=count,
                    first_sequence=first,
                    last_sequence=last,
                    failure_sequence=event.sequence,
                    failure_reason="Event hash mismatch",
                    root_hash=previous,
                )
            if not hmac.compare_digest(event.signature, expected_signature):
                return AuditVerification(
                    tenant_id=tenant_id,
                    valid=False,
                    events_checked=count,
                    first_sequence=first,
                    last_sequence=last,
                    failure_sequence=event.sequence,
                    failure_reason="Event signature mismatch",
                    root_hash=previous,
                )
            previous = event.event_hash
        return AuditVerification(
            tenant_id=tenant_id,
            valid=True,
            events_checked=count,
            first_sequence=first,
            last_sequence=last,
            root_hash=previous,
        )


_audit_ledger: AuditLedger | None = None


def get_audit_ledger() -> AuditLedger:
    global _audit_ledger
    if _audit_ledger is None:
        _audit_ledger = AuditLedger()
    return _audit_ledger
