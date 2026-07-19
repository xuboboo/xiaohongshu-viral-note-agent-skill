from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def purl(name: str, version: str) -> str:
    normalized = name.lower().replace("_", "-")
    return f"pkg:pypi/{normalized}@{version}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a CycloneDX-compatible SBOM")
    parser.add_argument("--output", type=Path, default=Path("dist/sbom.cdx.json"))
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    components = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda item: item.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        version = distribution.version
        components.append(
            {
                "type": "library",
                "bom-ref": purl(name, version),
                "name": name,
                "version": version,
                "purl": purl(name, version),
                "licenses": [],
            }
        )
    metadata: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tools": {
            "components": [
                {
                    "type": "application",
                    "name": "xiaohongshu-viral-note-agent-skill-sbom-generator",
                    "version": "5.12.0",
                }
            ]
        },
        "component": {
            "type": "application",
            "name": "xiaohongshu-viral-note-agent-skill",
            "version": "5.12.0",
            "purl": "pkg:pypi/xiaohongshu-viral-note-agent-skill@5.12.0",
        },
    }
    if args.artifact and args.artifact.is_file():
        metadata["component"]["hashes"] = [
            {"alg": "SHA-256", "content": hashlib.sha256(args.artifact.read_bytes()).hexdigest()}
        ]
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": f"urn:uuid:{uuid4()}",
        "version": 1,
        "metadata": metadata,
        "components": components,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
