from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from xhs_skill.api.app import create_app
from xhs_skill.core.auth import issue_token
from xhs_skill.core.config import get_settings


def enterprise_headers(*, subject: str, tenant: str, roles: set[str], scopes: set[str]) -> dict[str, str]:
    token = issue_token(
        subject=subject,
        tenant_id=tenant,
        scopes=scopes,
        roles=roles,
        amr={"webauthn"},
        auth_level=3,
        ttl_seconds=3600,
    )
    return {"Authorization": f"Bearer {token}"}


def _force_enterprise_profile(monkeypatch) -> None:
    """企业契约测试需要挂载 enterprise/scim 路由。"""
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "enterprise")
    monkeypatch.setenv("ENTERPRISE_ENABLED", "true")
    monkeypatch.setenv("SCIM_ENABLED", "true")
    get_settings.cache_clear()


def test_oauth_resource_metadata_is_public(monkeypatch) -> None:
    _force_enterprise_profile(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        assert "resource" in response.json()
        mcp = client.get("/.well-known/oauth-protected-resource/mcp")
        assert mcp.status_code == 200
        assert mcp.json()["resource"].endswith("/mcp")


def test_enterprise_controls_and_scim_lifecycle(monkeypatch) -> None:
    _force_enterprise_profile(monkeypatch)
    tenant = f"tenant-{uuid4().hex[:12]}"
    user_name = f"user-{uuid4().hex[:12]}"
    admin_headers = enterprise_headers(
        subject="tenant-admin-user",
        tenant=tenant,
        roles={"tenant-admin"},
        scopes={"enterprise:admin", "audit:read", "billing:read"},
    )
    scim_headers = enterprise_headers(
        subject="identity-admin-user",
        tenant=tenant,
        roles={"identity-admin"},
        scopes={"scim:read", "scim:write"},
    )
    with TestClient(create_app()) as client:
        tenant_response = client.get("/v1/enterprise/tenant", headers=admin_headers)
        assert tenant_response.status_code == 200
        assert tenant_response.json()["id"] == tenant
        controls = client.get("/v1/enterprise/controls", headers=admin_headers)
        assert controls.status_code == 200
        assert controls.json()["version"] == "5.12.0"
        budget = client.get("/v1/enterprise/budget", headers=admin_headers)
        assert budget.status_code == 200
        assert budget.json()["tenant_id"] == tenant

        created = client.post(
            "/scim/v2/Users",
            headers=scim_headers,
            json={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": user_name,
                "displayName": "Enterprise Test User",
                "active": True,
                "roles": [{"value": "creator"}],
            },
        )
        assert created.status_code == 201
        user_id = created.json()["id"]
        listed = client.get(
            f'/scim/v2/Users?filter=userName%20eq%20%22{user_name}%22',
            headers=scim_headers,
        )
        assert listed.status_code == 200
        assert listed.json()["totalResults"] == 1
        patched = client.patch(
            f"/scim/v2/Users/{user_id}",
            headers=scim_headers,
            json={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "active", "value": False}],
            },
        )
        assert patched.status_code == 200
        assert patched.json()["active"] is False
        deleted = client.delete(f"/scim/v2/Users/{user_id}", headers=scim_headers)
        assert deleted.status_code == 204
