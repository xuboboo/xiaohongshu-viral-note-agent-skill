# 高并发执行

## 单包分布式模式

本 Skill 的同一 Python 包同时包含 API、Worker、Redis Streams、SSE、分布式锁和发布调度，不依赖另一个代码仓库。

## 原则

1. 慢任务进入有界队列，不为每个请求无限创建异步任务。
2. 研究、生成、Provider、浏览器和发布使用独立 Bulkhead。
3. 每租户和每 Provider 设置并发、速率和排队上限。
4. 多副本部署启用 Redis Streams 任务与事件；SSE 使用 `Last-Event-ID` 重放。
5. 相同研究请求通过缓存与 SingleFlight 合并。
6. 遵守外部服务 `429/503` 与 `Retry-After`，使用指数退避和熔断。
7. 每个账号的登录和发布使用分布式锁；发布副作用必须具备内容 Hash 和幂等指纹。
8. 浏览器与发布并发应远低于纯文本任务，避免账号风险和机器资源耗尽。
9. Redis 被配置为分布式必需组件时不可静默退回不安全的本地模式。
10. 使用 Prometheus、OpenTelemetry 和压测脚本校准真实 P95、错误率和容量。
