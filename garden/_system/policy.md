---
id: system-autonomy-policy
kind: policy
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-09-21
topics: [agent-garden, autonomy, review]
---

# 自治与写入政策

原始资源、稳定知识、长期记忆与可执行 Skill 分别由 Garden Resources、Obsidian Wiki、OpenViking 和 Hermes 原生系统管理。

- 用户明确表达的个人偏好可直接写入 OpenViking memory。
- 稳定、可引用的显式知识可写入或合并 Wiki，并保留来源 URI。
- 外部网页、文档与仓库文件先以原始格式保存到 `garden/resources/`；翻译、摘要、重组和知识沉淀写入 `garden/wiki/`，并链接对应源文件。
- OpenViking 可从已提交会话中异步提取长期记忆；其 VLM 通过火山方舟固定使用 `doubao-seed-2-0-lite-260215`，不配置备用渠道或模型。
- Skill 的创建、修改、审批、账本和后台维护由 Hermes 原生系统按 Desktop 当前配置执行。
- 凭证、安全策略、删除、付费、公开发布、外部通信、医疗、法律和财务决策始终人工审查。

## Skill 生命周期

- Hermes Desktop 保存的配置是模型、Provider、fallback、辅助任务、子代理、Skills、Curator、Web、会话、终端与显示设置的唯一权威来源。
- Agent Garden 不修改 `~/.hermes/config.yaml`，不维护 profile Skill 副本或额外 Skill 目录，也不强制任何 Skill/Curator 开关。
- Curator 的 LLM consolidation 会由辅助模型分析重叠 Skill、建立 umbrella Skill 并归档被吸收的旧 Skill；是否启用完全由 Desktop 当前配置决定。
- Skill 的格式检查、安全扫描、更新、回滚与审批使用 Hermes 原生能力，Agent Garden 不维护平行实现。

## 同步边界

`garden/wiki/` 单向同步到 OpenViking。`resources/` 保留源文件原貌，仅作为本地归档，不参与同步；`wiki/` 保存翻译与知识沉淀。原始会话、OpenViking 数据库和运行状态不写入 Git；稳定 Wiki 内容不由会话记忆反向覆盖。
