from __future__ import annotations

from fastapi import APIRouter

from xhs_skill.core.config import get_settings
from xhs_skill.enterprise.identity import get_oidc_verifier

router = APIRouter(tags=["enterprise-identity"])


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource() -> dict:
    settings = get_settings()
    if not settings.oidc_issuer:
        return {
            "resource": settings.oauth_resource_identifier.rstrip("/"),
            "authorization_servers": [],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [],
        }
    return get_oidc_verifier().protected_resource_metadata()


@router.get("/.well-known/oauth-protected-resource/mcp")
async def mcp_oauth_protected_resource() -> dict:
    payload = await oauth_protected_resource()
    payload["resource"] = get_settings().oauth_resource_identifier.rstrip("/") + "/mcp"
    return payload
