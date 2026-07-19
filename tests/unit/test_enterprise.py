from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from xhs_skill.core.auth import Principal
from xhs_skill.core.config import Settings
from xhs_skill.enterprise.approvals import EnterpriseApprovalService
from xhs_skill.enterprise.audit import AuditLedger
from xhs_skill.enterprise.dlp import contains_blocking_secret, redact_text, scan_text
from xhs_skill.enterprise.models import ApprovalState, PluginManifest, TenantPolicy
from xhs_skill.enterprise.plugins import PluginVerifier
from xhs_skill.enterprise.quota import BudgetExceededError, CostLedger
from xhs_skill.enterprise.repository import EnterpriseRepository
from xhs_skill.enterprise.secrets import LocalAesGcmBackend


def settings_for(tmp_path: Path, **updates: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "app_secret_key": "Aa1!" + "x" * 48,
        "enterprise_data_dir": tmp_path / "enterprise",
        "audit_dir": tmp_path / "audit",
        "plugin_trust_store": tmp_path / "trust.json",
        "object_storage_dir": tmp_path / "objects",
        "xhs_session_dir": tmp_path / "sessions",
        "xhs_screenshot_dir": tmp_path / "screens",
        "xhs_manual_export_dir": tmp_path / "exports",
    }
    values.update(updates)
    return Settings(**values)


def principal(subject: str, *, tenant: str = "tenant-a", amr: set[str] | None = None) -> Principal:
    return Principal(
        subject=subject,
        tenant_id=tenant,
        scopes=frozenset({"publish:approve", "enterprise:admin", "*"}),
        roles=frozenset({"approver", "tenant-admin"}),
        amr=frozenset(amr or {"webauthn"}),
        auth_level=3,
        token_id=f"token-{subject}",
    )


def test_audit_chain_detects_tampering(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, audit_hmac_key="Bb2@" + "y" * 48)
    ledger = AuditLedger(settings)
    ledger.append(
        tenant_id="tenant-a",
        actor_id="alice",
        action="tenant.update",
        resource_type="tenant",
        outcome="SUCCESS",
    )
    ledger.append(
        tenant_id="tenant-a",
        actor_id="bob",
        action="publish.execute",
        resource_type="note",
        resource_id="note-1",
        outcome="SUCCESS",
    )
    verified = ledger.verify("tenant-a")
    assert verified.valid is True
    assert verified.events_checked == 2

    path = settings.audit_dir / "tenant-a.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["outcome"] = "TAMPERED"
    lines[0] = json.dumps(payload)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert ledger.verify("tenant-a").valid is False


def test_cost_ledger_enforces_hard_budget(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = EnterpriseRepository(settings)
    tenant = repository.get_tenant("tenant-a")
    tenant.policy = TenantPolicy(daily_cost_limit_usd=1.0, monthly_cost_limit_usd=2.0)
    repository.save_tenant(tenant)
    ledger = CostLedger(settings, repository)

    reservation = ledger.reserve(
        tenant_id="tenant-a", operation="content.generate", estimated_cost_usd=0.7
    )
    with pytest.raises(BudgetExceededError):
        ledger.reserve(tenant_id="tenant-a", operation="content.generate", estimated_cost_usd=0.4)
    settled = ledger.settle("tenant-a", reservation.id, 0.5)
    assert settled.status == "SETTLED"
    assert ledger.summary("tenant-a").daily_committed_usd == pytest.approx(0.5)


def test_enterprise_approval_requires_quorum_separation_and_webauthn(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, audit_hmac_key="Cc3#" + "z" * 48)
    repository = EnterpriseRepository(settings)
    tenant = repository.get_tenant("tenant-a")
    tenant.policy.publish_approval_quorum = 2
    repository.save_tenant(tenant)
    service = EnterpriseApprovalService(repository, AuditLedger(settings))

    approval = service.create(
        principal=principal("requester"),
        resource_type="publish_draft",
        resource_id="draft-1",
        content_hash="abc",
    )
    with pytest.raises(PermissionError):
        service.decide(approval.id, principal=principal("requester"), decision="APPROVE")
    with pytest.raises(PermissionError):
        service.decide(
            approval.id,
            principal=principal("approver-one", amr={"pwd"}),
            decision="APPROVE",
        )

    first = service.decide(
        approval.id, principal=principal("approver-one"), decision="APPROVE"
    )
    assert first.state == ApprovalState.PENDING
    second = service.decide(
        approval.id, principal=principal("approver-two"), decision="APPROVE"
    )
    assert second.state == ApprovalState.APPROVED
    assert service.require_approved(
        approval.id,
        tenant_id="tenant-a",
        resource_type="publish_draft",
        resource_id="draft-1",
        content_hash="abc",
    ).state == ApprovalState.APPROVED


def test_local_envelope_encryption_binds_context(tmp_path: Path) -> None:
    backend = LocalAesGcmBackend(settings_for(tmp_path))
    envelope = backend.encrypt(b"credential", context={"tenant_id": "tenant-a"})
    assert backend.decrypt(envelope, context={"tenant_id": "tenant-a"}) == b"credential"
    with pytest.raises(InvalidTag):
        backend.decrypt(envelope, context={"tenant_id": "tenant-b"})


def test_dlp_redacts_pii_and_blocks_secrets() -> None:
    text = "联系 me@example.com，手机 13800138000，api_key=ABCDEFGHIJKLMNOPQRSTUVWX"
    findings = scan_text(text)
    assert {item.kind for item in findings} >= {"EMAIL", "CN_MOBILE", "GENERIC_API_KEY"}
    redacted, _ = redact_text(text)
    assert "me@example.com" not in redacted
    assert contains_blocking_secret(text) is True


def test_signed_plugin_manifest(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    artifact = tmp_path / "plugin.pyz"
    artifact.write_bytes(b"plugin-artifact-v1")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    settings.plugin_trust_store.parent.mkdir(parents=True, exist_ok=True)
    settings.plugin_trust_store.write_text(
        json.dumps({"keys": {"publisher-key": base64.b64encode(public_raw).decode("ascii")}}),
        encoding="utf-8",
    )
    unsigned = PluginManifest(
        name="enterprise-addon",
        version="1.0.0",
        entrypoint="addon:main",
        publisher="Example Corp",
        sha256=digest,
        signature="placeholder",
        public_key_id="publisher-key",
    )
    canonical = PluginVerifier._canonical(unsigned)
    signature = base64.b64encode(private_key.sign(canonical)).decode("ascii")
    manifest = unsigned.model_copy(update={"signature": signature})
    result = PluginVerifier(settings).verify(manifest, artifact)
    assert result["verified"] is True


def test_oidc_verifier_binds_resource_and_rejects_inactive_scim_user(tmp_path: Path) -> None:
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

    from xhs_skill.core.auth import TokenError
    from xhs_skill.enterprise.identity import DiscoveryDocument, OIDCVerifier
    from xhs_skill.enterprise.models import EnterpriseUser

    resource = "https://skill.example.com"
    settings = settings_for(
        tmp_path,
        auth_mode="oidc",
        oidc_issuer="https://id.example.com",
        oidc_audience="xhs-skill-api",
        oauth_resource_identifier=resource,
        scim_reject_inactive_users=True,
    )
    private_key = generate_private_key(public_exponent=65537, key_size=2048)
    verifier = OIDCVerifier(settings)
    verifier._discovery = DiscoveryDocument(
        issuer=settings.oidc_issuer,
        jwks_uri="https://id.example.com/jwks",
        authorization_endpoint=None,
        token_endpoint=None,
        fetched_at=time.time(),
    )
    cast(Any, verifier)._signing_key = lambda _token, _header: private_key.public_key()
    now = int(time.time())
    claims = {
        "iss": settings.oidc_issuer,
        "sub": "managed-user",
        "aud": [settings.oidc_audience, resource],
        "tenant_id": "tenant-a",
        "roles": ["creator"],
        "scope": "research:read",
        "amr": ["webauthn"],
        "iat": now,
        "nbf": now - 1,
        "exp": now + 300,
        "jti": "oidc-test-token",
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test"})
    verified = verifier.verify(token)
    assert verified.auth_source == "oidc"
    assert verified.phishing_resistant is True
    assert "content:generate" in verified.scopes

    repository = EnterpriseRepository(settings)
    repository.save_user(
        EnterpriseUser(
            id="managed-user",
            tenant_id="tenant-a",
            user_name="managed-user",
            active=False,
        )
    )
    with pytest.raises(TokenError, match="inactive"):
        verifier.verify(token)
    managed = repository.get_user("tenant-a", "managed-user")
    assert managed is not None
    managed.active = True
    repository.save_user(managed)

    wrong_resource = jwt.encode(
        {**claims, "aud": [settings.oidc_audience]},
        private_key,
        algorithm="RS256",
        headers={"kid": "test"},
    )
    with pytest.raises(TokenError, match="audience-bound"):
        verifier.verify(wrong_resource)


@pytest.mark.asyncio
async def test_postgres_stores_share_one_pool_per_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys
    from types import SimpleNamespace

    from xhs_skill.enterprise.postgres import EnterprisePostgresStore

    class FakePool:
        def __init__(self) -> None:
            self.closed = 0

        async def close(self) -> None:
            self.closed += 1

    created: list[FakePool] = []

    async def create_pool(*args: Any, **kwargs: Any) -> FakePool:
        pool = FakePool()
        created.append(pool)
        return pool

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(create_pool=create_pool))
    settings = settings_for(
        tmp_path,
        database_url="postgresql://user:password@localhost/test-shared-pool",
    )
    first = EnterprisePostgresStore(settings)
    second = EnterprisePostgresStore(settings)
    await first.connect()
    await second.connect()
    assert len(created) == 1
    assert first.pool is second.pool
    pool = created[0]
    await first.close()
    assert pool.closed == 0
    await second.close()
    assert pool.closed == 1
