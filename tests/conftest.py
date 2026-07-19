from __future__ import annotations

import os

# Prefer fixture in automated tests so research calls without keys don't delegate.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SEARCH_AUTO_FALLBACK", "fixture")

import pytest

from xhs_skill.core.auth import issue_token
from xhs_skill.core.config import get_settings

get_settings.cache_clear()

ALL_SCOPES = {
    "admin:read",
    "assets:write",
    "jobs:admin",
    "experiments:write",
    "experiments:read",
    "content:plan",
    "assets:read",
    "research:read",
    "content:generate",
    "account:read",
    "account:sync",
    "auth:manage",
    "publish:draft",
    "publish:approve",
    "publish:execute",
    "jobs:read",
    "jobs:write",
    "providers:read",
    "mcp:invoke",
    "a2a:invoke",
    "enterprise:admin",
    "scim:read",
    "scim:write",
    "audit:read",
    "billing:read",
    "billing:write",
    "plugin:admin",
}


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = issue_token(
        subject="test-user",
        tenant_id="test-tenant",
        scopes=ALL_SCOPES,
        roles={"tenant-admin"},
        amr={"webauthn"},
        auth_level=3,
        ttl_seconds=3600,
    )
    return {"Authorization": f"Bearer {token}"}
