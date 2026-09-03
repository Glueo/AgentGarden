---
id: system-autonomy-policy
kind: policy
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-09-03
topics: [agent-garden, autonomy, review]
---

# 自治与晋升政策

系统按证据和风险路由候选，而不是采用模型自报置信度。

- 用户明确表达的个人偏好可直接写入 OpenViking memory。
- 稳定、可引用的显式知识可写入或合并 Wiki，并保留来源 URI。
- 单次过程经验保持 `provisional`。
- 普通过程经验至少需要两个相互独立的成功轨迹才可晋升。
- Skill 还必须通过格式校验、代表性样例和隔离前向测试。
- 未经授权的外部写入不得自动加入 Skill。
- 冲突、证据不足或高影响候选保留在晋升门禁的 `review` 状态并写入 Dream 审计，不创建单独的 review 文件。
- 凭证、安全策略、删除、付费、公开发布、外部通信、医疗、法律和财务决策始终人工审查。

Dreamer profile 是自动蒸馏 Skill 的唯一可写源；主 Hermes 和其他 worker 只读加载。每次完整 Dream 必须先创建 OpenViking snapshot，为 Skill 写入保留可恢复备份，并在变更后形成独立 Git commit 与简短审计记录。若验证、备份或 Git commit 失败，不得宣称晋升完成。

## 前向测试

隔离前向测试由 `automation/forward_test.py` 执行，不接受模型自述的结果。候选 Skill 被复制进一次性 Hermes home——不加载其他 Skill、不配置 memory provider——对其声明的代表性输入连续独立运行两次；两次都满足断言，且 `garden/`、`.runtime/`、Dreamer skills 目录与 Hermes 配置的前后哈希均未变化，才记为 `passed`。需要越界写入的候选因此必然失败。

`promotion_gate.py evaluate` 自行复核这份证据：其中记录的 `SKILL.md` 与 `forward-test.json` 哈希必须仍与磁盘一致，证据不得超过 14 天。命令行没有可以直接断言"已验证"的开关，绿灯之后再改 Skill 会使该次通过立即失效。

门禁返回 `promote_skill` 后，Dreamer 可无需另行授权在自己的 profile 中创建或更新 Skill，但必须先备份原目录，优先合并而非新建近重复 Skill，并在审计中记录路径、写入后哈希、备份位置与前向测试证据。
