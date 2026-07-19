from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JSONStore:
    """Atomic local JSON storage used by the MVP repositories."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, key: str, value: dict[str, Any]) -> Path:
        target = self.root / f"{key}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        return target

    def read(self, key: str) -> dict[str, Any] | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Stored JSON value is not an object")
        return value
