from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "dist",
    ".venv",
    "xiaohongshu_viral_note_agent_skill.egg-info",
}

# 内部开发文档、版本演进、安全审计、部署配置等不进入发布包
EXCLUDED_TOP_LEVEL = {
    "docs",
    "loadtests",
    "deploy",
    "private-docs",
}

EXCLUDED_FILES = {
    "CHANGELOG.md",
    "ARTIFACT_MANIFEST.json",
}

EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".coverage"}


def should_include(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES or path.name == ".coverage":
        return False
    if relative == Path(".env"):
        return False
    if relative.parts[:2] == ("playwright", ".auth") and path.name != ".gitkeep":
        return False
    if relative.parts and relative.parts[0] in EXCLUDED_TOP_LEVEL:
        return False
    if relative.name in EXCLUDED_FILES:
        return False
    return not (
        relative.parts and relative.parts[0] in {"data", "output"} and path.name != ".gitkeep"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "xiaohongshu-viral-note-agent-skill-v5.12.0.zip",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and should_include(path, root):
                archive.write(
                    path, Path("xiaohongshu-viral-note-agent-skill") / path.relative_to(root)
                )
    print(args.output)


if __name__ == "__main__":
    main()
