from __future__ import annotations

import importlib
import json

from _bootstrap import bootstrap

ROOT = bootstrap()

REQUIRED_FILES = [
    "SKILL.md",
    "pyproject.toml",
    "src/xhs_skill/api/app.py",
    "src/xhs_skill/api/security.py",
    "src/xhs_skill/core/auth.py",
    "src/xhs_skill/storage/assets.py",
    "src/xhs_skill/research/service.py",
    "src/xhs_skill/generation/service.py",
    "src/xhs_skill/providers/registry.py",
    "src/xhs_skill/accounts/weight_estimator.py",
    "src/xhs_skill/browser/login_flow.py",
    "src/xhs_skill/publishing/service.py",
    "src/xhs_skill/streaming/broker.py",
    "src/xhs_skill/mcp/protocol.py",
    "src/xhs_skill/a2a/server.py",
    "src/xhs_skill/enterprise/identity.py",
    "src/xhs_skill/enterprise/scim.py",
    "src/xhs_skill/enterprise/policy.py",
    "src/xhs_skill/enterprise/approvals.py",
    "src/xhs_skill/enterprise/audit.py",
    "src/xhs_skill/enterprise/quota.py",
    "src/xhs_skill/enterprise/secrets.py",
    "src/xhs_skill/enterprise/plugins.py",
    "src/xhs_skill/enterprise/postgres.py",
    "migrations/0003_enterprise_v5.sql",
    "migrations/0004_consistency_intelligence_operations.sql",
    "src/xhs_skill/publishing/distributed.py",
    "src/xhs_skill/intelligence/embeddings.py",
    "src/xhs_skill/operations/post_publish.py",
    "scripts/generate_sbom.py",
    "scripts/generate_provenance.py",
    "scripts/verify_release.py",
]
REQUIRED_MODULES = [
    "xhs_skill.api.app",
    "xhs_skill.research.service",
    "xhs_skill.generation.service",
    "xhs_skill.providers.registry",
    "xhs_skill.accounts.service",
    "xhs_skill.browser.login_flow",
    "xhs_skill.publishing.service",
    "xhs_skill.streaming.broker",
    "xhs_skill.mcp.tools",
    "xhs_skill.a2a.server",
    "xhs_skill.enterprise.identity",
    "xhs_skill.enterprise.scim",
    "xhs_skill.enterprise.audit",
    "xhs_skill.enterprise.quota",
    "xhs_skill.enterprise.secrets",
    "xhs_skill.enterprise.plugins",
    "xhs_skill.enterprise.postgres",
]

missing = [item for item in REQUIRED_FILES if not (ROOT / item).is_file()]
import_errors = {}
for module in REQUIRED_MODULES:
    try:
        importlib.import_module(module)
    except Exception as exc:
        import_errors[module] = f"{type(exc).__name__}: {exc}"

from xhs_skill.mcp.tools import TOOL_DEFINITIONS  # noqa: E402
from xhs_skill.search import SearchRegistry  # noqa: E402

source_root = ROOT / "src" / "xhs_skill"
security_text = "\n".join(
    path.read_text(encoding="utf-8", errors="ignore") for path in source_root.rglob("*.py")
)
security_checks = {
    "no_legacy_authorized_import_path": "authorized_import_path" not in security_text,
    "no_plaintext_approval_persistence": "approval_token=approval.approval_token"
    not in security_text,
    "bearer_auth_present": "HTTPBearer"
    in (ROOT / "src/xhs_skill/api/security.py").read_text(encoding="utf-8"),
    "asset_store_present": (ROOT / "src/xhs_skill/storage/assets.py").is_file(),
    "cross_pod_scheduler_present": all(
        item
        in (ROOT / "src/xhs_skill/publishing/distributed.py").read_text(encoding="utf-8")
        for item in ("SKIP LOCKED", "lease_token", "cancellation_epoch")
    ),
    "oidc_jwks_verification": "OIDC JWKS document is too large"
    in (ROOT / "src/xhs_skill/enterprise/identity.py").read_text(encoding="utf-8"),
    "scim_lifecycle": (ROOT / "src/xhs_skill/enterprise/scim.py").is_file(),
    "enterprise_quorum": "required_quorum"
    in (ROOT / "src/xhs_skill/enterprise/approvals.py").read_text(encoding="utf-8"),
    "audit_hash_chain": "previous_hash"
    in (ROOT / "src/xhs_skill/enterprise/audit.py").read_text(encoding="utf-8"),
    "kms_or_vault": all(
        item in (ROOT / "src/xhs_skill/enterprise/secrets.py").read_text(encoding="utf-8")
        for item in ("VaultTransitBackend", "AwsKmsEnvelopeBackend")
    ),
    "signed_plugins": "Ed25519PublicKey"
    in (ROOT / "src/xhs_skill/enterprise/plugins.py").read_text(encoding="utf-8"),
    "postgres_rls": "ENABLE ROW LEVEL SECURITY"
    in (ROOT / "migrations/0003_enterprise_v5.sql").read_text(encoding="utf-8"),
}

report = {
    "root": str(ROOT),
    "version": "5.12.0",
    "installable_skill": (ROOT / "SKILL.md").is_file() and (ROOT / "pyproject.toml").is_file(),
    "missing_files": missing,
    "import_errors": import_errors,
    "mcp_tool_count": len(TOOL_DEFINITIONS),
    "configured_search_providers": SearchRegistry().list(),
    "security_checks": security_checks,
    "passed": (
        not missing
        and not import_errors
        and len(TOOL_DEFINITIONS) >= 15
        and all(security_checks.values())
    ),
}
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report["passed"] else 1)
