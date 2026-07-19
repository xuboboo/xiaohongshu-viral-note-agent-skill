from __future__ import annotations

import ipaddress
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from xhs_skill.core.auth import TokenError, bearer_from_headers, verify_token
from xhs_skill.core.concurrency import get_concurrency_controller
from xhs_skill.core.config import get_settings
from xhs_skill.core.errors import XHSSkillError
from xhs_skill.core.metrics import INFLIGHT, OVERLOADS, REQUEST_DURATION, REQUESTS

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[dict]], Callable[..., Awaitable[None]]],
    Awaitable[None],
]


class HighConcurrencyMiddleware:
    """Backpressure, request-size limits and proxy-safe rate limiting."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.settings = get_settings()
        self.controller = get_concurrency_controller()
        self._trusted_proxy_networks = []
        for item in self.settings.trusted_proxy_cidrs.split(","):
            value = item.strip()
            if value:
                self._trusted_proxy_networks.append(ipaddress.ip_network(value, strict=False))

    def _client_ip(self, scope: dict, headers: dict[bytes, bytes]) -> str:
        peer = str((scope.get("client") or ("unknown", 0))[0])
        try:
            peer_ip = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        trusted = any(peer_ip in network for network in self._trusted_proxy_networks)
        if trusted:
            forwarded = headers.get(b"x-forwarded-for", b"").decode("utf-8", errors="ignore")
            if forwarded:
                candidate = forwarded.split(",", 1)[0].strip()
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    pass
        return str(peer_ip)

    def _tenant(self, headers: dict[bytes, bytes]) -> str:
        token = bearer_from_headers(headers)
        if not token:
            return "anonymous"
        try:
            return verify_token(token, self.settings).tenant_id
        except TokenError:
            return "invalid-token"

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        tenant = self._tenant(headers)
        client_ip = self._client_ip(scope, headers)
        rate_key = f"{tenant}:{client_ip}"
        supplied_request_id = headers.get(b"x-request-id", b"").decode("utf-8", errors="ignore")
        request_id = supplied_request_id[:128] if supplied_request_id else str(uuid4())
        method = scope.get("method", "UNKNOWN")
        started = time.monotonic()
        final_status = 500
        body_bytes = 0
        path = scope.get("path", "")
        body_limit = (
            self.settings.asset_upload_max_bytes + 1_048_576
            if path == "/v1/assets"
            else self.settings.max_request_body_bytes
        )

        async def limited_receive() -> dict:
            nonlocal body_bytes
            message: dict = await receive()
            if message.get("type") == "http.request":
                body_bytes += len(message.get("body", b""))
                if body_bytes > body_limit:
                    raise ValueError("REQUEST_BODY_TOO_LARGE")
            return message

        try:
            remaining, _ = await self.controller.rate_limiter.require(rate_key)
            is_stream = path.endswith("/events") or (path == "/mcp" and method == "GET")
            async with self.controller.request_slot(tenant, streaming=is_stream):
                INFLIGHT.inc()

                async def wrapped_send(message: dict) -> None:
                    nonlocal final_status
                    if message["type"] == "http.response.start":
                        final_status = int(message["status"])
                        response_headers = list(message.get("headers", []))
                        response_headers.extend(
                            [
                                (b"x-request-id", request_id.encode()),
                                (b"x-ratelimit-remaining", str(max(0, int(remaining))).encode()),
                                (b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"no-referrer"),
                                (b"cache-control", b"no-store"),
                            ]
                        )
                        message["headers"] = response_headers
                    await send(message)

                try:
                    await self.app(scope, limited_receive, wrapped_send)
                finally:
                    INFLIGHT.dec()
        except ValueError as exc:
            if str(exc) != "REQUEST_BODY_TOO_LARGE":
                raise
            final_status = 413
            body = json.dumps(
                {
                    "error": {
                        "code": "REQUEST_BODY_TOO_LARGE",
                        "message": "Request body exceeds configured limit",
                    }
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"x-request-id", request_id.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body, "more_body": False})
        except XHSSkillError as exc:
            final_status = exc.status_code
            OVERLOADS.labels(code=exc.code).inc()
            body = json.dumps(
                {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
                ensure_ascii=False,
            ).encode("utf-8")
            retry_after = exc.details.get("retry_after_seconds")
            response_headers = [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"x-request-id", request_id.encode()),
            ]
            if retry_after is not None:
                response_headers.append(
                    (b"retry-after", str(max(1, int(float(retry_after)))).encode())
                )
            await send(
                {
                    "type": "http.response.start",
                    "status": exc.status_code,
                    "headers": response_headers,
                }
            )
            await send({"type": "http.response.body", "body": body, "more_body": False})
        finally:
            REQUESTS.labels(method=method, status_class=f"{final_status // 100}xx").inc()
            REQUEST_DURATION.labels(method=method).observe(time.monotonic() - started)
