---
id: agent-garden-overview
kind: knowledge
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-09-20
topics: [agent-garden, architecture, memory]
---

# Agent Garden 架构概览

Agent Garden 以 Hermes 作为交互与执行入口，以 `garden/resources/` 保存未经处理的原始源文件，以 `garden/wiki/` 保存翻译和稳定知识，以 OpenViking 保存会话、记忆与语义索引，以 Hermes 原生 Skills 保存可复用流程。

OpenViking 通过火山方舟固定使用 `doubao-seed-2-0-lite-260215` 异步提取长期记忆，不配置备用渠道或模型。Skill 的创建、修改、审批、账本和 Curator 生命周期由 Hermes 原生系统管理。

Hermes Desktop 当前保存的配置是唯一权威来源。Agent Garden 不覆盖主模型、Provider、fallback、辅助任务路由、子代理、Skills、Curator、Web、会话、终端或显示设置，只维护 OpenViking 服务、Garden 内容和单向同步。

相关政策：[[../_system/policy|自治与写入政策]]、[[../_system/schema|笔记 Schema]]。
