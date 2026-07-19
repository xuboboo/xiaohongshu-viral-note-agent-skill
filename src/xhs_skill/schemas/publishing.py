from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from xhs_skill.schemas.content import DeliveryPackage


class LoginStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    QR_CODE_READY = "QR_CODE_READY"
    WAITING_FOR_SCAN = "WAITING_FOR_SCAN"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    AUTHENTICATED = "AUTHENTICATED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    RISK_VERIFICATION_REQUIRED = "RISK_VERIFICATION_REQUIRED"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    LOCKED = "LOCKED"
    LOGGED_OUT = "LOGGED_OUT"


class PublishMode(StrEnum):
    DRAFT_ONLY = "DRAFT_ONLY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    SCHEDULED_AUTO_PUBLISH = "SCHEDULED_AUTO_PUBLISH"
    FULLY_AUTOMATED = "FULLY_AUTOMATED"


class AuthSession(BaseModel):
    id: str
    account_id: str
    tenant_id: str = "local"
    status: LoginStatus
    qr_image_path: str | None = Field(default=None, exclude=True)
    qr_image_url: str | None = None
    authenticated_at: datetime | None = None
    expires_at: datetime | None = None
    last_verified_at: datetime | None = None
    account_display_name: str | None = None
    identity_verified: bool = False
    warnings: list[str] = Field(default_factory=list)


class PublishDraft(BaseModel):
    id: str
    account_id: str
    tenant_id: str = "local"
    created_by: str = "local-cli"
    package: DeliveryPackage
    content_hash: str
    mode: PublishMode = PublishMode.REQUIRE_CONFIRMATION
    preview_path: str | None = Field(default=None, exclude=True)
    preview_url: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PublishApproval(BaseModel):
    id: str
    draft_id: str
    account_id: str
    tenant_id: str = "local"
    approved_by: str = "local-cli"
    approver_auth_level: int = 1
    expected_content_hash: str
    mode: PublishMode = PublishMode.REQUIRE_CONFIRMATION
    approval_token: str | None = None
    approval_token_hash: str
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    used_at: datetime | None = None
    scheduled_for: str | None = None
    ai_disclosure_confirmed: bool = False
    commercial_disclosure_confirmed: bool = False
    account_identity_confirmed: bool = False
    enterprise_approval_id: str | None = None


class PublishSchedule(BaseModel):
    id: str
    draft_id: str
    account_id: str
    tenant_id: str = "local"
    approval_id: str
    scheduled_at: datetime
    status: str = "SCHEDULED"
    failure_message: str | None = None


class PublishResult(BaseModel):
    job_id: str
    draft_id: str
    account_id: str
    status: str
    note_url: str | None = None
    note_id: str | None = None
    published_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    audit: dict = Field(default_factory=dict)
