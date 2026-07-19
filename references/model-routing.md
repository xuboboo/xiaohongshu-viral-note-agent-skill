# 多模型路由

## 能力优先，不绑定模型名

模型选择依次执行：

1. 过滤缺少硬能力的 Provider，例如视觉任务必须支持图像输入。
2. 过滤不符合数据区域、租户或安全策略的 Provider。
3. 比较结构化输出可靠性、中文适配、上下文长度、历史成功率、成本和延迟。
4. 选择主 Provider，并准备同协议和跨 Provider 回退链。
5. 失败时先遵守 `Retry-After`，再指数退避；内容发布等外部副作用不得盲目重试。

## Provider 类型

- OpenAI Responses
- OpenAI-Compatible，包括 DeepSeek、Qwen、Ark、GLM、Kimi、MiniMax、混元、千帆、OpenRouter、Mistral、Groq、xAI、vLLM 等
- Anthropic Messages 和 Anthropic-Compatible
- Gemini Generate Content
- Amazon Bedrock Converse
- Azure OpenAI，通过 OpenAI-Compatible 的 `api-key` 与 `api-version` 配置

## 能力声明

兼容接口不保证所有能力。`assets/providers.yaml` 可为每个 Provider 明确声明：

- `vision`
- `streaming`
- `tool_calling`
- `structured_output`
- `json_mode`
- `reasoning`
- `web_search`
- `embeddings`
- `reranking`

未声明能力不得自动假设。运行 `scripts/provider_probe.py` 查看当前配置。
