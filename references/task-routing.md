# 任务路由

## 支持模式

| 模式 | 触发意图 | 核心输出 |
|---|---|---|
| `SEARCH_HOT_NOTES` | 搜索近期热门笔记 | `HotNotesReport` |
| `SEARCH_TRENDING_TOPICS` | 搜索正在上升的话题 | 趋势分类和证据 |
| `ANALYZE_HOT_NOTES` | 分析参考笔记机制 | 内容机制卡 |
| `CREATE_NOTE` | 从零生成笔记 | `DeliveryPackage` |
| `GENERATE_FROM_TRENDS` | 结合当前趋势原创 | 研究与内容包 |
| `REWRITE_NOTE` | 改写现有笔记 | 保事实的修订稿 |
| `DIAGNOSE_NOTE` | 诊断标题、正文和风险 | 审核报告 |
| `SYNC_ACCOUNT_ANALYTICS` | 导入授权账号数据 | 标准化账号分析 |
| `QUERY_ACCOUNT_WEIGHT` | 查询账号权重 | 非官方估算报告 |
| `AUTHENTICATE_ACCOUNT` | 授权扫码登录 | 加密会话状态 |
| `CREATE_PUBLISH_DRAFT` | 填充创作平台 | 草稿与预览 |
| `PUBLISH_NOTE` | 发布已批准内容 | 发布结果和审计 |
| `SCHEDULE_NOTE` | 定时发布已批准内容 | 调度记录 |
| `ANALYZE_PERFORMANCE` | 发布后复盘 | 描述性结论和实验建议 |

## 路由规则

1. 用户要求“当前、最近、今天、热门、趋势”时必须进入研究流程。
2. 用户提供原稿并要求优化时进入改写，不得重写用户未授权改变的事实。
3. 涉及账号登录、退出、发布或定时发布时进入高影响工具流程，必须取得显式授权。
4. 涉及医疗、金融、教育结果、未成年人或其他高风险行业时必须进入人工复核。
5. 公开网页结果始终标记 `PUBLIC_INDEX_TREND`；授权互动数据才允许使用 `METRIC_HOT_SCORE`。
6. 无法确定任务时先提取 Brief；次要字段可采用可见假设，事实和经历不得推测。
