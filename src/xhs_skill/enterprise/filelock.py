from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def process_file_lock(path: Path) -> Iterator[None]:
    """Best-effort cross-process exclusive lock for local enterprise fallbacks.

    Production multi-node deployments should use PostgreSQL/advisory locks. This lock protects
    local and shared-POSIX-filesystem installations from common multi-worker lost updates.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        except ImportError:
            # Windows fallback: the in-process RLock at the caller still provides protection.
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        except ImportError:
            pass
        os.close(fd)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
