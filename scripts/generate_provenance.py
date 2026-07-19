from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SLSA provenance for a release artifact")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/provenance.intoto.jsonl"))
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": artifact.name, "digest": {"sha256": digest}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://github.com/slsa-framework/slsa-github-generator/generic@v2",
                "externalParameters": {
                    "repository": os.getenv("GITHUB_REPOSITORY", "local/xhs-skill"),
                    "ref": os.getenv("GITHUB_REF", "local"),
                    "workflow": os.getenv("GITHUB_WORKFLOW_REF", "local-build"),
                },
                "internalParameters": {},
                "resolvedDependencies": [
                    {
                        "uri": os.getenv("GITHUB_SERVER_URL", "https://github.com")
                        + "/"
                        + os.getenv("GITHUB_REPOSITORY", "local/xhs-skill"),
                        "digest": {"gitCommit": os.getenv("GITHUB_SHA", "unknown")},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": os.getenv("RUNNER_NAME", "local-builder")},
                "metadata": {
                    "invocationId": os.getenv("GITHUB_RUN_ID", "local"),
                    "startedOn": datetime.now(UTC).isoformat(),
                    "finishedOn": datetime.now(UTC).isoformat(),
                },
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(statement, separators=(",", ":")) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
