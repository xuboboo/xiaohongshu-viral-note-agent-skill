# Supply-chain security reference

Create a deterministic release archive, SHA-256 digest, CycloneDX SBOM and provenance statement.
Scan source, dependencies, images and secrets in CI. Sign release artifacts and verify signatures
before deployment. Plugin packages are untrusted until their digest, publisher key, signature,
minimum Skill version and declared permissions all pass verification. Never load arbitrary Python
from an uploaded asset merely because its filename appears valid.
