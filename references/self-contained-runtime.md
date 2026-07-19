# Self-contained runtime

This Skill is distributed as one package. `SKILL.md` is the Agent entry point, while bundled
Python modules and scripts implement the capabilities rather than requiring a separate runtime
repository.

## Bundled capability map

| Capability | Bundled implementation |
|---|---|
| Current public web research | `xhs_skill.search`, `xhs_skill.research` |
| Multi-model generation | `xhs_skill.providers` |
| High concurrency | `xhs_skill.core.concurrency`, `xhs_skill.jobs`, Redis Streams |
| SSE and replay | `xhs_skill.streaming` |
| Account estimate | `xhs_skill.accounts` |
| QR login | `xhs_skill.browser` |
| Controlled publishing | `xhs_skill.publishing` |
| MCP | `xhs_skill.mcp` |
| A2A | `xhs_skill.a2a` |
| HTTP API | `xhs_skill.api` |

## Execution modes

1. **Host-tool mode:** use the host Agent's native web-search or browser tools when available.
2. **Standalone script mode:** run scripts from `scripts/` using configured API credentials.
3. **Embedded server mode:** run `scripts/serve_runtime.py`; the Skill exposes HTTP, SSE, MCP and
   A2A from the same package.
4. **Distributed mode:** configure Redis and run API/worker replicas from the same Skill image.

## Security boundary

Packaging everything together does not remove approval boundaries. Login still requires QR
confirmation. Publication defaults to `REQUIRE_CONFIRMATION`. Captcha, risk verification,
account mismatch, content-hash mismatch, unsupported UI, originality failure or compliance
failure stop publication.
