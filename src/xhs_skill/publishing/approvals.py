from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.schemas.publishing import PublishApproval, PublishDraft, PublishMode


def _token_hash(token: str, settings: Settings) -> str:
    return hmac.new(
        settings.app_secret_key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def create_approval(
    draft: PublishDraft,
    *,
    approved_by: str = "local-cli",
    approver_auth_level: int = 2,
    mode: PublishMode = PublishMode.REQUIRE_CONFIRMATION,
    ttl_minutes: int = 30,
    ai_disclosure_confirmed: bool = False,
    commercial_disclosure_confirmed: bool = False,
    account_identity_confirmed: bool = False,
    enterprise_approval_id: str | None = None,
    settings: Settings | None = None,
) -> PublishApproval:
    settings = settings or get_settings()
    if approver_auth_level < 2:
        raise PermissionError("Step-up authentication is required for publication approval")
    if ttl_minutes < 1 or ttl_minutes > 120:
        raise ValueError("Approval TTL must be between 1 and 120 minutes")
    approved_at = datetime.now(UTC)
    expires_at = approved_at + timedelta(minutes=ttl_minutes)
    token = secrets.token_urlsafe(32)
    return PublishApproval(
        id=str(uuid4()),
        draft_id=draft.id,
        account_id=draft.account_id,
        tenant_id=draft.tenant_id,
        approved_by=approved_by,
        approver_auth_level=approver_auth_level,
        expected_content_hash=draft.content_hash,
        mode=mode,
        approval_token=token,
        approval_token_hash=_token_hash(token, settings),
        approved_at=approved_at,
        expires_at=expires_at,
        ai_disclosure_confirmed=ai_disclosure_confirmed,
        commercial_disclosure_confirmed=commercial_disclosure_confirmed,
        account_identity_confirmed=account_identity_confirmed,
        enterprise_approval_id=enterprise_approval_id,
    )


def validate_approval(
    draft: PublishDraft,
    approval: PublishApproval,
    provided_token: str,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    if now >= approval.expires_at:
        raise ValueError("Approval expired")
    if approval.used_at is not None:
        raise ValueError("Approval token has already been consumed")
    if approval.scheduled_for is not None:
        raise ValueError("Approval token is bound to a scheduled publication")
    if approval.tenant_id != draft.tenant_id or approval.account_id != draft.account_id:
        raise ValueError("Approval scope does not match the draft")
    if approval.expected_content_hash != draft.content_hash:
        raise ValueError("Content hash changed after approval")
    if approval.approver_auth_level < 2:
        raise ValueError("Approval was not created with step-up authentication")
    if not hmac.compare_digest(approval.approval_token_hash, _token_hash(provided_token, settings)):
        raise ValueError("Invalid approval token")
