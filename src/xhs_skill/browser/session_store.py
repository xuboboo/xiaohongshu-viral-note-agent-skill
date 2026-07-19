from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import atomic_write_private, private_mkdir, validate_identifier
from xhs_skill.core.security import decrypt_bytes, encrypt_bytes


class EncryptedSessionStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = private_mkdir(self.settings.xhs_session_dir)

    def _path(self, storage_key: str) -> Path:
        validate_identifier(storage_key, field="session_key")
        return self.root / f"{storage_key}.session.enc"

    def save(self, storage_key: str, storage_state: dict[str, Any]) -> Path:
        raw = json.dumps(storage_state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        aad = storage_key.encode("utf-8")
        nonce, ciphertext = encrypt_bytes(raw, self.settings.app_secret_key, aad)
        path = self._path(storage_key)
        atomic_write_private(path, nonce + ciphertext)
        return path

    def load(self, storage_key: str) -> dict[str, Any] | None:
        path = self._path(storage_key)
        if path.is_symlink():
            raise PermissionError("Session file must not be a symbolic link")
        if not path.exists():
            return None
        raw = path.read_bytes()
        if len(raw) < 13:
            raise ValueError("Corrupt session file")
        plaintext = decrypt_bytes(
            raw[:12], raw[12:], self.settings.app_secret_key, storage_key.encode("utf-8")
        )
        return cast(dict[str, Any], json.loads(plaintext))

    def delete(self, storage_key: str) -> bool:
        path = self._path(storage_key)
        if path.exists():
            path.unlink()
            return True
        return False
