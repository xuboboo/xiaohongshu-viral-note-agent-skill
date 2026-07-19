from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from xhs_skill.core.auth import Principal, TokenError, verify_token
from xhs_skill.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    settings = get_settings()
    if not settings.auth_required and settings.app_env.lower() in {"development", "test"}:
        return Principal("local-development", "local", frozenset({"*"}), 2, "local")
    if credentials is None or credentials.scheme.lower() != "bearer":
        metadata = settings.oauth_resource_identifier.rstrip("/") + "/.well-known/oauth-protected-resource"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication is required",
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{metadata}"'},
        )
    try:
        return verify_token(credentials.credentials, settings)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={
                "WWW-Authenticate": (
                    'Bearer error="invalid_token", resource_metadata="'
                    + settings.oauth_resource_identifier.rstrip("/")
                    + '/.well-known/oauth-protected-resource"'
                )
            },
        ) from exc


def require_scopes(*scopes: str, min_auth_level: int = 1) -> Callable[..., Principal]:
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.auth_level < min_auth_level:
            raise HTTPException(status_code=403, detail="Step-up authentication is required")
        if not principal.has(*scopes):
            raise HTTPException(status_code=403, detail=f"Missing required scope: {', '.join(scopes)}")
        return principal

    return dependency
