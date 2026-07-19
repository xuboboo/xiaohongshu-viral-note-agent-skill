from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class StreamEvent(BaseModel):
    event_id: int
    event_type: str
    job_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sequence: int
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str
