from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Protocol

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.security import derive_key, validate_public_url


@dataclass(frozen=True, slots=True)
class SecretEnvelope:
    backend: str
    ciphertext: str
    encrypted_data_key: str | None = None
    nonce: str | None = None
    key_id: str | None = None
    version: int = 1

    def serialize(self) -> str:
        return json.dumps(self.__dict__, separators=(",", ":"), sort_keys=True)

    @classmethod
    def parse(cls, value: str) -> SecretEnvelope:
        return cls(**json.loads(value))


class SecretBackend(Protocol):
    name: str

    def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> SecretEnvelope: ...

    def decrypt(self, envelope: SecretEnvelope, *, context: dict[str, str]) -> bytes: ...


class LocalAesGcmBackend:
    name = "local"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.key = derive_key(self.settings.app_secret_key, "xhs-enterprise-envelope-v1")

    @staticmethod
    def _aad(context: dict[str, str]) -> bytes:
        return json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> SecretEnvelope:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext, self._aad(context))
        return SecretEnvelope(
            backend=self.name,
            ciphertext=base64.b64encode(ciphertext).decode("ascii"),
            nonce=base64.b64encode(nonce).decode("ascii"),
            key_id="local:v1",
        )

    def decrypt(self, envelope: SecretEnvelope, *, context: dict[str, str]) -> bytes:
        if envelope.backend != self.name or not envelope.nonce:
            raise ValueError("Envelope is not compatible with the local backend")
        return AESGCM(self.key).decrypt(
            base64.b64decode(envelope.nonce),
            base64.b64decode(envelope.ciphertext),
            self._aad(context),
        )


class VaultTransitBackend:
    name = "vault"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.vault_addr or not self.settings.vault_token:
            raise ValueError("Vault Transit is not configured")
        self.base = validate_public_url(self.settings.vault_addr.rstrip("/"))

    def _url(self, action: str) -> str:
        mount = self.settings.vault_transit_mount.strip("/")
        key = self.settings.vault_transit_key
        return f"{self.base}/v1/{mount}/{action}/{key}"

    def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> SecretEnvelope:
        payload = {
            "plaintext": base64.b64encode(plaintext).decode("ascii"),
            "context": base64.b64encode(
                json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).decode("ascii"),
        }
        response = httpx.post(
            self._url("encrypt"),
            json=payload,
            headers={"X-Vault-Token": str(self.settings.vault_token)},
            timeout=10.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        ciphertext = str(response.json()["data"]["ciphertext"])
        return SecretEnvelope(
            backend=self.name,
            ciphertext=ciphertext,
            key_id=f"vault:{self.settings.vault_transit_mount}/{self.settings.vault_transit_key}",
        )

    def decrypt(self, envelope: SecretEnvelope, *, context: dict[str, str]) -> bytes:
        if envelope.backend != self.name:
            raise ValueError("Envelope is not compatible with Vault")
        payload = {
            "ciphertext": envelope.ciphertext,
            "context": base64.b64encode(
                json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).decode("ascii"),
        }
        response = httpx.post(
            self._url("decrypt"),
            json=payload,
            headers={"X-Vault-Token": str(self.settings.vault_token)},
            timeout=10.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        return base64.b64decode(response.json()["data"]["plaintext"])


class AwsKmsEnvelopeBackend:
    name = "aws_kms"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.aws_kms_key_id:
            raise ValueError("AWS KMS is not configured")
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("Install the aws optional dependency for AWS KMS") from exc
        self.client = boto3.client("kms", region_name=self.settings.aws_region)

    @staticmethod
    def _context(context: dict[str, str]) -> dict[str, str]:
        return {str(key): str(value) for key, value in context.items()}

    def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> SecretEnvelope:
        result = self.client.generate_data_key(
            KeyId=self.settings.aws_kms_key_id,
            KeySpec="AES_256",
            EncryptionContext=self._context(context),
        )
        data_key = bytearray(result["Plaintext"])
        try:
            nonce = os.urandom(12)
            ciphertext = AESGCM(bytes(data_key)).encrypt(
                nonce,
                plaintext,
                json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            )
        finally:
            for index in range(len(data_key)):
                data_key[index] = 0
        return SecretEnvelope(
            backend=self.name,
            ciphertext=base64.b64encode(ciphertext).decode("ascii"),
            encrypted_data_key=base64.b64encode(result["CiphertextBlob"]).decode("ascii"),
            nonce=base64.b64encode(nonce).decode("ascii"),
            key_id=self.settings.aws_kms_key_id,
        )

    def decrypt(self, envelope: SecretEnvelope, *, context: dict[str, str]) -> bytes:
        if envelope.backend != self.name or not envelope.encrypted_data_key or not envelope.nonce:
            raise ValueError("Envelope is not compatible with AWS KMS")
        result = self.client.decrypt(
            CiphertextBlob=base64.b64decode(envelope.encrypted_data_key),
            KeyId=self.settings.aws_kms_key_id,
            EncryptionContext=self._context(context),
        )
        data_key = bytearray(result["Plaintext"])
        try:
            return AESGCM(bytes(data_key)).decrypt(
                base64.b64decode(envelope.nonce),
                base64.b64decode(envelope.ciphertext),
                json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            )
        finally:
            for index in range(len(data_key)):
                data_key[index] = 0


def get_secret_backend(settings: Settings | None = None) -> SecretBackend:
    settings = settings or get_settings()
    if settings.secret_backend == "vault":
        return VaultTransitBackend(settings)
    if settings.secret_backend == "aws_kms":
        return AwsKmsEnvelopeBackend(settings)
    return LocalAesGcmBackend(settings)
