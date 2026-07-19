from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from xhs_skill import __version__
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.security import content_hash
from xhs_skill.enterprise.models import PluginManifest


class PluginVerificationError(ValueError):
    pass


class PluginTrustStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = self.settings.plugin_trust_store.resolve()

    def keys(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in payload.get("keys", {}).items()}

    def public_key(self, key_id: str) -> Ed25519PublicKey:
        encoded = self.keys().get(key_id)
        if not encoded:
            raise PluginVerificationError("Plugin signing key is not trusted")
        try:
            return Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded))
        except Exception as exc:
            raise PluginVerificationError("Trusted plugin key is invalid") from exc


class PluginVerifier:
    def __init__(
        self,
        settings: Settings | None = None,
        trust_store: PluginTrustStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.trust_store = trust_store or PluginTrustStore(self.settings)

    @staticmethod
    def _canonical(manifest: PluginManifest) -> bytes:
        payload = manifest.model_dump(mode="json", exclude={"signature"})
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        parts = value.split("+", 1)[0].split("-", 1)[0].split(".")
        return tuple(int(item) if item.isdigit() else 0 for item in parts)

    def verify(self, manifest: PluginManifest, artifact: Path) -> dict[str, str | bool]:
        if not artifact.is_file() or artifact.is_symlink():
            raise PluginVerificationError("Plugin artifact must be a regular file")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if digest != manifest.sha256:
            raise PluginVerificationError("Plugin artifact digest mismatch")
        if self._version_tuple(__version__) < self._version_tuple(manifest.minimum_skill_version):
            raise PluginVerificationError("Plugin requires a newer Skill version")
        if not manifest.signature:
            if (
                self.settings.app_env in {"development", "test"}
                and self.settings.plugin_allow_unsigned_in_development
            ):
                return {"verified": False, "sha256": digest, "reason": "unsigned-development-plugin"}
            raise PluginVerificationError("Unsigned plugins are not allowed")
        try:
            signature = base64.b64decode(manifest.signature, validate=True)
            self.trust_store.public_key(manifest.public_key_id).verify(
                signature,
                self._canonical(manifest),
            )
        except PluginVerificationError:
            raise
        except Exception as exc:
            raise PluginVerificationError("Plugin signature verification failed") from exc
        return {
            "verified": True,
            "sha256": digest,
            "fingerprint": content_hash(manifest.publisher, manifest.name, manifest.version, digest),
        }
