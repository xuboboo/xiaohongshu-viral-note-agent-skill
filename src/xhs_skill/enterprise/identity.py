from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
import jwt

from xhs_skill.core.auth import Principal, TokenError
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.security import validate_public_url
from xhs_skill.enterprise.repository import EnterpriseRepository

ROLE_SCOPES: dict[str, set[str]] = {
    "creator": {"research:read", "content:generate", "jobs:read", "jobs:write"},
    "analyst": {"research:read", "account:read", "audit:read"},
    "publisher": {"publish:draft", "publish:execute", "account:read", "auth:manage"},
    "approver": {"publish:approve"},
    "identity-admin": {"scim:read", "scim:write"},
    "billing-admin": {"billing:read", "billing:write"},
    "security-admin": {"audit:read", "plugin:admin", "enterprise:admin"},
    "tenant-admin": {
        "enterprise:admin", "scim:read", "scim:write", "billing:read", "billing:write",
        "audit:read", "plugin:admin", "publish:draft", "publish:approve",
        "publish:execute", "research:read", "content:generate", "account:read",
        "account:sync", "auth:manage", "jobs:read", "jobs:write", "providers:read",
        "mcp:invoke", "a2a:invoke",
    },
}

@dataclass(slots=True)
class DiscoveryDocument:
    issuer: str
    jwks_uri: str
    authorization_endpoint: str | None
    token_endpoint: str | None
    fetched_at: float


class OIDCVerifier:
    """OIDC access-token verifier with issuer/audience/algorithm pinning and JWKS caching."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.RLock()
        self._discovery: DiscoveryDocument | None = None
        self._jwks: dict[str, jwt.PyJWK] = {}
        self._jwks_fetched_at: float = 0.0

    def _discovery_url(self) -> str:
        explicit = self.settings.oidc_discovery_url
        if explicit:
            return validate_public_url(explicit)
        issuer = self.settings.oidc_issuer.rstrip("/")
        if not issuer:
            raise TokenError("OIDC issuer is not configured")
        return validate_public_url(f"{issuer}/.well-known/openid-configuration")

    def discovery(self) -> DiscoveryDocument:
        now = time.time()
        with self._lock:
            if self._discovery and now - self._discovery.fetched_at < self.settings.oidc_cache_ttl_seconds:
                return self._discovery
            response = httpx.get(
                self._discovery_url(),
                timeout=self.settings.oidc_http_timeout_seconds,
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            issuer = str(payload.get("issuer", "")).rstrip("/")
            expected = self.settings.oidc_issuer.rstrip("/")
            if not issuer or issuer != expected:
                raise TokenError("OIDC discovery issuer mismatch")
            jwks_uri = validate_public_url(str(payload.get("jwks_uri", "")))
            self._discovery = DiscoveryDocument(
                issuer=issuer,
                jwks_uri=jwks_uri,
                authorization_endpoint=payload.get("authorization_endpoint"),
                token_endpoint=payload.get("token_endpoint"),
                fetched_at=now,
            )
            self._jwks = {}
            self._jwks_fetched_at = 0.0
            return self._discovery


    def _load_jwks(self, *, force: bool = False) -> dict[str, jwt.PyJWK]:
        now = time.time()
        with self._lock:
            if (
                self._jwks
                and not force
                and now - self._jwks_fetched_at < self.settings.oidc_cache_ttl_seconds
            ):
                return self._jwks
            discovery = self.discovery()
            response = httpx.get(
                discovery.jwks_uri,
                timeout=self.settings.oidc_http_timeout_seconds,
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            if len(response.content) > 1_048_576:
                raise TokenError("OIDC JWKS document is too large")
            payload = response.json()
            raw_keys = payload.get("keys", []) if isinstance(payload, dict) else []
            if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 100:
                raise TokenError("OIDC JWKS document has an invalid key set")
            try:
                key_set = jwt.PyJWKSet.from_dict({"keys": raw_keys})
            except jwt.PyJWTError as exc:
                raise TokenError("OIDC JWKS document is invalid") from exc
            keys = {
                str(key.key_id): key
                for key in key_set.keys
                if key.key_id and key.algorithm_name in {
                    item.strip()
                    for item in self.settings.oidc_allowed_algorithms.split(",")
                    if item.strip()
                }
            }
            if not keys:
                raise TokenError("OIDC JWKS contains no approved signing key")
            self._jwks = keys
            self._jwks_fetched_at = now
            return keys

    def _signing_key(self, token: str, header: dict[str, Any]) -> Any:
        key_id = str(header.get("kid", ""))
        if not key_id or len(key_id) > 256:
            raise TokenError("OIDC token is missing a valid key identifier")
        key = self._load_jwks().get(key_id)
        if key is None:
            key = self._load_jwks(force=True).get(key_id)
        if key is None:
            raise TokenError("OIDC signing key is not trusted")
        return key.key

    @staticmethod
    def _claim_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item for item in value.replace(",", " ").split() if item]
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        return []

    def verify(self, token: str) -> Principal:
        if not token or len(token) > 32_768:
            raise TokenError("Malformed OIDC token")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenError("Malformed OIDC token") from exc
        algorithm = str(header.get("alg", ""))
        allowed = {item.strip() for item in self.settings.oidc_allowed_algorithms.split(",") if item.strip()}
        if algorithm not in allowed or algorithm.startswith("HS") or algorithm == "none":
            raise TokenError("OIDC token algorithm is not allowed")
        discovery = self.discovery()
        try:
            signing_key = self._signing_key(token, header)
            payload: dict[str, Any] = jwt.decode(
                token,
                signing_key,
                algorithms=sorted(allowed),
                audience=sorted(
                    {
                        value
                        for value in (
                            self.settings.oidc_audience,
                            self.settings.oauth_resource_identifier,
                        )
                        if value
                    }
                ),
                issuer=discovery.issuer,
                leeway=self.settings.oidc_clock_skew_seconds,
                options={
                    "require": ["exp", "iat", "iss", "sub", "aud"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.PyJWTError as exc:
            raise TokenError("OIDC token validation failed") from exc
        subject = str(payload.get("sub", ""))
        tenant_id = str(payload.get(self.settings.oidc_tenant_claim, ""))
        if not tenant_id:
            tenant_id = str(payload.get("organization_id", payload.get("org_id", "")))
        if not subject or not tenant_id:
            raise TokenError("OIDC token is missing subject or tenant claim")
        scopes = self._claim_list(payload.get(self.settings.oidc_scope_claim, payload.get("scope")))
        roles = self._claim_list(payload.get(self.settings.oidc_roles_claim, payload.get("roles")))
        repository = EnterpriseRepository(self.settings)
        managed_user = repository.get_user(tenant_id, subject) or repository.find_user_by_name(
            tenant_id, subject
        )
        if managed_user is not None:
            if not managed_user.active and self.settings.scim_reject_inactive_users:
                raise TokenError("SCIM-managed user is inactive")
            roles.extend(managed_user.roles)
            for group_id in managed_user.groups:
                group = repository.get_group(tenant_id, group_id)
                if group:
                    roles.extend(group.roles)
        elif self.settings.scim_require_managed_user:
            raise TokenError("OIDC subject is not provisioned through SCIM")
        roles = sorted(set(roles))
        for role in roles:
            scopes.extend(ROLE_SCOPES.get(role, set()))
        scopes = sorted(set(scopes))
        amr = self._claim_list(payload.get("amr"))
        acr = str(payload.get("acr", ""))
        phishing_resistant = any(item.lower() in {"webauthn", "hwk", "passkey", "fido2"} for item in amr)
        auth_level = 3 if phishing_resistant else (2 if len(amr) >= 2 or acr else 1)
        audience = payload.get("aud")
        aud_list = [audience] if isinstance(audience, str) else [str(item) for item in audience or []]
        if self.settings.oauth_resource_identifier and self.settings.oauth_resource_identifier not in aud_list:
            raise TokenError("OIDC token is not audience-bound to this resource")
        return Principal(
            subject=subject,
            tenant_id=tenant_id,
            scopes=frozenset(scopes),
            auth_level=auth_level,
            token_id=str(payload.get("jti", "")),
            roles=frozenset(roles),
            amr=frozenset(amr),
            client_id=str(payload.get("client_id", payload.get("azp", ""))) or None,
            region=str(payload.get(self.settings.oidc_region_claim, "")) or None,
            auth_source="oidc",
        )

    def protected_resource_metadata(self) -> dict[str, Any]:
        resource = self.settings.oauth_resource_identifier.rstrip("/")
        return {
            "resource": resource,
            "authorization_servers": [self.settings.oidc_issuer.rstrip("/")],
            "bearer_methods_supported": ["header"],
            "scopes_supported": sorted(
                {
                    "research:read",
                    "content:generate",
                    "account:read",
                    "account:sync",
                    "publish:draft",
                    "publish:approve",
                    "publish:execute",
                    "mcp:invoke",
                    "a2a:invoke",
                    "enterprise:admin",
                    "audit:read",
                }
            ),
            "resource_documentation": urljoin(resource + "/", "docs"),
        }


_oidc_verifier: OIDCVerifier | None = None
_oidc_lock = threading.Lock()


def get_oidc_verifier() -> OIDCVerifier:
    global _oidc_verifier
    if _oidc_verifier is None:
        with _oidc_lock:
            if _oidc_verifier is None:
                _oidc_verifier = OIDCVerifier()
    return _oidc_verifier
