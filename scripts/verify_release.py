from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify artifact digest, SBOM, provenance and optional Cosign bundle")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--sha256-file", type=Path)
    parser.add_argument("--sbom", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--cosign-bundle", type=Path)
    parser.add_argument("--certificate-identity")
    parser.add_argument("--certificate-oidc-issuer")
    args = parser.parse_args()
    digest = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    if args.sha256_file:
        expected = args.sha256_file.read_text(encoding="utf-8").split()[0]
        if expected != digest:
            raise SystemExit("Artifact SHA-256 mismatch")
    if args.sbom:
        sbom = json.loads(args.sbom.read_text(encoding="utf-8"))
        if sbom.get("bomFormat") != "CycloneDX" or not sbom.get("components"):
            raise SystemExit("Invalid CycloneDX SBOM")
    if args.provenance:
        provenance = json.loads(args.provenance.read_text(encoding="utf-8").splitlines()[0])
        subjects = provenance.get("subject", [])
        if not any(item.get("digest", {}).get("sha256") == digest for item in subjects):
            raise SystemExit("Provenance does not bind the artifact digest")
    if args.cosign_bundle:
        command = [
            "cosign",
            "verify-blob",
            str(args.artifact),
            "--bundle",
            str(args.cosign_bundle),
        ]
        if args.certificate_identity:
            command += ["--certificate-identity", args.certificate_identity]
        if args.certificate_oidc_issuer:
            command += ["--certificate-oidc-issuer", args.certificate_oidc_issuer]
        subprocess.run(command, check=True)
    print(json.dumps({"verified": True, "sha256": digest}, indent=2))


if __name__ == "__main__":
    main()
