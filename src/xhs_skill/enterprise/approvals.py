from __future__ import annotations

from datetime import UTC, datetime, timedelta

from xhs_skill.core.auth import Principal
from xhs_skill.enterprise.audit import AuditLedger, get_audit_ledger
from xhs_skill.enterprise.models import (
    ApprovalDecision,
    ApprovalState,
    EnterpriseApproval,
)
from xhs_skill.enterprise.repository import EnterpriseRepository


class EnterpriseApprovalService:
    def __init__(
        self,
        repository: EnterpriseRepository | None = None,
        audit: AuditLedger | None = None,
    ) -> None:
        self.repository = repository or EnterpriseRepository()
        self.audit = audit or get_audit_ledger()

    def create(
        self,
        *,
        principal: Principal,
        resource_type: str,
        resource_id: str,
        content_hash: str | None = None,
        ttl_minutes: int = 30,
        metadata: dict | None = None,
    ) -> EnterpriseApproval:
        tenant = self.repository.get_tenant(principal.tenant_id)
        approval = EnterpriseApproval(
            tenant_id=principal.tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            requested_by=principal.subject,
            required_quorum=tenant.policy.publish_approval_quorum,
            separation_of_duties=tenant.policy.require_separation_of_duties,
            require_phishing_resistant_mfa=(
                tenant.policy.require_phishing_resistant_mfa_for_publish
            ),
            content_hash=content_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=max(1, min(ttl_minutes, 120))),
            metadata=metadata or {},
        )
        self.repository.save_approval(approval)
        self.audit.append(
            tenant_id=principal.tenant_id,
            actor_id=principal.subject,
            action="approval.create",
            resource_type=resource_type,
            resource_id=resource_id,
            outcome="SUCCESS",
            metadata={"approval_id": approval.id, "quorum": approval.required_quorum},
        )
        return approval

    @staticmethod
    def _approved_actors(approval: EnterpriseApproval) -> set[str]:
        return {
            item.approver_id
            for item in approval.decisions
            if item.decision.upper() == "APPROVE"
        }

    def decide(
        self,
        approval_id: str,
        *,
        principal: Principal,
        decision: str,
        comment: str = "",
    ) -> EnterpriseApproval:
        approval = self.repository.get_approval(principal.tenant_id, approval_id)
        if approval is None:
            raise KeyError("Approval workflow not found")
        now = datetime.now(UTC)
        if approval.state != ApprovalState.PENDING:
            raise ValueError("Approval workflow is not pending")
        if now >= approval.expires_at:
            approval.state = ApprovalState.EXPIRED
            self.repository.save_approval(approval)
            raise ValueError("Approval workflow expired")
        normalized = decision.strip().upper()
        if normalized not in {"APPROVE", "REJECT"}:
            raise ValueError("Decision must be APPROVE or REJECT")
        if approval.separation_of_duties and principal.subject == approval.requested_by:
            raise PermissionError("Requester cannot approve their own high-risk operation")
        if principal.subject in {item.approver_id for item in approval.decisions}:
            raise PermissionError("Approver has already submitted a decision")
        if approval.require_phishing_resistant_mfa and not principal.phishing_resistant:
            raise PermissionError("Phishing-resistant MFA is required for approval")
        approval.decisions.append(
            ApprovalDecision(
                approver_id=principal.subject,
                decision=normalized,
                comment=comment[:1000],
                auth_level=principal.auth_level,
                amr=sorted(principal.amr),
            )
        )
        if normalized == "REJECT":
            approval.state = ApprovalState.REJECTED
        elif len(self._approved_actors(approval)) >= approval.required_quorum:
            approval.state = ApprovalState.APPROVED
        self.repository.save_approval(approval)
        self.audit.append(
            tenant_id=principal.tenant_id,
            actor_id=principal.subject,
            action="approval.decide",
            resource_type=approval.resource_type,
            resource_id=approval.resource_id,
            outcome=normalized,
            metadata={"approval_id": approval.id, "state": approval.state},
        )
        return approval

    def require_approved(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        content_hash: str | None = None,
    ) -> EnterpriseApproval:
        approval = self.repository.get_approval(tenant_id, approval_id)
        if approval is None or approval.state != ApprovalState.APPROVED:
            raise PermissionError("Enterprise approval quorum has not been satisfied")
        if approval.expires_at <= datetime.now(UTC):
            raise PermissionError("Enterprise approval workflow expired")
        if approval.resource_type != resource_type or approval.resource_id != resource_id:
            raise PermissionError("Enterprise approval is bound to another resource")
        if content_hash is not None and approval.content_hash != content_hash:
            raise PermissionError("Enterprise approval content hash mismatch")
        return approval
