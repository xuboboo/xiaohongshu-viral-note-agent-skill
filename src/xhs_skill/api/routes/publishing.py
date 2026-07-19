from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from xhs_skill.api.dependencies import publishing_service
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.core.config import get_settings
from xhs_skill.enterprise.enforcement import enforce_enterprise_policy
from xhs_skill.schemas.content import DeliveryPackage
from xhs_skill.schemas.publishing import (
    PublishApproval,
    PublishDraft,
    PublishMode,
    PublishResult,
    PublishSchedule,
)

router = APIRouter(prefix="/v1", tags=["publishing"])


class DraftRequest(BaseModel):
    package: DeliveryPackage
    mode: PublishMode = PublishMode.REQUIRE_CONFIRMATION


class ApprovalRequest(BaseModel):
    ttl_minutes: int = Field(default=30, ge=1, le=120)
    ai_disclosure_confirmed: bool = False
    commercial_disclosure_confirmed: bool = False
    account_identity_confirmed: bool = False
    enterprise_approval_id: str | None = None


class PublishRequest(BaseModel):
    approval_token: str = Field(min_length=32, max_length=512)


class ScheduleRequest(BaseModel):
    approval_token: str = Field(min_length=32, max_length=512)
    scheduled_at: datetime


@router.post("/accounts/{account_id}/publishing/drafts", response_model=PublishDraft)
async def create_draft(
    account_id: str,
    request: DraftRequest,
    principal: Principal = Depends(require_scopes("publish:draft")),
) -> PublishDraft:
    enforce_enterprise_policy(principal, "publish.draft", context={"account_id": account_id})
    return publishing_service().create_draft(
        account_id,
        request.package,
        request.mode,
        tenant_id=principal.tenant_id,
        created_by=principal.subject,
    )


@router.get("/accounts/{account_id}/publishing/selector-health")
async def selector_health(
    account_id: str,
    principal: Principal = Depends(require_scopes("publish:draft")),
) -> dict:
    """发布页选择器 canary：返回 ok / missing / ui_version_hint。"""
    enforce_enterprise_policy(principal, "publish.draft", context={"account_id": account_id})
    return await publishing_service().check_selector_health(
        account_id,
        tenant_id=principal.tenant_id,
    )


@router.post("/publishing/drafts/{draft_id}/preview", response_model=PublishDraft)
async def preview(
    draft_id: str,
    principal: Principal = Depends(require_scopes("publish:draft")),
) -> PublishDraft:
    return await publishing_service().preview(draft_id, tenant_id=principal.tenant_id)


@router.get("/publishing/drafts/{draft_id}/preview-image")
async def preview_image(
    draft_id: str,
    principal: Principal = Depends(require_scopes("publish:draft")),
):
    draft = publishing_service().repository.load_draft(draft_id, principal.tenant_id)
    if not draft.preview_path:
        raise HTTPException(status_code=404, detail="Preview image is not available")
    path = Path(draft.preview_path).resolve()
    root = get_settings().xhs_screenshot_dir.resolve()
    if path.parent != root or path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="Preview image file is missing")
    return FileResponse(
        path,
        media_type="image/png",
        filename=f"preview-{draft.id}.png",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/publishing/drafts/{draft_id}/approve", response_model=PublishApproval)
async def approve(
    draft_id: str,
    request: ApprovalRequest,
    principal: Principal = Depends(require_scopes("publish:approve", min_auth_level=2)),
) -> PublishApproval:
    enforce_enterprise_policy(principal, "publish.approve")
    return publishing_service().approve(
        draft_id,
        request.ttl_minutes,
        tenant_id=principal.tenant_id,
        approved_by=principal.subject,
        approver_auth_level=principal.auth_level,
        ai_disclosure_confirmed=request.ai_disclosure_confirmed,
        commercial_disclosure_confirmed=request.commercial_disclosure_confirmed,
        account_identity_confirmed=request.account_identity_confirmed,
        enterprise_approval_id=request.enterprise_approval_id,
    )


@router.post("/publishing/drafts/{draft_id}/publish", response_model=PublishResult)
async def publish(
    draft_id: str,
    request: PublishRequest,
    principal: Principal = Depends(require_scopes("publish:execute", min_auth_level=2)),
) -> PublishResult:
    draft = publishing_service().repository.load_draft(draft_id, principal.tenant_id)
    enforce_enterprise_policy(
        principal, "publish.execute", context={"account_id": draft.account_id}
    )
    return await publishing_service().publish(
        draft_id,
        request.approval_token,
        tenant_id=principal.tenant_id,
    )


@router.post("/publishing/drafts/{draft_id}/schedule", response_model=PublishSchedule)
async def schedule(
    draft_id: str,
    request: ScheduleRequest,
    principal: Principal = Depends(require_scopes("publish:execute", min_auth_level=2)),
) -> PublishSchedule:
    draft = publishing_service().repository.load_draft(draft_id, principal.tenant_id)
    enforce_enterprise_policy(
        principal, "publish.execute", context={"account_id": draft.account_id}
    )
    return await publishing_service().schedule(
        draft_id,
        request.approval_token,
        request.scheduled_at,
        tenant_id=principal.tenant_id,
    )


@router.delete("/publishing/schedules/{schedule_id}")
async def cancel_schedule(
    schedule_id: str,
    principal: Principal = Depends(require_scopes("publish:execute", min_auth_level=2)),
) -> dict:
    enforce_enterprise_policy(principal, "publish.execute")
    return {
        "cancelled": await publishing_service().cancel_schedule(
            schedule_id,
            tenant_id=principal.tenant_id,
        )
    }
