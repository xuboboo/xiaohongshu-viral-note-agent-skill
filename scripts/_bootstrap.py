from __future__ import annotations

import sys
from pathlib import Path


def bootstrap() -> Path:
    """Make the bundled src-layout package importable without installation."""

    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return root
