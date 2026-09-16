---
id: agent-garden-overview
kind: knowledge
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-09-16
topics: [agent-garden, architecture, memory]
---

# Agent Garden 架构概览

Agent Garden 以 Hermes 作为交互与执行入口，以 OpenViking 保存会话、记忆与语义索引，以 Obsidian 保存人和 Agent 都能阅读的稳定知识，以 Hermes 原生 Skills 保存可复用流程。

OpenViking 通过火山方舟固定使用 `doubao-seed-2-0-lite-260215` 异步提取长期记忆，不配置备用渠道或模型。Skill 由 `/learn`、前台 `skill_manage` 与 Hermes 原生后台自改进产生，写入统一经过 Hermes 审批和变更账本；Curator 使用原生生命周期管理，LLM 合并保持关闭。

Agent Garden 不决定主 Hermes 的模型或供应商；用户通过 Hermes 原生模型选择器自行切换。主路由不配置 fallback，普通子代理继承当前主模型；智能审批、会后审查、压缩、标题等辅助任务统一使用独立的 `coderapi` 渠道。

相关政策：[[../_system/policy|自治与写入政策]]、[[../_system/schema|笔记 Schema]]。
