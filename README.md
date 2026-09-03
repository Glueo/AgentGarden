# Agent Garden

Agent Garden 是一套本机优先的人机协同知识库和个人经验自进化框架：Hermes 负责交互与执行，OpenViking 保存轨迹、记忆和语义索引，Obsidian Garden 保存稳定知识，Dreamer 定期从重复成功轨迹中提炼可复用经验并维护 Hermes Skills。

## 日常使用

- 直接使用 Hermes；无需手动提示它读取记忆。
- 在 Obsidian 中查看或修改 `garden/`。
- `wiki/`、`sources/` 会单向同步到 OpenViking；原始聊天只留在 OpenViking。
- 每天 03:30 由专用 `dreamer` profile 执行轻量扫描；模型链为 `anyrouter/gpt-5.6-sol` → `micu-api/gpt-5.6-sol`。出现两个尚未处理的独立成功轨迹时事件触发完整 Dream；累计 10 个有效会话或距上次完整 Dream 满 7 天仍作为周期兜底。
- 日常协调器使用 `anyrouter/gpt-5.6-sol`，失败后回退到 `micu-api/gpt-5.6-terra`。
- Hermes 原生 `web_search` 使用免费 DDGS，原生 `web_extract` 使用 Tavily。
- 冲突、证据不足或高风险候选保留在晋升门禁的 `review` 状态，并写入 Dream 审计；Garden 不再维护单独的 review 文件夹。
- Skill 晋升要求两次独立成功轨迹加一次隔离前向测试。前向测试由 `automation/forward_test.py` 在一次性 Hermes home 中真实运行候选 Skill 两次（`gpt-5.6-sol`），门禁自行复核证据，不接受模型自述通过。

## 运行边界

- OpenViking 只监听 `127.0.0.1:1933`。
- API Key 保存在用户目录下权限为 `0600` 的运行配置，不进入本仓库。
- `.runtime/`、OpenViking 数据库、原始会话与日志不进入 Git。
- Dream 生成的 Skill 唯一源文件位于 `~/.hermes/profiles/dreamer/skills/`；主 Hermes 和其他 worker 通过 `skills.external_dirs` 只读加载。
- Hermes 的会后 Skill 创建提醒保持关闭；对话只产生候选证据，Skill 必须经 Dream 门禁、隔离验证、备份和审计后才生效。

常用自检：

```bash
conda run -n agent-garden python automation/healthcheck.py
conda run -n agent-garden python automation/sync_garden.py --dry-run
```
