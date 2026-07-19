---
name: xiaohongshu-viral-note-agent-skill
description: >
  Use for Xiaohongshu/RED hot notes, trends, note generation/rewrite, authorized
  account weight, login, publish, schedule, and post-publish review. Not for
  unauthorized access, captcha bypass, restricted scraping, fake engagement, or plagiarism.
  用于小红书热门笔记、趋势、种草文案、账号权重、扫码登录、发布与内容复盘。
  禁止未授权访问、绕过验证、刷量、洗稿。
license: MIT
compatibility: >
  Python 3.12+, optional PostgreSQL/Redis/Vault/AWS KMS, OIDC and SCIM for enterprise identity,
  optional web-search providers, Playwright for authorized browser workflows, MCP stdio or
  Streamable HTTP, A2A and an SSE-enabled high-concurrency runtime.
keywords:
  - 小红书
  - 小红书热门笔记
  - 小红书趋势
  - 爆款笔记
  - 种草文案
  - 小红书标题
  - 封面文案
  - 图文分页
  - 口播脚本
  - 探店笔记
  - 测评笔记
  - 去AI味
  - 账号权重
  - 扫码登录
  - 自动发布
  - 定时发布
  - 内容复盘
  - 小红书SEO
  - Xiaohongshu
  - RED notes
  - viral note
  - content seeding
  - account weight
  - authorized publish
  - PUBLIC_INDEX_TREND
  - ESTIMATED_ACCOUNT_WEIGHT
  - MCP skill
  - Cursor agent skill
metadata:
  display_name: "小红书爆款笔记生成 agent Skill"
  version: "5.14.5"
  language: "zh-CN"
  category: "content-intelligence"
  optimization: "SEO+GEO"
---

# 小红书爆款笔记生成 agent Skill

> **这是什么**：一套自包含的 Cursor / agent skill，面向小红书（Xiaohongshu / RED）内容研究、原创生成、合规校验、授权账号分析，以及受控登录/发布和发后运营。

能力边界以本包内的 Python 模块、`scripts/` 和 `references/` 为准。

- 不默认提供站内官方全量热榜
- 不假设存在包外未写明的自动化能力

## 黄金路径（先做对这件事）

> **黄金路径是什么**：Agent 与人共用的最短闭环；先看 `ux.summary` / `next_step`，再下钻业务字段。

```text
研究/选题 → 生成交付包 → 人工审阅 →（可选）授权草稿与发布
```

| 你想… | 优先调用 | 成功后看什么 |
|---|---|---|
| 找热门与选题 | `search_hot_notes` 或 `generate_from_hot(dry_run=true)` | `topic_suggestions`、`hot_insights`、`ux.next_step` |
| 一键成稿 | `generate_from_hot(dry_run=false)` 或 `generate_xhs_note` | `creation_bundle`、`quality_report.readiness`、`ux.status` |
| 改写润色 | `rewrite_xhs_note` | `title_hook`、`structure_checks`、`ux` |
| 无搜索密钥 | 任意研究工具 | `status=needs_web_search` → 宿主 websearch → 带 `web_results` 重调 |
| 环境是否就绪 | CLI `xhs-skill doctor` | `ready`、`checks[].hint`、`golden_path` |

**读返回值的顺序（Agent / 人通用）：**

1. `status` 或 `ux.status`（`ok` / `needs_web_search` / `needs_human_review` / `blocked` / `suggestions_ready` / `generated`）
2. `ux.summary`（一句话发生了什么）
3. `ux.next_step` 或顶层 `next_step`（下一步调哪个工具）
4. 再读业务体：`topic_suggestions`、`creation_bundle`、`package` 等

**工具怎么找：** `tools/list` 里每个工具描述带场景前缀（如 `[研究/选题]`），`_meta.groups` 给分组索引；分组顺序：`research → generate → verify → publish → operations`。

**不要做：** 在 `blocked` / 未人工确认时直接 `publish_note`；不要把 `PUBLIC_INDEX_TREND` 说成站内热榜。

## 核心约定（Core contract）

> **核心约定是什么**：先分清数据从哪来，输出里必须标明类型；客观说法进台账，缺证不编造。

三类数据标签（首次定义，全文沿用）：

1. **`PUBLIC_INDEX_TREND`（公开索引趋势）**：网上搜到的公开内容线索，**不是**小红书 App 内官方热榜。
2. **`AUTHORIZED`（授权数据）**：账号主人明确导入或授权暴露的数据。
3. **`ESTIMATED_ACCOUNT_WEIGHT`（估算账号权重）**：系统按规则估出的账号权重，**不是**小红书官方分数。

硬规则：

- 不能编造缺失的互动数据、个人经历、产品事实、用户评价、平台规则、价格、排名、奖项、医疗功效或商业关系。
- 客观说法必须进入 **Claim Ledger（声明台账：待核验客观说法清单）**。
- 核验不过时，只能：`DELETE` / `QUALIFY` / `CONVERT_TO_SUBJECTIVE` / `HUMAN_REVIEW`。
- 不能让模型“挑一个听起来最像真的”。

## 工作流（Workflow）

> **工作流是什么**：从任务路由到研究、生成、校验、交付、授权账号与发布的固定顺序；细节见 references。

1. **先路由任务**：研究、生成、改写、诊断、账号分析、鉴权或发布 → `references/task-routing.md`。
2. **再抽 Brief**：目标、受众、账号身份、内容形态、商业属性、证据与约束。次要字段可给合理默认并写明假设；**不能**臆造事实或经历。
3. **要“当前/热门/趋势”时，做自适应检索** → `references/research-protocol.md`：
   - 宿主已给 `web_results`（`client_web`）→ 优先用；
   - 否则用已配置的在线搜索 Provider；
   - 再否则返回 `needs_web_search`：宿主按 `suggested_queries` 检索后，带上 `web_results`（`[{url, title, snippet?}, ...]`）重调同一工具。
4. **归一化、去重、排序**笔记；保留公开索引覆盖警告。
5. **只蒸馏机制**（人群/场景/结构/痛点等）；不能复用原文独特表达、个人故事或图片。
6. **多候选生成**标题/封面/正文（图文分页或视频分镜与正文对齐），再按相关性和多样性排序；正文可落话题标签。
7. **抽取声明**，再跑原创性、合规、AI 风格/来源校验 → `references/verification-workflow.md`。
8. **输出结构化 `DeliveryPackage`（最终交付包）**；发布前必须人工审阅。
9. **账号权重**：只能用 `AUTHORIZED` 分析数据，并标明 `ESTIMATED_ACCOUNT_WEIGHT`。
10. **登录**：必须用户扫码确认；会话状态加密存储。
11. **发布**：默认 `REQUIRE_CONFIRMATION`；校验审批 token 和内容 hash。**创建草稿 / 审批 / 发布前必须服务端重跑 claims、合规与原创门禁**，不得信任客户端自报的 `compliance_report` / `originality_report` / `claims.verified`。
12. **立刻停止的条件**：验证码、风险验证、账号不一致、不支持的 UI、合规/原创失败、内容 hash 变更、缺少 AI 披露决策、服务端重验 `BLOCKED`。
13. **突发或长任务**：有界异步任务 + SSE；遵守租户/Provider 限流，不能绕过背压。
14. **发布成功后**：排队做授权侧发布后指标同步（归因、权重趋势、实验、复盘、下一条建议）；复盘 `next_note_suggestions` 可直接喂 `generate_xhs_note`。
15. **多 Pod**：用 PostgreSQL 管发布状态、租约、Outbox 和库级幂等；**不能**依赖单 Pod 本地草稿/审批/调度文件。

创作者常用能力补充：

- **热门一键生成**：`generate_from_hot`（`dry_run` 先选题 / 再一键成稿，复用同一研究报吿）。
- **健康度驱动选题**：`suggest_topics_by_health`；`generate_from_hot` 可开 `use_account_health` 按弱项重排选题并推荐 `note_style`（估算，非官方推荐）。
- **热门洞察**：`search_hot_notes` 等返回 `hot_insights`（分位热度带、上升词/双轴、早期速度信号、话题生命周期、内容缺口、标题机制统计），公开索引非站内热榜。
- **可点选选题**：`topic_suggestions[]`（含 `generate_payload` / `note_style`）。
- **创作一览包**：`generate` 附带 `creation_bundle.v1`；`strategy` 含 `preferred_mechanisms` / `title_proxy_board` / `seo_tag_balance`。
- **改写标题钩子**：`rewrite_xhs_note` 返回 `title_hook`（mechanism/risk_flags）与实体/数字保留检查。
- **Brief + 就绪分**：`content_brief` 与 `quality_report.readiness`。
- **叙事框架 / 笔记类型**：`note_style` + `narrative_framework`；`plan_content_outline`。
- **封面联动 / 口播时长 / 清单分页**：见 `note_style`、`video_duration_seconds`、checklist 分页。
- **账号**：`query_account_weight` + `query_content_health` + `diagnose_account`（evidence、区间、异常检测、冷启动先验、`generate_payload`；非官方分）。
- **多变体 / 复盘一跳 / 发帖窗口 / 评论草稿**：variants、retrospective payload、`get_publish_windows`、`draft_comment_reply`。

## 自包含执行（Self-contained execution）

> **自包含执行是什么**：本包装了研究 Provider、模型适配、高并发运行时、SSE、MCP、A2A、账号分析、浏览器登录与发布；核心能力不依赖单独的 Runtime/Platform 仓库。

详见 `references/self-contained-runtime.md`。

**能力怎么选（按优先级）：**

1. **没有在线搜索密钥时，优先宿主原生 websearch**
   - 调 `search_hot_notes` / `generate_xhs_note`（及同类研究工具）时，可以不传 `providers`。
   - 若返回 `status=needs_web_search`：宿主用 `suggested_queries` 检索，再以 `web_results` 重调同一工具。
   - Skill 负责归一化、去重、排序和机制蒸馏；默认不会静默用 fixture 假数据。
2. **已配置在线搜索**（Brave / Bing / Google CSE / SearxNG / OpenAI web 等）时，Skill 自己搜，不用宿主代搜。
3. **`providers: ["fixture"]`** 只给离线/开发用确定性数据。
4. **端到端研究→交付**：`scripts/generate_note.py`。
5. **检索/分析辅助脚本**（按需）：`scripts/search_hot_notes.py`、`scripts/search_trending_topics.py`、`scripts/analyze_hot_notes.py`、`scripts/diagnose_note.py`。
6. **账号与发布**：`scripts/query_account_weight.py`、`scripts/login_account.py`、`scripts/publish_note.py`；授权数据同步可用 `scripts/sync_account_analytics.py`。
7. **高并发**：`scripts/serve_runtime.py` 或 `scripts/run_worker.py`；调度/Outbox/指标同步见 `scripts/run_scheduler.py`、`scripts/run_outbox.py`、`scripts/run_metrics_sync.py`。
8. **MCP 宿主接入**：`scripts/run_mcp.py`。

模型与 Provider：`references/model-routing.md`、`assets/providers.yaml`；探测用 `scripts/provider_probe.py`。

## 工具与 references 按需加载（Tool and reference loading）

> **按需加载是什么**：只加载当前请求相关的 reference；能跑脚本/模块时，不用长文复述其逻辑。

| 场景 | 加载 |
|---|---|
| 研究与热门排序 | `references/research-protocol.md`、`references/hot-ranking.md` |
| 任务路由 | `references/task-routing.md` |
| 内容生成 | `references/content-generation.md` |
| 验证闭环 | `references/verification-workflow.md` |
| 模型路由 | `references/model-routing.md` |
| 账号估算 | `references/account-weight.md` |
| 登录与发布 | `references/browser-authentication.md`、`references/auto-publishing.md` |
| 安全合规 | `references/compliance-rules.md`、`references/ai-labeling.md` |
| 协议集成 | `references/mcp-a2a-streaming.md` |
| 高并发与批量 | `references/high-concurrency.md` |
| 分布式发布与恢复 | `references/distributed-consistency.md` |
| 语义/视觉/学习排序 | `references/content-intelligence-v5.1.md` |
| 发布后运营 | `references/operations-loop.md` |
| 企业身份与治理 | `references/enterprise-identity.md`、`references/enterprise-governance.md`、`references/supply-chain-security.md` |

**MCP 工具名**（契约以 `contracts/mcp-tools.json` 为准；分组索引见 `contracts/mcp-tool-groups.json`）示例：

- 研究/生成：`search_hot_notes`、`search_trending_topics`、`analyze_hot_notes`、`generate_xhs_note`、`rewrite_xhs_note`、`diagnose_xhs_note`
- 校验：`verify_claims`、`check_originality`、`check_compliance`
- 账号：`query_account_weight`、`sync_account_analytics`、`start_account_login` / `check_account_login` / `logout_account`
- 发布：`create_publish_draft` / `preview_publish_draft` / `approve_publish_draft`、`publish_note` / `schedule_note`
- 以及：发布后运营与实验类工具（指标同步、归因、日历/系列、A/B/n、bandit、素材库、复盘等）、企业管控与审批类工具

## 企业执行约定（Enterprise execution contract）

> **企业约定是什么**：企业模式打开后的身份、授权、成本、审批与审计硬规则。

1. 身份只能来自已校验的本地或 OIDC token；**不信任**未认证的租户/角色请求头。
2. 调工具前，先过租户状态、scope、角色、区域、Provider/账号白名单和 DLP。
3. 贵的调用先预留估算成本，结束后结算或释放。
4. 高风险发布要抗钓鱼 MFA 证据，以及 quorum（多人一起点头才算过）审批。
5. 职责分离：申请人不能审批自己的发布。
6. 审批绑定租户、资源、内容 hash 和过期时间；任一变更就让审批失效。
7. 管理、身份、审批、插件和发布结果写入审计链。
8. 生产长生命周期密钥优先 Vault Transit 或 AWS KMS（已配置时）。
9. 只接受摘要和发布者公钥都受信的已签名插件。
10. 遵守数据驻留与留存策略；租户或 SCIM 用户停用就停止处理。

细节：`references/enterprise-identity.md`、`references/enterprise-governance.md`、`references/supply-chain-security.md`。

## 强制输出规则（Mandatory output rules）

> **强制输出规则是什么**：交付与操作时必须遵守的可见性、校验状态与授权要求。

- 假设和未知项要写清楚。
- 用了公开检索时，必须带**研究覆盖警告**（`PUBLIC_INDEX_TREND` ≠ 站内全量热榜）。
- 交付包要含声明、原创性、合规和 AI 来源/标识相关报告（与 `DeliveryPackage` 约定一致）。
- 任一关键校验失败时，**不能**标成可直接发布（应为 `BLOCKED` 或 `HUMAN_REVIEW_REQUIRED` 等）。
- 没有用户明确授权，不能执行登录、退出、发布或定时发布。
- 不能绕过平台安全机制，不能自动化刷量/虚假互动。

## 明确不做（边界）

> **边界是什么**：本 skill 明确拒绝的高风险与违规用途。

- 破解验证码，绕过登录/风控/访问控制。
- 未授权访问账号，或抓取受限内容。
- 洗稿，或近义词复刻第三方独特表达/图片/隐私。
- 隐瞒商业合作关系；删除或篡改应有的 AI 生成内容披露。
- 把 `ESTIMATED_ACCOUNT_WEIGHT` 或公开索引热度伪装成官方分数/站内热榜。