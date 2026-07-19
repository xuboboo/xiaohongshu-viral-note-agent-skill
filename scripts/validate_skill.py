from __future__ import annotations

import re
from pathlib import Path


def main() -> None:
    skill = Path("SKILL.md")
    text = skill.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SystemExit("SKILL.md must start with YAML frontmatter")
    if "name: xiaohongshu-viral-note-agent-skill" not in text:
        raise SystemExit("Invalid skill name")
    if not re.search(r"description:\s*>?", text):
        raise SystemExit("Missing description")
    print("SKILL.md is valid")


if __name__ == "__main__":
    main()
