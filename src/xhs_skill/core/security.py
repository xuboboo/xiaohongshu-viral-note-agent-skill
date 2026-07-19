from __future__ import annotations

import hashlib
import ipaddress
import socket
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def derive_key(secret: str, context: str = "xhs-skill-session") -> bytes:
    return hashlib.scrypt(
        secret.encode("utf-8"),
        salt=context.encode("utf-8"),
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


def encrypt_bytes(data: bytes, secret: str, associated_data: bytes = b"") -> tuple[bytes, bytes]:
    import os

    nonce = os.urandom(12)
    ciphertext = AESGCM(derive_key(secret)).encrypt(nonce, data, associated_data)
    return nonce, ciphertext


def decrypt_bytes(
    nonce: bytes,
    ciphertext: bytes,
    secret: str,
    associated_data: bytes = b"",
) -> bytes:
    return AESGCM(derive_key(secret)).decrypt(nonce, ciphertext, associated_data)


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.hostname or parsed.hostname.lower() in BLOCKED_HOSTS:
        raise ValueError("Blocked hostname")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Private or reserved network destinations are blocked")
    return url


def content_hash(*parts: str | bytes) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()
