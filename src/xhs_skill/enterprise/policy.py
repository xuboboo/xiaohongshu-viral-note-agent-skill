from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xhs_skill.core.auth import Principal
from xhs_skill.enterprise.models import PolicyDecision, TenantStatus
from xhs_skill.enterprise.repository import EnterpriseRepository


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    scope: str
    roles: frozenset[str] = frozenset()
    high_risk: bool = False
    requires_phishing_resistant_mfa: bool = False


OPERATIONS: dict[str, OperationPolicy] = {
    "content.generate": OperationPolicy("content:generate", frozenset({"creator", "publisher", "tenant-admin"})),
    "research.search": OperationPolicy("research:read", frozenset({"creator", "analyst", "publisher", "tenant-admin"})),
    "account.read": OperationPolicy("account:read", frozenset({"analyst", "publisher", "tenant-admin"})),
    "account.sync": OperationPolicy("account:sync", frozenset({"analyst", "tenant-admin"}), high_risk=True),
    "provider.read": OperationPolicy("providers:read", frozenset({"creator", "analyst", "tenant-admin"})),
    "publish.draft": OperationPolicy("publish:draft", frozenset({"publisher", "tenant-admin"}), high_risk=True),
    "publish.approve": OperationPolicy(
        "publish:approve",
        frozenset({"approver", "tenant-admin"}),
        high_risk=True,
        requires_phishing_resistant_mfa=True,
    ),
    "tenant.read": OperationPolicy("enterprise:admin", frozenset({"tenant-admin", "security-admin"})),
    "tenant.write": OperationPolicy("enterprise:admin", frozenset({"tenant-admin"}), high_risk=True),
    "scim.read": OperationPolicy("scim:read", frozenset({"identity-admin", "tenant-admin"})),
    "scim.write": OperationPolicy("scim:write", frozenset({"identity-admin", "tenant-admin"}), high_risk=True),
    "audit.read": OperationPolicy("audit:read", frozenset({"auditor", "security-admin", "tenant-admin"})),
    "audit.verify": OperationPolicy("audit:read", frozenset({"auditor", "security-admin"})),
    "budget.read": OperationPolicy("billing:read", frozenset({"billing-admin", "tenant-admin"})),
    "budget.write": OperationPolicy("billing:write", frozenset({"billing-admin", "tenant-admin"}), high_risk=True),
    "plugin.register": OperationPolicy("plugin:admin", frozenset({"security-admin", "tenant-admin"}), high_risk=True),
    "approval.create": OperationPolicy("publish:approve", frozenset({"publisher", "approver", "tenant-admin"}), high_risk=True),
    "approval.decide": OperationPolicy(
        "publish:approve",
        frozenset({"approver", "tenant-admin"}),
        high_risk=True,
        requires_phishing_resistant_mfa=True,
    ),
    "publish.execute": OperationPolicy(
        "publish:execute",
        frozenset({"publisher", "tenant-admin"}),
        high_risk=True,
        requires_phishing_resistant_mfa=True,
    ),
}


class EnterprisePolicyEngine:
    def __init__(self, repository: EnterpriseRepository | None = None) -> None:
        self.repository = repository or EnterpriseRepository()

    def evaluate(
        self,
        principal: Principal,
        operation: str,
        *,
        resource_tenant: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        context = context or {}
        tenant_id = resource_tenant or principal.tenant_id
        matched: list[str] = []
        obligations: list[str] = []
        if tenant_id != principal.tenant_id and "platform-admin" not in principal.roles and "*" not in principal.scopes:
            return PolicyDecision(allowed=False, reason="Cross-tenant access is denied", matched_rules=["tenant_isolation"])
        tenant = self.repository.get_tenant(tenant_id)
        if tenant.status != TenantStatus.ACTIVE:
            return PolicyDecision(allowed=False, reason="Tenant is not active", matched_rules=["tenant_status"])
        policy = OPERATIONS.get(operation)
        if policy:
            if not principal.has(policy.scope):
                return PolicyDecision(allowed=False, reason=f"Missing scope: {policy.scope}", matched_rules=["scope"])
            if policy.roles and not (principal.roles & policy.roles) and "*" not in principal.scopes:
                return PolicyDecision(allowed=False, reason="Required enterprise role is missing", matched_rules=["role"])
            matched.extend(["scope", "role"])
            if policy.requires_phishing_resistant_mfa and tenant.policy.require_phishing_resistant_mfa_for_publish:
                if not principal.phishing_resistant:
                    return PolicyDecision(
                        allowed=False,
                        reason="Phishing-resistant MFA is required",
                        matched_rules=["mfa"],
                        obligations=["step_up_webauthn"],
                    )
                matched.append("mfa")
        region = (principal.region or context.get("region") or "global").lower()
        allowed_regions = set(tenant.policy.allowed_regions)
        if "global" not in allowed_regions and region not in allowed_regions:
            return PolicyDecision(
                allowed=False,
                reason=f"Region {region!r} is not allowed for this tenant",
                matched_rules=["data_residency"],
            )
        matched.append("data_residency")
        provider = context.get("provider")
        if operation == "content.generate" and tenant.policy.allowed_model_providers and not provider:
            return PolicyDecision(
                allowed=False,
                reason="An explicit model provider is required by the tenant allowlist",
                matched_rules=["provider_allowlist"],
            )
        if provider and tenant.policy.allowed_model_providers and provider not in tenant.policy.allowed_model_providers:
            return PolicyDecision(
                allowed=False,
                reason="Model provider is not allowed",
                matched_rules=["provider_allowlist"],
            )
        search_provider = context.get("search_provider")
        if operation == "research.search" and tenant.policy.allowed_search_providers and not search_provider:
            return PolicyDecision(
                allowed=False,
                reason="An explicit search provider is required by the tenant allowlist",
                matched_rules=["search_provider_allowlist"],
            )
        if search_provider and tenant.policy.allowed_search_providers and search_provider not in tenant.policy.allowed_search_providers:
            return PolicyDecision(
                allowed=False,
                reason="Search provider is not allowed",
                matched_rules=["search_provider_allowlist"],
            )
        account_id = context.get("account_id")
        if account_id and tenant.policy.allowed_publish_accounts and account_id not in tenant.policy.allowed_publish_accounts:
            return PolicyDecision(allowed=False, reason="Publishing account is not allowed", matched_rules=["account_allowlist"])
        if policy and policy.high_risk:
            obligations.extend(["audit_required", "idempotency_required"])
        return PolicyDecision(allowed=True, reason="Allowed", matched_rules=matched, obligations=obligations)


_policy_engine: EnterprisePolicyEngine | None = None


def get_policy_engine() -> EnterprisePolicyEngine:
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = EnterprisePolicyEngine()
    return _policy_engine
