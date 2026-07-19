from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    total = 0
    failures: list[str] = []
    for category, expected_count in manifest["counts"].items():
        path = root / "cases" / f"{category}.jsonl"
        if not path.exists():
            failures.append(f"missing {path}")
            continue
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) != expected_count:
            failures.append(f"{category}: expected {expected_count}, got {len(lines)}")
        for number, line in enumerate(lines, start=1):
            case = json.loads(line)
            for field in ("id", "category", "input", "expected"):
                if field not in case:
                    failures.append(f"{category}:{number} missing {field}")
        total += len(lines)
    if total != manifest["total"]:
        failures.append(f"total: expected {manifest['total']}, got {total}")
    if manifest["total"] < 1750:
        failures.append("evaluation corpus must contain at least 1750 cases")
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"status": "passed", "total": total}, ensure_ascii=False))


if __name__ == "__main__":
    main()
