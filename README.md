# Agent Garden

Agent Garden 是一套本机优先的人机协同知识库和个人经验自进化框架：Hermes 负责交互与执行，OpenViking 保存轨迹、记忆和语义索引，Obsidian Garden 保存稳定知识与技能，Dreamer 定期从重复成功轨迹中提炼可复用经验。

## 日常使用

- 直接使用 Hermes；无需手动提示它读取记忆。
- 在 Obsidian 中查看或修改 `garden/`。
- `wiki/`、`sources/`、`skills/` 会单向同步到 OpenViking；原始聊天只留在 OpenViking。
- 每天 03:30 检查是否需要 Dream。累计 10 个有效会话，或距上次完整 Dream 满 7 天，才执行完整提炼。
- 只有冲突、证据不足或高风险候选进入 `garden/reviews/`。

## 运行边界

- OpenViking 只监听 `127.0.0.1:1933`。
- API Key 保存在用户目录下权限为 `0600` 的运行配置，不进入本仓库。
- `.runtime/`、OpenViking 数据库、原始会话与日志不进入 Git。
- Skill 的唯一源文件位于 `garden/skills/`，Hermes 通过 `skills.external_dirs` 直接加载。

常用自检：

```bash
conda run -n agent-garden python automation/healthcheck.py
conda run -n agent-garden python automation/sync_garden.py --dry-run
```
