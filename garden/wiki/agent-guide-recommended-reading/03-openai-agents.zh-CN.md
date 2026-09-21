---
id: 03-openai-agents-zh-cn
kind: translation
status: stable
source_uris:
  - https://developers.openai.com/api/docs/guides/agents
created: 2026-09-20
updated: 2026-09-20
topics: [agents, openai, agent-runtime, recommended-reading, translation]
language: zh-CN
resource_path: resources/agent-guide-recommended-reading/03-openai-agents.html
---

> 中文翻译；原文归 OpenAI 所有。抓取与翻译日期：2026-09-20。
>
> 源文件：[[../../resources/agent-guide-recommended-reading/03-openai-agents.html|原始 HTML]]

# Agents

> 如需完整的文档索引，请参阅 [llms.txt](/llms.txt)。在文档页面 URL 后附加 `.md`，即可获取该页面的 Markdown 版本。

Agent 可以使用工具来规划并完成任务、与其他 Agent 协作，并在多个步骤之间保持上下文。请根据你希望编排在哪里运行，以及由谁管理任务之间的状态来选择运行时。

## 选择起点

| 你的需求 | 从这里开始 |
| --- | --- |
| 使用由 OpenAI 管理的 Codex harness 运行 Agent | [Agents API](https://developers.openai.com/api/docs/guides/agents-api/quickstart) |
| 在应用程序中使用可复用的 Agent、工具和移交机制来控制 Agent 循环 | [Agents SDK](https://developers.openai.com/api/docs/guides/agents/quickstart) |
| 直接处理模型响应并控制集成方式 | [Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses) |
| 添加嵌入式聊天体验 | [ChatKit](https://developers.openai.com/api/docs/guides/chatkit) |

## 比较 Agent 运行时选项

|  | Agents API | Agents SDK | Responses API |
| --- | --- | --- | --- |
| **适用于** | 由 OpenAI 管理 Agent 并保存其进度的长时间运行任务 | 在应用程序中使用自定义工具和工作流构建 Agent | 直接调用模型或从头构建 Agent |
| Agent 在哪里运行 | OpenAI 运行托管的 Codex harness | SDK 在你的应用程序内部运行 | 在你的应用程序中运行，也可选择使用托管式编排 |
| Agent 集成工作量 | 低 | 中 | 高 |
| 任务之间的状态 | 已保存的会话配置、轮次和项目 | 你的存储与 SDK 会话，或 Responses 会话状态 | 手动管理历史记录、串联响应，或使用 Conversations |
| 工具执行 | 服务连接的工具、应用程序函数处理程序，以及可选的 sandbox | 在你的应用程序中配置的工具和集成 | 托管工具以及由你的应用程序运行的工具 |
| 执行环境 | OpenAI 托管的 sandbox、自托管 sandbox，或不使用 sandbox | 你的运行时及 sandbox 提供商集成 | 你自己的执行环境 |
| 从这里开始 | [Agents API 概览](https://developers.openai.com/api/docs/guides/agents-api/overview) | [Agents SDK 概览](https://developers.openai.com/api/docs/guides/agents/sdk) | [Responses 指南](https://developers.openai.com/api/docs/guides/migrate-to-responses) |

Agents API 运行 Codex harness 并管理底层 Agent 基础设施，让你可以专注于 Agent 所执行的工作。它包括自动上下文压缩、多 Agent 编排、程序化工具调用，以及对 MCP 服务器的支持。请参阅[架构](https://developers.openai.com/api/docs/guides/agents-api/architecture)。

Agents SDK 让你的应用程序可以控制部署、存储、审批和运行时集成。它的 runner 负责处理 Agent 循环和移交。请参阅[运行 Agent](https://developers.openai.com/api/docs/guides/agents/running-agents)。

## 添加工具、Skills 和提示词缓存

工具设计、可复用 Skills 和提示词缓存适用于各种 Agent 工作流。它们的配置和生命周期可能因 API 而异。

- 从[使用工具](https://developers.openai.com/api/docs/guides/tools)开始，了解函数调用、MCP 和托管能力。
- 阅读 [Programmatic Tool Calling](https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling)，了解使用 JavaScript 进行编排的方法以及各 API 的配置。
- 使用 [Skills](https://developers.openai.com/api/docs/guides/tools-skills)来提供可复用指令，并了解支持的加载机制。
- 阅读[提示词缓存](https://developers.openai.com/api/docs/guides/prompt-caching)，了解共享缓存行为；然后阅读 [Agents API 可观测性与用量](https://developers.openai.com/api/docs/guides/agents-api/observability)，了解会话计量。

Agents API 会话、SDK 会话、Responses conversation 和 sandbox 是不同的资源。请遵循所选运行时对应的状态管理与清理说明。
