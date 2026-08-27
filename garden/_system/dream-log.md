---
id: system-dream-log
kind: audit-log
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-08-07
topics: [agent-garden, dream, audit]
---

# Dream 审计日志

自动化每次完整 Dream 在此追加一段简短记录：时间、输入会话、OpenViking snapshot、知识/经验/技能变更、进入人工审查的项目以及 Git commit。

## 2026-08-19 Dream

- 输入会话：`20260807_171334_7bf321`、`20260807_165228_5de56d`、`20260807_165004_226e8d`、`0e2e6f8f-5842-4408-b798-38c8d748a49d`、`20260807_164941_022aa6`、`20260807_162712_e10b05`、`20260807_162548_8a3215`；其中 4 个含工具调用或显式偏好/知识，3 个为无可复用内容的恢复或精确回显测试。
- OpenViking 快照（变更前）：`284bcafea56eb1d8b0f669b0906919668a648373`。
- 结论：重复证据只确认了已有的“功能完整前提下遵循奥卡姆剃刀”用户偏好；该偏好已在 OpenViking memory 中，未新增 Wiki、经验或 Skill。`synthetic-algorithm-fix` 仅有合成轨迹，未通过隔离前向验证，保留为 validated experience，未创建 Skill。
- 审查：无冲突或高风险候选；未写入凭证或其他秘密。
- 同步与验证：使用 `conda run -n agent-garden python automation/sync_garden.py --wait`；测试使用 `conda run -n agent-garden python -m unittest discover -s tests -v`。
- Git commit：本条目所在的 Dream commit（`HEAD`）。

## 2026-08-20 Skill 归属迁移

- 决策：按用户明确要求，Garden 不再保存可执行 Skill 或单独的 review 文件夹。Dreamer profile 的 `~/.hermes/profiles/dreamer/skills/` 成为自动蒸馏 Skill 的唯一可写源；主 Hermes、SOL、Qwen、Claude worker 通过 `skills.external_dirs` 只读加载。
- 迁移 Skill：`algorithm-practice`（`83509e91c49251aad890422e12eaab1203d382f0f90d2d9f0b985de6cde46968`）、`distill-experience`（`0cf5c3d221580d80071f087787b4ec01bf14a8d63c8f31210acf3ef4608f8735`）、`hermes-health-audit`（`5a6aa8b27b715414093fed3a3c0facc3eb305f4dfaba6fe7b1bebc02f25cf94b`）、`hermes-model-orchestration`（`c7d0112045184098ecb055065bc5318c231a5bcffe442ea87fe6c05b3258c74e`）、`model-router`（`582f76152df80381fb272aef8fc34166e7c12418592e6bcdf0b50d506ed58f6f`）。哈希均为迁移后最终 `SKILL.md` 的 SHA-256。
- 可恢复备份：`~/.hermes/skill-migration-backups/20260820-145303/`，包含 Garden 原源、Dreamer 旧版本、各 consumer 的同名副本、旧 usage 数据、CCSwitch 旧链接和迁移动作清单。
- Review 路由：冲突、弱证据和高风险候选只保留在晋升门禁的 `review` 状态并进入 Dream 审计；不再创建 `garden/reviews/` 文件。
- OpenViking：清理 10 个历史 Garden Skill 资源；同步前快照 `8982c4e5c11cd97ec0e7274a50d66348abe0524f`，安全重试复用了同一操作号，最终 dry-run 为 `changed: 0`。
- 验证：5 个迁移后目录均通过 Skill 格式校验；完整测试集 27 项通过。`algorithm-practice` 与 `hermes-model-orchestration` 的独立前向测试通过；健康审计的前向测试发现并促成了对隐式写入、联网披露、原始日志/端点泄露和 SQLite WAL 限制的收紧，最终独立静态复验为 PASS。
- Git commit：本条目所在的迁移 commit（`HEAD`）。

## 2026-08-27 Dream

- 输入会话：`20260819_221044_493970`、`20260820_131752_ccf700`、`20260821_120946_0b47bc`，三者均含工具调用、非平凡产物、显式知识或失败复盘；本轮没有尚未登记的新会话，周期门禁因距上次完整 Dream 已满 7 天而触发。
- OpenViking 快照（变更前）：`7c0d5ad4c02e5fac1a1b7ff4f45ae1dcd2b2d2d6`。
- 稳定知识：接纳并补全 `garden/wiki/算法复习.md` 与 `garden/wiki/C++算法常用库函数.md` 的来源 URI；内容来自 `viking://user/gwen/sessions/20260820_131752_ccf700/history/archive_002`，反例边界是无关联条目不强制建立双向链接、未实际遗忘的 API 不进入专门参考页。
- 候选路由：`hermes-ansi-garbled-output-troubleshooting`、`hermes-session-profile-isolation-explanation`、`algorithm-coaching-wiki-crosslinks` 均只有一次独立成功，保持 provisional experience；`headless-dream-session-enumeration` 只有失败轨迹，保持 provisional；`synthetic-algorithm-fix` 虽有两条合成成功轨迹，但缺少合格的隔离前向验证，门禁上限为 validated experience。
- Skill：没有候选达到“两次独立成功 + 隔离前向测试通过”，因此未创建或修改 Dreamer Hermes Skill；无 Skill 路径、哈希或备份项。
- 审查：无冲突或 mandatory-review 候选；未写入凭证、原始私密会话或其他秘密。
- 验证：运行完整单元测试；运行 `automation/sync_garden.py --wait` 并复查 dry-run 为零变更。
- Git commit：本条目所在的 Dream commit（`HEAD`）。
