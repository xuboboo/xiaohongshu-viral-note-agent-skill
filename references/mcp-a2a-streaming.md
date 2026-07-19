# MCP, A2A and streaming

Use SSE for task progress and token/result events. Use MCP for tools/data and A2A for independent
agents. High-impact MCP tools such as publishing require explicit approval. Event IDs are
monotonic and replayable; clients must de-duplicate by event ID.

## Tool UX envelope

Every MCP `tools/call` result (and A2A skill execution via the same service) includes a
`tool_ux.v1` block when applicable:

1. Read `ux.status` (or top-level `status` for `needs_web_search`).
2. Read `ux.summary` and `ux.next_step` (also promoted to top-level `next_step` when missing).
3. Then consume business fields (`topic_suggestions`, `creation_bundle`, drafts, etc.).

`tools/list` descriptions are prefixed by scene (`[研究/选题]`, `[生成/改写]`, …). The list result
may include `_meta` with `tool_groups.v1` (`contracts/mcp-tool-groups.json` after export).

## Search quality in A2A

`/.well-known/agent-card.json` exposes `capabilities.search_quality` with:
- `features`: list of adaptive search capabilities (memory, guards, provider priority, …)
- `ux_fields`: fields to read in tool results for quality assessment
- `memory`: where per-query quality is persisted

`DeliveryPackage.quality_report.search_quality` contains:
- `score` (0–100), `label` (good/fair/poor/empty)
- `delta.score_delta` vs last same-query search
- `guards.strength` (none/soft/hard)
- `confidence_note`: human-readable confidence summary
- `recommendations`: actionable improvement hints
