from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.enterprise.approvals import EnterpriseApprovalService
from xhs_skill.enterprise.audit import get_audit_ledger
from xhs_skill.enterprise.costs import get_cost_budget_service
from xhs_skill.enterprise.dlp import redact_text, scan_text
from xhs_skill.enterprise.models import PluginManifest, Tenant, TenantPolicy
from xhs_skill.enterprise.plugins import PluginVerifier
from xhs_skill.enterprise.policy import get_policy_engine
from xhs_skill.enterprise.quota import BudgetExceededError
from xhs_skill.enterprise.repository import EnterpriseRepository
from xhs_skill.storage.assets import AssetStore

router = APIRouter(prefix="/v1/enterprise", tags=["enterprise"])
_repo = EnterpriseRepository()
_approval_service = EnterpriseApprovalService(_repo)


def _authorize(principal: Principal, operation: str, *, context: dict[str, Any] | None = None) -> None:
    decision = get_policy_engine().evaluate(principal, operation, context=context)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail={"reason": decision.reason, "obligations": decision.obligations})


class TenantUpdate(BaseModel):
    display_name: str | None = None
    domains: list[str] | None = None
    policy: TenantPolicy | None = None


class CostReservationRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=128)
    estimated_cost_usd: float = Field(ge=0, le=1_000_000)
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostSettlementRequest(BaseModel):
    actual_cost_usd: float = Field(ge=0, le=1_000_000)


class ApprovalCreateRequest(BaseModel):
    resource_type: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=128)
    content_hash: str | None = Field(default=None, max_length=256)
    ttl_minutes: int = Field(default=30, ge=1, le=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    decision: str
    comment: str = Field(default="", max_length=1000)


class DLPRequest(BaseModel):
    text: str = Field(max_length=2_000_000)
    redact: bool = True


class PluginVerifyRequest(BaseModel):
    manifest: PluginManifest
    asset_id: str


@router.get("/tenant", response_model=Tenant)
async def get_tenant(
    principal: Principal = Depends(require_scopes("enterprise:admin")),
) -> Tenant:
    _authorize(principal, "tenant.read")
    return _repo.get_tenant(principal.tenant_id)


@router.patch("/tenant", response_model=Tenant)
async def update_tenant(
    request: TenantUpdate,
    principal: Principal = Depends(require_scopes("enterprise:admin", min_auth_level=2)),
) -> Tenant:
    _authorize(principal, "tenant.write")
    tenant = _repo.get_tenant(principal.tenant_id)
    if request.display_name is not None:
        tenant.display_name = request.display_name[:200]
    if request.domains is not None:
        tenant.domains = sorted({item.strip().lower() for item in request.domains if item.strip()})
    if request.policy is not None:
        tenant.policy = request.policy
    saved = _repo.save_tenant(tenant)
    get_audit_ledger().append(
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        action="tenant.update",
        resource_type="tenant",
        resource_id=tenant.id,
        outcome="SUCCESS",
    )
    return saved


@router.get("/budget")
async def budget_summary(
    principal: Principal = Depends(require_scopes("billing:read")),
) -> dict:
    _authorize(principal, "budget.read")
    return await get_cost_budget_service().summary(principal.tenant_id)


@router.post("/budget/reservations")
async def reserve_cost(
    request: CostReservationRequest,
    principal: Principal = Depends(require_scopes("billing:write")),
) -> dict:
    _authorize(principal, "budget.write", context={"provider": request.provider})
    try:
        record = await get_cost_budget_service().reserve(
            tenant_id=principal.tenant_id,
            operation=request.operation,
            estimated_cost_usd=request.estimated_cost_usd,
            provider=request.provider,
            model=request.model,
            metadata=request.metadata,
        )
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return record if isinstance(record, dict) else record.model_dump(mode="json")


@router.post("/budget/reservations/{reservation_id}/settle")
async def settle_cost(
    reservation_id: str,
    request: CostSettlementRequest,
    principal: Principal = Depends(require_scopes("billing:write")),
) -> dict:
    _authorize(principal, "budget.write")
    record = await get_cost_budget_service().settle(
        principal.tenant_id, reservation_id, request.actual_cost_usd
    )
    return record if isinstance(record, dict) else record.model_dump(mode="json")


@router.post("/budget/reservations/{reservation_id}/release")
async def release_cost(
    reservation_id: str,
    principal: Principal = Depends(require_scopes("billing:write")),
) -> dict:
    _authorize(principal, "budget.write")
    record = await get_cost_budget_service().release(principal.tenant_id, reservation_id)
    return record if isinstance(record, dict) else record.model_dump(mode="json")


@router.get("/audit")
async def audit_events(
    limit: int = 100,
    principal: Principal = Depends(require_scopes("audit:read")),
) -> dict:
    _authorize(principal, "audit.read")
    events = get_audit_ledger().events(principal.tenant_id, limit=min(max(limit, 1), 10_000))
    return {"items": [item.model_dump(mode="json") for item in events], "count": len(events)}


@router.post("/audit/verify")
async def verify_audit(
    principal: Principal = Depends(require_scopes("audit:read")),
) -> dict:
    _authorize(principal, "audit.verify")
    return get_audit_ledger().verify(principal.tenant_id).model_dump(mode="json")


@router.post("/approvals")
async def create_approval(
    request: ApprovalCreateRequest,
    principal: Principal = Depends(require_scopes("publish:approve", min_auth_level=2)),
) -> dict:
    _authorize(principal, "approval.create")
    return _approval_service.create(
        principal=principal,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        content_hash=request.content_hash,
        ttl_minutes=request.ttl_minutes,
        metadata=request.metadata,
    ).model_dump(mode="json")


@router.post("/approvals/{approval_id}/decisions")
async def decide_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    principal: Principal = Depends(require_scopes("publish:approve", min_auth_level=2)),
) -> dict:
    _authorize(principal, "approval.decide")
    try:
        approval = _approval_service.decide(
            approval_id,
            principal=principal,
            decision=request.decision,
            comment=request.comment,
        )
    except (KeyError, ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return approval.model_dump(mode="json")


@router.get("/approvals/{approval_id}")
async def get_approval(
    approval_id: str,
    principal: Principal = Depends(require_scopes("publish:approve")),
) -> dict:
    _authorize(principal, "approval.create")
    approval = _repo.get_approval(principal.tenant_id, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval.model_dump(mode="json")


@router.post("/dlp/scan")
async def dlp_scan(
    request: DLPRequest,
    principal: Principal = Depends(require_scopes("content:generate")),
) -> dict:
    findings = scan_text(request.text)
    redacted, _ = redact_text(request.text) if request.redact else (request.text, findings)
    return {
        "redacted_text": redacted,
        "findings": [item.__dict__ for item in findings],
        "blocking": any(item.severity == "CRITICAL" for item in findings),
    }


@router.post("/plugins/verify")
async def verify_plugin(
    request: PluginVerifyRequest,
    principal: Principal = Depends(require_scopes("plugin:admin", min_auth_level=2)),
) -> dict:
    _authorize(principal, "plugin.register")
    asset = AssetStore().resolve(principal.tenant_id, request.asset_id)
    try:
        result = PluginVerifier().verify(request.manifest, Path(asset))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_audit_ledger().append(
        tenant_id=principal.tenant_id,
        actor_id=principal.subject,
        action="plugin.verify",
        resource_type="plugin",
        resource_id=request.manifest.name,
        outcome="SUCCESS",
        metadata={"version": request.manifest.version, "sha256": request.manifest.sha256},
    )
    return result


@router.get("/controls")
async def controls(
    principal: Principal = Depends(require_scopes("enterprise:admin")),
) -> dict:
    _authorize(principal, "tenant.read")
    tenant = _repo.get_tenant(principal.tenant_id)
    return {
        "version": "5.12.0",
        "tenant_status": tenant.status,
        "data_residency": tenant.policy.data_residency_region,
        "publish_quorum": tenant.policy.publish_approval_quorum,
        "separation_of_duties": tenant.policy.require_separation_of_duties,
        "phishing_resistant_mfa": tenant.policy.require_phishing_resistant_mfa_for_publish,
        "audit_chain_valid": get_audit_ledger().verify(principal.tenant_id).valid,
        "checked_at": datetime.now(UTC).isoformat(),
    }
