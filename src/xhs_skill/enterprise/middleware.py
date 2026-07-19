from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from xhs_skill.core.auth import TokenError, bearer_from_headers, verify_token
from xhs_skill.core.config import get_settings
from xhs_skill.enterprise.audit import get_audit_ledger

logger = logging.getLogger(__name__)

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[dict]], Callable[..., Awaitable[None]]],
    Awaitable[None],
]


class EnterpriseAuditMiddleware:
    """Records request outcomes without storing request bodies or raw IP addresses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.settings = get_settings()

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http" or not self.settings.audit_enabled:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if path in {"/health/live", "/metrics"}:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        token = bearer_from_headers(headers)
        subject, tenant, actor_type = "anonymous", "system", "anonymous"
        if token:
            try:
                principal = verify_token(token, self.settings)
                subject, tenant, actor_type = principal.subject, principal.tenant_id, principal.auth_source
            except TokenError:
                subject, tenant, actor_type = "invalid-token", "system", "invalid"
        status_code = 500
        request_id = headers.get(b"x-request-id", b"").decode("utf-8", errors="ignore")[:128] or None

        async def wrapped_send(message: dict) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            peer = str((scope.get("client") or ("unknown", 0))[0])
            try:
                get_audit_ledger().append(
                    tenant_id=tenant,
                    actor_id=subject,
                    actor_type=actor_type,
                    action=f"http.{str(scope.get('method', 'UNKNOWN')).lower()}",
                    resource_type="http_endpoint",
                    resource_id=path[:512],
                    outcome="SUCCESS" if status_code < 400 else "DENIED" if status_code in {401, 403} else "ERROR",
                    request_id=request_id,
                    source_ip=peer,
                    metadata={"status_code": status_code},
                )
            except Exception:
                # The response may already be committed, so emit a security log for alerting.
                logger.exception("enterprise_audit_append_failed", extra={"path": path})
