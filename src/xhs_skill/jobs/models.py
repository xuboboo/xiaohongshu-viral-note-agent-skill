from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from xhs_skill.schemas.common import JobStatus


class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.PENDING
    task_type: str
    tenant_id: str = "local"
    created_by: str = "local-cli"
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    input: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
