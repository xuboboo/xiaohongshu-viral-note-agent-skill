from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskMode(StrEnum):
    SEARCH_HOT_NOTES = "SEARCH_HOT_NOTES"
    SEARCH_TRENDING_TOPICS = "SEARCH_TRENDING_TOPICS"
    ANALYZE_HOT_NOTES = "ANALYZE_HOT_NOTES"
    GENERATE_FROM_TRENDS = "GENERATE_FROM_TRENDS"
    CREATE_NOTE = "CREATE_NOTE"
    REWRITE_NOTE = "REWRITE_NOTE"
    DIAGNOSE_NOTE = "DIAGNOSE_NOTE"
    SYNC_ACCOUNT_ANALYTICS = "SYNC_ACCOUNT_ANALYTICS"
    QUERY_ACCOUNT_WEIGHT = "QUERY_ACCOUNT_WEIGHT"
    AUTHENTICATE_ACCOUNT = "AUTHENTICATE_ACCOUNT"
    CREATE_PUBLISH_DRAFT = "CREATE_PUBLISH_DRAFT"
    PREVIEW_NOTE = "PREVIEW_NOTE"
    PUBLISH_NOTE = "PUBLISH_NOTE"
    SCHEDULE_NOTE = "SCHEDULE_NOTE"
    ANALYZE_PERFORMANCE = "ANALYZE_PERFORMANCE"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_TOOL = "WAITING_FOR_TOOL"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BaseRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = "1.0"


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
