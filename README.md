# Agent Garden

Agent Garden 是一套本机优先的人机协同知识系统：Hermes 负责交互、执行与原生 Skills，OpenViking 保存会话、记忆和语义索引，Obsidian Garden 保存稳定知识，Git 提供版本历史。

## 日常使用

- 直接使用 Hermes；无需手动提示它读取记忆。
- 在 Obsidian 中查看或修改 `garden/`。
- `wiki/`、`sources/` 会单向同步到 OpenViking；原始聊天只留在 OpenViking。
- Hermes 的 bundled、official 与本地 Skills 统一位于 `~/.hermes/skills/`。新增或修改 Skill 只通过明确的 `/learn` 或 `skill_manage` 请求，并经过 Hermes 写入审批与原生变更账本。
- 日常协调器使用 `anyrouter/gpt-6-astra`，失败后依次回退到 `anyrouter/gpt-5.6-sol`、`openai-codex/gpt-5.6-sol` 和 `micu-api/gpt-5.6-sol`。普通 `delegate_task` 不固定独立模型，原生继承协调器当前主路由与完整 fallback 链；Micu SOL 只作为主会话和其子代理的最后一级回退，不供辅助任务、OpenViking 或定时任务使用。AnyRouter 只承载 GPT；其 Claude 系列在实际使用中不可用，已于 2026-09 连同对应的 Hermes 源码补丁一起移除。
- OpenViking 的 VLM 通过火山方舟固定使用 `doubao-seed-2-0-lite-260215`；会话提交后的异步记忆提取只消耗该模型的独立 Ark 额度，不使用 Camel、Qwen 或 Micu。
- Hermes 原生 `web_search` 使用免费 DDGS，原生 `web_extract` 使用 Tavily。

## 运行边界

- OpenViking 只监听 `127.0.0.1:1933`。
- API Key 保存在用户目录下权限为 `0600` 的运行配置，不进入本仓库。
- 首次安装前必须由用户在 `~/.openviking/ov.conf` 中预置火山方舟 VLM 凭据；`install_runtime.py` 只复用已经绑定到 Ark 官方 API 的凭据，不会从旧 Camel/OpenAI 配置或其他模型渠道迁移密钥。
- `.runtime/`、OpenViking 数据库、原始会话与日志不进入 Git。
- 默认 Hermes 直接使用 `~/.hermes/skills/`；worker 通过 `skills.external_dirs` 读取同一目录，不保留遮蔽共享版本的本地副本。
- 同步 manifest v2 为每个资源记录 `accepted/pending/completed/failed` 与 `task_id`；异步受理不等于完成，只有任务终态成功且远端正文回读一致才完成。`healthcheck.py` 会区分 configured/available，并输出未恢复任务和同步积压。
- 移动清理记录精确的来源路径，并在删除前检查当前文件和其他 manifest 记录。重新出现的来源文件保留，失效的删除请求随之撤销。
- 删除使用公开 HTTP 接口同时校验语义刷新与目标不存在；部分失败保留 `delete_pending`、`cleanup_uris`、`cleanup_sources` 和 `cleanup_attempts`，供后续核验。
- Hermes 的会后后台审查、Skill 创建提醒与 Curator 自动维护保持关闭；对话不会自动创建、合并或归档 Skill。

常用自检：

```bash
conda run -n agent-garden python automation/healthcheck.py
conda run -n agent-garden python automation/sync_garden.py --dry-run
```

`--dry-run` 只显示本地变更计划。`changed=0` 仍须结合健康检查和远端正文校验判断；普通同步在存在未完成、失败或待清理记录时返回非零退出码。

删除响应丢失、语义刷新失败、上传任务身份不明或旧清理记录缺乏来源证明时，同步器保留状态并等待人工核验，不会重复删除或把后续 404 当作恢复成功。恢复时先核对公开 task、fs/stat 接口、原操作快照及来源记录，再通过经批准的维护操作处理该目标；保留未核实的记录和数据。
