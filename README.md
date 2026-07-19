# 小红书爆款笔记生成 Agent Skill

**Xiaohongshu Viral Note Agent Skill**

[中文](#这是什么) | [English](README_EN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-purple.svg)](https://modelcontextprotocol.io/)

---

## 这是什么

做了五年小红书内容运营，操盘过数码、软件、教育、美妆、母婴、家居、本地生活多个赛道的账号。

五年里反复在做的事情就几件：刷热门找选题、拆解爆款结构、写文案、改到没有 AI 味、盯着数据复盘、然后下一条。这些经验慢慢变成了肌肉记忆 — 什么标题机制容易爆、什么叙事框架适合种草、什么时间发流量最好、账号权重掉了怎么救。

去年开始用 AI 辅助内容生产，发现一个问题：**AI 能写，但不懂小红书。** 通用大模型写出来的文案要么太"作文"，要么编造数据，要么踩合规红线。

所以把五年的运营方法论 + AI 工程能力融合，做了这个 Skill — **从选题研究、内容生成、合规校验、账号分析、扫码登录、一键发布到发后复盘，小红书运营的全流程一站式搞定。**

> **不是让 AI 替你写小红书，而是把你的运营经验"教"给 AI，让它按你的方法论做研究、生成、校验，你只管审稿和发布。**

49 个 MCP 工具，覆盖从选题到复盘的完整闭环。接入 Cursor、Claude 或任意 AI Agent 就能用。

**我们的愿景很简单：让小红书创作变得更简单，降低写作门槛，人人都能成为小红书爆款笔记创作者。** 不需要你有五年的运营经验，不需要你懂 AI 工程，装上就能用。

---

## 它能帮你解决什么

| 你遇到的问题 | 它怎么帮你 |
|---|---|
| 找选题靠感觉，刷两小时热门还是不知道写什么 | 联网抓取公开热门数据，自动分析热度带、上升词、内容缺口，给你可点选的选题列表 |
| 写一篇文案要两小时，改到没 AI 味又要一小时 | 一键从选题生成完整图文/视频交付包：标题、封面文案、正文、话题标签、CTA 全包，内置去 AI 味改写 |
| 发布前心里没底，怕踩合规红线 | 三道门禁自动过：声明验证 + 原创性检查 + 合规检查，任一不过自动阻断 |
| 不知道账号现在什么情况，该往哪个方向调 | 导入授权数据，估算账号权重和内容健康度，按弱项推荐选题和笔记风格 |
| 发布流程太繁琐，登录-上传-填标签-发布要半小时 | 授权扫码登录 → 草稿预览 → 显式批准 → 自动发布，全程可控 |
| 发完就完了，不知道效果怎么样 | 自动同步发布后指标，归因分析、A/B 实验、复盘建议，闭环运营 |

---

## 30 秒上手

```bash
# 安装
pip install -e '.[dev]'

# 一键从热门选题到成稿
xhs-skill generate --topic "通勤防晒" --search-provider fixture --output output/package.json

# 或者用 MCP 接入你的 AI Agent
python -m xhs_skill.mcp.server --transport stdio
```

---

## 核心能力

### 研究 / 选题
- 联网搜索公开热门笔记，自动去重、排序、趋势分类
- 返回可点选的 `topic_suggestions`，每个选题带 `generate_payload`，一跳生成
- `hot_insights`：热度带、上升词、早期速度信号、内容缺口、标题机制统计

### 内容生成
- 多候选标题/封面/正文，按相关性 + 多样性排序
- 图文分页 / 视频分镜（15/30/45/60s 口播模板）
- 叙事框架：PAS / AIDA / BAB / QUEST / 4P / SCQA
- 笔记类型：测评、种草、避坑、清单、教程、探店、对比、决策

### 校验门禁
- **声明台账**：客观说法自动抽取，无法验证的只能删除或转主观
- **原创性**：字面 + 语义 + 稀有短语 + 图片 pHash 多维度检测
- **合规**：极限词、虚构体验、医疗/金融承诺、商业披露
- **AI 来源**：记录并标识 AI 生成或修改的内容

### 账号分析
- 账号权重估算（非官方分数，明确标注）
- 内容健康度：互动/收藏/节奏/搜索/风险多维度
- 按弱项自动推荐 `note_style` 和选题角度

### 发布与运营
- 授权扫码登录，AES-256-GCM 加密会话
- 草稿 → 预览 → 显式批准 → 发布，每步可拦截
- 发布后自动同步指标：归因分析、权重趋势、内容日历、系列规划、A/B/n 实验、LinUCB 多臂老虎机

---

## 工具一览（49 个 MCP 工具）

| 分组 | 工具 | 说明 |
|---|---|---|
| **研究/选题** | `search_hot_notes` `search_trending_topics` `analyze_hot_notes` `suggest_topics_by_health` | 联网热门研究与选题建议 |
| **生成/改写** | `generate_xhs_note` `generate_from_hot` `rewrite_xhs_note` `diagnose_xhs_note` `plan_content_outline` `draft_comment_reply` `generate_xhs_note_variants` | 内容生成、改写、诊断、评论草稿 |
| **校验门禁** | `verify_claims` `check_originality` `check_compliance` | 声明、原创性、合规检查 |
| **账号/登录** | `query_account_weight` `query_content_health` `diagnose_account` `sync_account_analytics` `start_account_login` `check_account_login` `logout_account` | 账号分析与授权登录 |
| **发布流** | `create_publish_draft` `preview_publish_draft` `approve_publish_draft` `publish_note` `schedule_note` `get_publish_windows` | 草稿、预览、批准、发布、定时 |
| **发后运营** | `sync_published_metrics` `get_performance_attribution` `get_account_weight_trend` `create_content_calendar` `create_content_series` `create_abn_experiment` `choose_content_bandit` `generate_retrospective` `analyze_performance` | 指标同步、归因、日历、实验、复盘 |
| **企业管控** | `get_enterprise_controls` `get_enterprise_budget` `create_enterprise_approval` `decide_enterprise_approval` `verify_enterprise_audit` `enterprise_dlp_scan` | 租户策略、预算、审批、审计、DLP |

完整契约：`contracts/mcp-tools.json`

---

## 支持的模型

| Provider | 适配方式 |
|---|---|
| OpenAI / GPT | Responses API |
| Anthropic / Claude | Messages API |
| Google / Gemini | Generate Content API |
| DeepSeek、Qwen、Ark、GLM、Kimi、MiniMax、混元、千帆 | OpenAI-Compatible |
| Amazon Bedrock | Converse API |
| Azure OpenAI | OpenAI-Compatible |
| 自托管（vLLM 等） | OpenAI-Compatible |

模型标识符是配置，不是硬编码。详见 `assets/providers.yaml`。

---

## 搜索 Provider

| Provider | 说明 |
|---|---|
| `client_web` | 宿主 Agent 传入的 `web_results`（无需 API Key） |
| `brave` | Brave Search API |
| `bing` | Bing Web Search |
| `google_cse` | Google Custom Search |
| `searxng` | 自托管 SearxNG |
| `openai_web` | OpenAI Web Search |
| `fixture` | 离线开发确定性数据 |

未配置 Key 时，自动返回 `needs_web_search`，宿主 Agent 可用自己的搜索能力补充。

---

## 快速开始

```bash
# 1. 安装
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# 2. 配置
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 3. 浏览器发布需要
playwright install chromium

# 4. 运行
xhs-skill serve --host 127.0.0.1 --port 8080   # HTTP API
python -m xhs_skill.mcp.server --transport stdio  # MCP
```

### CLI 示例

```bash
# 搜索热门
xhs-skill search-hot --query "通勤防晒" --provider fixture

# 一键生成
xhs-skill generate --topic "通勤防晒" --search-provider fixture

# 账号分析
xhs-skill account weight --account demo --input examples/account_analytics.json

# 发布流程
xhs-skill publish draft --account demo --package output/package.json
xhs-skill publish preview --draft <draft-id>
xhs-skill publish approve --draft <draft-id>
xhs-skill publish execute --draft <draft-id> --approval-token <token>
```

---

## MCP 接入

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

### HTTP 端点

```bash
POST /mcp
```

### A2A

```bash
GET /.well-known/agent-card.json
```

---

## 安全边界

本 Skill **不会**：
- 绕过验证码、风控或访问控制
- 自动化刷量、虚假评论
- 洗稿或复刻他人内容
- 隐瞒商业合作关系
- 把估算数据伪装成官方数据

发布前必须过三道门禁：声明验证 + 原创性检查 + 合规检查。任一不过，自动阻断。

---

## 企业版

支持 OIDC / SCIM 身份管理、租户隔离、多人审批、DLP、审计哈希链、Vault / KMS 密钥管理。

```bash
pip install -e '.[enterprise]'
```

---

## 项目结构

```text
├── SKILL.md              # Agent 入口（你正在看的 README 的底层协议）
├── src/xhs_skill/        # Python 源码
│   ├── mcp/              # MCP 协议与 49 个工具
│   ├── research/         # 联网研究与趋势分析
│   ├── generation/       # 内容生成与改写
│   ├── verifiers/        # 合规、原创性、声明校验
│   ├── accounts/         # 账号权重与健康度
│   ├── publishing/       # 授权发布流程
│   ├── operations/       # 发后运营与实验
│   ├── enterprise/       # 企业管控
│   └── ...
├── contracts/            # MCP / OpenAPI / A2A 契约
├── schemas/              # 34 个 JSON Schema
├── references/           # Agent 按需加载的参考文档
├── scripts/              # CLI 与运维脚本
├── tests/                # 测试（unit + contract + integration）
└── evals/                # 1750 条评测数据
```

---

## 开发

```bash
pip install -e '.[dev,enterprise,ml,vision]'
pytest
ruff check .
mypy src/xhs_skill scripts
```

---

## License

[MIT](LICENSE)

---

<p align="center">
  <strong>让 AI 做内容研究和生成，你只管审稿和发布。</strong><br>
  <sub>小红书爆款笔记生成 Agent Skill &mdash; 从趋势到发布，一站搞定。</sub>
</p>