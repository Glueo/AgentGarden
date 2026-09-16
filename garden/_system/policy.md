---
id: system-autonomy-policy
kind: policy
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-09-16
topics: [agent-garden, autonomy, review]
---

# 自治与写入政策

稳定知识、长期记忆与可执行 Skill 分别由 Obsidian Garden、OpenViking 和 Hermes 原生系统管理。

- 用户明确表达的个人偏好可直接写入 OpenViking memory。
- 稳定、可引用的显式知识可写入或合并 Wiki，并保留来源 URI。
- OpenViking 可从已提交会话中异步提取长期记忆；其 VLM 通过火山方舟固定使用 `doubao-seed-2-0-lite-260215`，不配置备用渠道或模型。
- Skill 可由 `/learn`、前台 `skill_manage` 或 Hermes 原生后台自改进提出创建或修改。
- Skill 写入必须经过 Hermes 原生审批并进入原生变更账本。
- 凭证、安全策略、删除、付费、公开发布、外部通信、医疗、法律和财务决策始终人工审查。

## Skill 生命周期

- Hermes 的 bundled Skills 由版本更新同步。
- official optional Skills 通过 `hermes skills` 安装、审计和更新。
- 本地 Skills 统一位于 `~/.hermes/skills/`，主会话与普通子代理由 Hermes 原生机制直接加载；不维护 profile 本地副本或额外的 `skills.external_dirs`。
- Skill 创建提醒、后台审查与 Curator 使用 Hermes 原生默认行为；`skills.write_approval=true` 和 `skills.ledger=true` 保证变更经人工审批且可审计，Curator 的 LLM 合并保持关闭。
- Skill 的格式检查、安全扫描、更新、回滚与审批使用 Hermes 原生能力，不在 Agent Garden 中维护平行实现。

## 同步边界

`garden/wiki/` 与 `garden/sources/` 单向同步到 OpenViking。原始会话、OpenViking 数据库和运行状态不写入 Git；稳定 Wiki 内容不由会话记忆反向覆盖。
