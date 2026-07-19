from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import validate_identifier


class TokenError(ValueError):
    pass


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: str
    scopes: frozenset[str]
    auth_level: int
    token_id: str
    roles: frozenset[str] = frozenset()
    amr: frozenset[str] = frozenset()
    client_id: str | None = None
    region: str | None = None
    auth_source: str = "local"

    def has(self, *required: str) -> bool:
        return "*" in self.scopes or all(scope in self.scopes for scope in required)

    @property
    def phishing_resistant(self) -> bool:
        return bool({"webauthn", "fido2", "passkey", "hwk"} & {item.lower() for item in self.amr})


def issue_token(
    *,
    subject: str,
    tenant_id: str,
    scopes: list[str] | set[str],
    auth_level: int = 1,
    ttl_seconds: int | None = None,
    roles: list[str] | set[str] | None = None,
    amr: list[str] | set[str] | None = None,
    client_id: str | None = None,
    region: str | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    now = int(time.time())
    payload = {
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "sub": subject,
        "tenant_id": tenant_id,
        "scopes": sorted(set(scopes)),
        "roles": sorted(set(roles or [])),
        "amr": sorted(set(amr or [])),
        "auth_level": int(auth_level),
        "client_id": client_id,
        "region": region,
        "iat": now,
        "nbf": now - 5,
        "exp": now + int(ttl_seconds or settings.auth_token_ttl_seconds),
        "jti": secrets.token_hex(16),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = (
        f"{_b64e(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64e(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    signature = hmac.new(
        settings.app_secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64e(signature)}"


def _normalized_claim_list(value: Any, field: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    values = value if isinstance(value, list) else str(value).replace(",", " ").split()
    normalized: set[str] = set()
    for item in values:
        entry = str(item)
        if not entry or len(entry) > 128:
            raise TokenError(f"Token contains an invalid {field}")
        if any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-."
            for char in entry
        ):
            raise TokenError(f"Token contains an invalid {field}")
        normalized.add(entry)
    return frozenset(normalized)


def _verify_local_token(token: str, settings: Settings) -> Principal:
    if not token or len(token) > 16_384:
        raise TokenError("Malformed bearer token")
    try:
        head, body, signature = token.split(".")
        signing_input = f"{head}.{body}"
        expected = hmac.new(
            settings.app_secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64d(signature)):
            raise TokenError("Invalid token signature")
        header: dict[str, Any] = json.loads(_b64d(head))
        payload: dict[str, Any] = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TokenError("Malformed bearer token") from exc
    if header.get("alg") != "HS256":
        raise TokenError("Unsupported local token algorithm")
    now = int(time.time())
    if payload.get("iss") != settings.auth_issuer or payload.get("aud") != settings.auth_audience:
        raise TokenError("Token issuer or audience mismatch")
    if int(payload.get("nbf", 0)) > now + 30 or int(payload.get("exp", 0)) <= now:
        raise TokenError("Token expired or not yet valid")
    subject = str(payload.get("sub", ""))
    tenant = str(payload.get("tenant_id", ""))
    if not subject or not tenant:
        raise TokenError("Token is missing required claims")
    try:
        validate_identifier(subject, field="subject")
        validate_identifier(tenant, field="tenant_id")
    except ValueError as exc:
        raise TokenError("Token contains an invalid subject or tenant") from exc
    scopes = _normalized_claim_list(payload.get("scopes", []), "scope")
    roles = _normalized_claim_list(payload.get("roles", []), "role")
    amr = _normalized_claim_list(payload.get("amr", []), "amr")
    auth_level = int(payload.get("auth_level", 1))
    if auth_level < 1 or auth_level > 3:
        raise TokenError("Token contains an invalid authentication level")
    return Principal(
        subject=subject,
        tenant_id=tenant,
        scopes=scopes,
        auth_level=auth_level,
        token_id=str(payload.get("jti", "")),
        roles=roles,
        amr=amr,
        client_id=str(payload.get("client_id", "")) or None,
        region=str(payload.get("region", "")) or None,
        auth_source="local",
    )


def verify_token(token: str, settings: Settings | None = None) -> Principal:
    settings = settings or get_settings()
    mode = settings.auth_mode.strip().lower()
    local_error: TokenError | None = None
    if mode in {"local", "hybrid"}:
        try:
            return _verify_local_token(token, settings)
        except TokenError as exc:
            local_error = exc
            if mode == "local":
                raise
    if mode in {"oidc", "hybrid"} and settings.oidc_issuer:
        try:
            from xhs_skill.enterprise.identity import get_oidc_verifier

            return get_oidc_verifier().verify(token)
        except TokenError:
            raise
        except Exception as exc:
            raise TokenError("OIDC token validation failed") from exc
    if local_error:
        raise local_error
    raise TokenError("No configured authentication method accepted this token")


def bearer_from_headers(headers: dict[bytes, bytes]) -> str | None:
    raw = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
    if not raw.lower().startswith("bearer "):
        return None
    return raw.split(" ", 1)[1].strip() or None
