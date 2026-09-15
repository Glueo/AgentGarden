---
id: agent-garden-overview
kind: knowledge
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-09-14
topics: [agent-garden, architecture, memory]
---

# Agent Garden 架构概览

Agent Garden 以 Hermes 作为交互与执行入口，以 OpenViking 保存会话、记忆与语义索引，以 Obsidian 保存人和 Agent 都能阅读的稳定知识，以 Hermes 原生 Skills 保存明确创建的可执行流程。

OpenViking 通过火山方舟固定使用 `doubao-seed-2-0-lite-260215` 异步提取长期记忆，不配置备用渠道或模型。Skill 只通过明确的 `/learn` 或 `skill_manage` 请求写入，并经过 Hermes 原生审批和变更账本；Hermes 的后台审查、创建提醒和 Curator 均保持关闭，普通会话不自动生成 Skill。

相关政策：[[../_system/policy|自治与写入政策]]、[[../_system/schema|笔记 Schema]]。
