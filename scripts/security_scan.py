from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXTENSIONS = {".py", ".yml", ".yaml", ".toml", ".json", ".md", ".env"}
EXCLUDED = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}

SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9_-]{32,}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
}
PLACEHOLDER_ALLOWLIST = {
    "development-only-secret-key-change-me",
    "replace-with-at-least-32-random-bytes",
}


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        path.is_file()
        and path.suffix in SOURCE_EXTENSIONS
        and not any(part in EXCLUDED for part in relative.parts)
    )


def main() -> None:
    findings: list[dict[str, str]] = []
    for path in ROOT.rglob("*"):
        if not included(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                value = match.group(0)
                if value in PLACEHOLDER_ALLOWLIST:
                    continue
                findings.append(
                    {
                        "type": name,
                        "path": str(path.relative_to(ROOT)),
                        "line": str(text.count("\\n", 0, match.start()) + 1),
                    }
                )
    forbidden_inputs = {
        "authorized_import_path": "client-controlled local import path",
        'Field(description="local path': "client-controlled local file path",
    }
    source = "\\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "src" / "xhs_skill").rglob("*.py")
    )
    for needle, description in forbidden_inputs.items():
        if needle in source:
            findings.append({"type": description, "path": "src/xhs_skill", "line": "?"})
    report = {"passed": not findings, "findings": findings}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
