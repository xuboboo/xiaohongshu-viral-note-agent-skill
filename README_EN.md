# Xiaohongshu Viral Note Agent Skill

[English](#what-is-this) | [中文](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-purple.svg)](https://modelcontextprotocol.io/)

---

## What is this

Five years running content operations on Xiaohongshu (China's lifestyle platform, think Instagram meets Pinterest). Multiple accounts across beauty, parenting, home decor, and local business.

The job boils down to a few things on repeat: scanning trends, deconstructing what makes posts go viral, writing copy, stripping the "AI smell," watching the numbers, then doing it all again. Over time it becomes muscle memory — which title hooks work, which narrative frameworks fit product reviews, when to post for max reach, how to recover when account weight drops.

When I started using AI for content production last year, I hit a wall: **AI can write, but it doesn't understand Xiaohongshu.** Generic LLMs produce essays that feel like homework, fabricate data, or trip compliance wires.

So I fused five years of operational methodology with AI engineering into this Skill — **a one-stop solution covering the entire Xiaohongshu workflow: trend research, content generation, compliance verification, account analysis, QR login, one-click publishing, and post-publish analytics.**

> **The goal isn't to let AI replace your content creation. It's to "teach" AI your operational playbook — so it handles research, generation, and verification your way, while you focus on review and publishing.**

49 MCP tools covering the full loop from topic selection to retrospective. Plug in Cursor, Claude, or any AI agent and you're ready to go.

**Our vision is simple: make Xiaohongshu content creation accessible to everyone. Lower the barrier to entry so anyone can write notes that go viral.** You don't need five years of operational experience. You don't need to understand AI engineering. Just install and go.

---

## What problems does it solve

| Your problem | How it helps |
|---|---|
| Picking topics by gut feel, scrolling for hours without direction | Scrapes public trend data, analyzes heat bands, rising keywords, and content gaps — gives you clickable topic suggestions |
| Writing one post takes 2 hours, removing AI smell takes another | One-click generation of complete graphic/video packages: title, cover copy, body, hashtags, CTA — with built-in de-AI rewriting |
| Not sure if your content will pass compliance checks | Three automatic verification gates: claims + originality + compliance — any failure = auto-block |
| No idea how your account is actually performing | Import authorized analytics, estimate account weight and content health, get recommendations by weak area |
| Publishing workflow is tedious | Authorized QR login → draft preview → explicit approval → auto-publish, fully controlled |
| No feedback loop after publishing | Auto-syncs post-publish metrics: attribution, A/B experiments, retrospective suggestions |

---

## 30-second start

```bash
# Install
pip install -e '.[dev]'

# One-click: from trend to finished note
xhs-skill generate --topic "commute sunscreen" --search-provider fixture --output output/package.json

# Or plug into your AI agent via MCP
python -m xhs_skill.mcp.server --transport stdio
```

---

## Core capabilities

### Research & Topics
- Scrapes public hot notes, auto-deduplicates, ranks, classifies trends
- Returns clickable `topic_suggestions` — each with `generate_payload` for one-hop generation
- `hot_insights`: heat bands, rising keywords, early velocity signals, content gaps, title mechanism stats

### Content Generation
- Multi-candidate titles/covers/bodies ranked by relevance + diversity
- Graphic pages / video storyboards (15/30/45/60s voiceover templates)
- Narrative frameworks: PAS / AIDA / BAB / QUEST / 4P / SCQA
- Note styles: review, seeding, pitfall-avoidance, checklist, tutorial, store-visit, comparison, decision

### Verification Gates
- **Claim Ledger**: auto-extracts objective claims; unverifiable ones must be deleted or converted to subjective
- **Originality**: literal + semantic + rare-phrase + image pHash multi-dimensional checks
- **Compliance**: extreme claims, fabricated experiences, medical/financial promises, commercial disclosure
- **AI Provenance**: records and labels AI-generated or modified content

### Account Analysis
- Account weight estimation (explicitly labeled as non-official)
- Content health: engagement, saves, rhythm, search visibility, risk — multi-dimensional
- Auto-recommends `note_style` and topic angles based on weak areas

### Publishing & Operations
- Authorized QR login with AES-256-GCM encrypted sessions
- Draft → Preview → Explicit approval → Publish — interceptable at every step
- Auto-syncs post-publish metrics: attribution, weight trends, content calendars, series planning, A/B/n experiments, LinUCB contextual bandits

---

## Tools at a glance (49 MCP tools)

| Group | Tools | What they do |
|---|---|---|
| **Research** | `search_hot_notes` `search_trending_topics` `analyze_hot_notes` `suggest_topics_by_health` | Trend research & topic suggestions |
| **Generate** | `generate_xhs_note` `generate_from_hot` `rewrite_xhs_note` `diagnose_xhs_note` `plan_content_outline` `draft_comment_reply` `generate_xhs_note_variants` | Content generation, rewriting, diagnosis |
| **Verify** | `verify_claims` `check_originality` `check_compliance` | Claims, originality, compliance checks |
| **Account** | `query_account_weight` `query_content_health` `diagnose_account` `sync_account_analytics` `start_account_login` `check_account_login` `logout_account` | Account analysis & authorized login |
| **Publish** | `create_publish_draft` `preview_publish_draft` `approve_publish_draft` `publish_note` `schedule_note` `get_publish_windows` | Draft, preview, approve, publish, schedule |
| **Operations** | `sync_published_metrics` `get_performance_attribution` `get_account_weight_trend` `create_content_calendar` `create_content_series` `create_abn_experiment` `choose_content_bandit` `generate_retrospective` `analyze_performance` | Metrics, attribution, calendar, experiments |
| **Enterprise** | `get_enterprise_controls` `get_enterprise_budget` `create_enterprise_approval` `decide_enterprise_approval` `verify_enterprise_audit` `enterprise_dlp_scan` | Tenant policy, budget, approvals, audit |

Full contract: `contracts/mcp-tools.json`

---

## Supported models

| Provider | Adapter |
|---|---|
| OpenAI / GPT | Responses API |
| Anthropic / Claude | Messages API |
| Google / Gemini | Generate Content API |
| DeepSeek, Qwen, Ark, GLM, Kimi, MiniMax, Hunyuan, Qianfan | OpenAI-Compatible |
| Amazon Bedrock | Converse API |
| Azure OpenAI | OpenAI-Compatible |
| Self-hosted (vLLM etc.) | OpenAI-Compatible |

Model identifiers are configuration, not hard-coded. See `assets/providers.yaml`.

---

## Search providers

| Provider | Description |
|---|---|
| `client_web` | Host agent passes `web_results` (no API key needed) |
| `brave` | Brave Search API |
| `bing` | Bing Web Search |
| `google_cse` | Google Custom Search |
| `searxng` | Self-hosted SearxNG |
| `openai_web` | OpenAI Web Search |
| `fixture` | Deterministic offline dev data |

When no key is configured, automatically returns `needs_web_search` so the host agent can use its own search.

---

## Quick start

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# 2. Configure
cp .env.example .env
# Edit .env with your API keys

# 3. Browser publishing requires
playwright install chromium

# 4. Run
xhs-skill serve --host 127.0.0.1 --port 8080   # HTTP API
python -m xhs_skill.mcp.server --transport stdio  # MCP
```

### CLI examples

```bash
# Search hot notes
xhs-skill search-hot --query "commute sunscreen" --provider fixture

# One-click generate
xhs-skill generate --topic "commute sunscreen" --search-provider fixture

# Account analysis
xhs-skill account weight --account demo --input examples/account_analytics.json

# Publishing flow
xhs-skill publish draft --account demo --package output/package.json
xhs-skill publish preview --draft <draft-id>
xhs-skill publish approve --draft <draft-id>
xhs-skill publish execute --draft <draft-id> --approval-token <token>
```

---

## MCP integration

### Cursor / Claude Desktop

```json
{
  "mcpServers": {
    "xhs-skill": {
      "command": "python",
      "args": ["-m", "xhs_skill.mcp.server", "--transport", "stdio"]
    }
  }
}
```

### HTTP endpoint

```bash
POST /mcp
```

### A2A

```bash
GET /.well-known/agent-card.json
```

---

## Safety boundaries

This Skill will **never**:
- Bypass captchas, risk controls, or access controls
- Automate fake engagement or spam
- Plagiarize or replicate others' content
- Hide commercial relationships
- Disguise estimates as official data

Three verification gates must pass before publish: claim verification + originality check + compliance check. Any failure = automatic block.

---

## Enterprise

Supports OIDC/SCIM identity management, tenant isolation, multi-party approvals, DLP, audit hash chains, and Vault/KMS key management.

```bash
pip install -e '.[enterprise]'
```

---

## License

[MIT](LICENSE)

---

<p align="center">
  <strong>Let AI handle research and writing. You just review and publish.</strong><br>
  <sub>Xiaohongshu Viral Note Agent Skill &mdash; from trends to publishing, one package.</sub>
</p>