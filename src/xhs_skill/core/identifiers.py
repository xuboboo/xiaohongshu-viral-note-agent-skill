from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def validate_identifier(value: str, *, field: str = "identifier") -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {field}: use 1-128 letters, digits, '_' or '-'")
    return value


def safe_child(root: str | Path, name: str, *, field: str = "identifier") -> Path:
    root_path = Path(root).expanduser().resolve()
    safe = validate_identifier(name, field=field)
    candidate = (root_path / safe).resolve()
    if candidate.parent != root_path:
        raise ValueError(f"Invalid {field}")
    return candidate


def private_mkdir(path: str | Path) -> Path:
    target = Path(path)
    if target.is_symlink():
        raise PermissionError(f"Private directory must not be a symbolic link: {target}")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink():
        raise PermissionError(f"Private directory must not be a symbolic link: {target}")
    try:
        target.chmod(0o700)
    except OSError:
        pass
    return target


def atomic_write_private(path: str | Path, payload: bytes) -> None:
    target = Path(path)
    private_mkdir(target.parent)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
