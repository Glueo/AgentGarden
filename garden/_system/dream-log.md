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

## 2026-09-03 Dream

- 输入会话：本轮消费 11 个已登记有效会话（2026-08-27 至 2026-09-02）；新扫描 6 个会话，其中 `20260902_204728_b1ec10`、`20260902_234905_3b77ae` 与 `cron_5514cfcf65fd_20260831_151159` 含工具调用、已验证产物或失败边界，判为有效；两个固定字符串探测及一个仅问候会话无可复用证据，判为无效。周期门因有效会话达到 11/10 而触发，事件门同时由 `hermes-system-update-maintenance` 触发。
- OpenViking 快照（变更前）：`074995b821cbfe422c5b85a766803af9a8beab70`（已通过 snapshot show 回读核验）。
- 候选路由：`hermes-system-update-maintenance` 有两次独立成功升级轨迹，门禁评估为 `validated_experience`；已有 OpenViking 经验 `Hermes系统更新操作` 覆盖该流程。反例是非 Git 安装不能套用同一更新路径，且更新未完成配置、Gateway 与 doctor 回读时不得宣称成功。`provider-model-availability-probing` 只有一次成功轨迹，保持 `provisional_experience`；其反例是 `/models` 中存在模型不等于实时可用，未禁用 fallback 的探测会产生假阳性。此前单次成功候选继续保持 provisional；`headless-dream-session-enumeration` 仍只有失败证据。
- Skill：未创建或修改。更新流程与现有 Dreamer `hermes-agent` Skill 实质重叠，应优先合并而非新建近重复 Skill；本轮未执行可授权的隔离前向测试，因此门禁上限为 validated experience。模型可用性探测证据不足两条。无 Skill 路径、哈希、备份或验证项。
- 知识与审查：新会话对应的事件与过程经验已由 OpenViking 提取存在，无需重复写 Wiki 或 memory。无冲突或 mandatory-review 候选；未记录凭证、端点秘密或原始私密会话。
- 同步与验证：运行 `/opt/homebrew/Caskroom/miniconda/base/bin/conda run -n agent-garden python automation/sync_garden.py`，结果 `changed: 0`；同一环境运行 `python -m unittest discover -s tests -v`，37 项全部通过。Git commit 为本条目所在的 Dream commit（`HEAD`）。

## 2026-09-04 Dream

- 输入会话：新扫描 13 个已提交 OpenViking 会话；`20260903_170621_d27b19`、`20260903_204251_2f7f94`、`20260904_003126_27b873`、`cron_5514cfcf65fd_20260903_164011` 与 4 个 `hermes-remember-*` 会话含工具产物、失败复盘或显式知识，判为有效；5 个固定字符串路由探测判为无效。4 个 remember 会话是原始会话的派生记忆提交，不计作独立成功轨迹。周期门为 8/10、`due: false`；事件门由 `hermes-model-channel-fallback-configuration` 的第二条独立成功轨迹触发。
- OpenViking 快照（变更前）：`56d74b83d9e287d2828659f5e5631d40e908a207`（已通过 snapshot show 回读核验）。
- 候选路由：`hermes-model-channel-fallback-configuration` 的来源为 `viking://user/gwen/sessions/20260827_182852_578a6f/history/archive_001` 与 `viking://user/gwen/sessions/20260903_170621_d27b19/history/archive_002`，两次独立成功，门禁上限为 `validated_experience`；已有 `viking://user/gwen/memories/experiences/hermes_fallback_provider_chain_configure.md` 覆盖流程。反例是未经用户确认顺序、未验证 provider 鉴权与最小请求、未回读配置并重启 Gateway 时不得套用或宣称成功。`hermes-source-zero-modification-recovery`、`fallback-context-compression-diagnosis`、`distill-experience-workflow-run` 各只有一次独立成功，保持 `provisional_experience`；前者不得对非 Git 安装或未确认归属的本地修改执行破坏性还原，后两者分别不得把单一版本阈值缺口泛化到所有模型、不得把同一 Dream 的派生产物当作独立证据。
- OpenViking 经验：对 `fallback-context-compression-diagnosis` 提交并完成提取，生成 `viking://user/gwen/memories/experiences/fallback_context_compression_diagnosis.md`；其来源为 `viking://user/gwen/sessions/20260904_003126_27b873/history/archive_001`。核心边界是主模型恢复不等于被 fallback 压缩的历史可恢复，且 75%/85% 阈值结论必须按当前版本、模型元数据与日志重新核验。其他新会话的事件、偏好与过程记录已由 OpenViking 提取，未重复写 Garden Wiki。
- 人工审查：`openai-codex-900k-selector-removal` 仅有 `viking://user/gwen/sessions/20260903_204251_2f7f94/history/archive_002` 一次成功，且涉及 Hermes 核心源码、多条模型目录/缓存/传输路径，两个独立审查尝试均中断；门禁按不明确爆炸半径保留 `review`。反例是旧缓存或 current-model 回注仍可复活退役别名，标准 Codex 模型回归或后续 upstream update 覆盖本地补丁时均不能视为完成。已有经验 `viking://user/gwen/memories/experiences/模型选择器合成模型移除排查.md`，本轮不自动改 Skill 或源码。
- Skill：未创建或修改。模型 provider、fallback 与配置管理行为实质重叠于 Dreamer `hermes-agent` Skill 的 `references/providers-and-models.md`；候选无隔离前向测试证据，因此不得超过 validated experience。源码移除候选仍在 review。无 Skill 路径、哈希、备份或验证证据。
- 同步与验证：`conda run -n agent-garden python automation/sync_garden.py --wait` 与后续 dry-run 均为 `changed: 0`；`conda run -n agent-garden python -m unittest discover -s tests -v` 共 56 项全部通过。Git commit 为本条目所在的 Dream commit（`HEAD`）。
