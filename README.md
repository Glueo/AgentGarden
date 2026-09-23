# Agent Garden —— 人机协同的知识 Wiki 与长期记忆系统

Agent Garden 把人类判断、大模型执行、长期记忆和可版本化知识库组织成一个持续生长的协作系统。Hermes 是对话与执行入口，OpenViking 保存会话、长期记忆和语义索引，Obsidian Garden 承载可阅读、可链接、可编辑的稳定知识，Git 记录知识演化历史。

## 系统做什么

- **人机共同维护 Wiki**：人和 Agent 在同一个 Obsidian Vault 中整理知识、建立双向链接并维护主题导航。
- **保存资料与知识形成过程**：`resources/` 归档外部材料的原始快照与全文译文，`wiki/` 保存摘要、学习结论、结构化笔记和长期知识。
- **为 Hermes 提供长期记忆**：OpenViking 保存会话记忆，并为后续对话提供语义检索。
- **同步稳定知识**：同步器把 `wiki/` 单向写入 OpenViking，使人工整理的知识可以在对话中被检索和引用。
- **验证同步结果**：每次同步记录内容哈希、异步任务状态和远端回读结果，持续处理新增、修改、移动与删除。
- **保留完整版本历史**：Wiki、系统规则和自动化代码由 Git 管理，可以审阅、比较和回滚。

## 工作流程

```text
外部资料 ──→ resources/ 原始快照与全文译文 ──→ 人与 Agent 整理 ──→ wiki/ 稳定知识
                                                        │
                                                        ├──→ Git 版本历史
                                                        └──→ OpenViking 语义索引 ──→ Hermes 后续对话

Hermes 对话 ──→ OpenViking 会话与长期记忆 ────────────────────────────────────┘
```

## 目录结构

| 路径 | 用途 |
| --- | --- |
| `garden/resources/` | 外部网页、文档、仓库文件等原始快照及全文译文 |
| `garden/wiki/` | 摘要、学习结论、结构化笔记、主题 Hub 与稳定知识 |
| `garden/_system/` | Garden 的用途、写入政策和笔记 Schema |
| `garden/.obsidian/` | Obsidian Vault 配置 |
| `automation/` | 运行配置、Wiki 同步、健康检查和资料快照脚本 |
| `launchd/` | OpenViking 服务与定时同步的 macOS LaunchAgent 模板 |
| `.runtime/` | 本地同步清单和运行状态 |

## 快速开始

### 1. 准备环境

需要 macOS、Miniconda、Hermes Agent、Obsidian，以及可调用火山方舟模型的 API Key。

```bash
git clone git@github.com:Glueo/AgentGarden.git
cd AgentGarden
conda env create -f environment.yml
conda activate agent-garden
```

环境固定使用 Python 3.11、OpenViking 0.4.20 和 MCP 1.29.0。

### 2. 配置 OpenViking

在 `~/.openviking/ov.conf` 中写入火山方舟的 VLM 与 Embedding 配置：

```json
{
  "vlm": {
    "provider": "volcengine",
    "api_key": "YOUR_VOLCENGINE_API_KEY",
    "api_base": "https://ark.cn-beijing.volces.com/api/v3",
    "model": "doubao-seed-2-0-lite-260215"
  },
  "embedding": {
    "dense": {
      "provider": "volcengine",
      "api_key": "YOUR_VOLCENGINE_API_KEY",
      "api_base": "https://ark.cn-beijing.volces.com/api/v3",
      "model": "doubao-embedding-vision-251215",
      "dimension": 1024,
      "input": "multimodal",
      "batch_size": 8
    }
  }
}
```

初始化脚本会补全本地存储、服务地址和 Hermes 的 OpenViking 连接变量，并把配置文件权限设为 `0600`：

```bash
python automation/install_runtime.py
```

初始化完成后重启 Hermes，使新的 OpenViking 连接变量生效。

### 3. 启动 OpenViking

```bash
openviking-server --config "$HOME/.openviking/ov.conf"
```

保持该终端运行。服务启动后监听 `http://127.0.0.1:1933`，后续命令在另一个终端执行。

### 4. 完成首次同步

先查看同步计划，再等待首次索引完成：

```bash
python automation/sync_garden.py --dry-run
python automation/sync_garden.py --wait
```

最后运行健康检查：

```bash
python automation/healthcheck.py
```

## 日常使用

1. **与 Hermes 对话**：会话和长期记忆由 OpenViking 保存，后续对话可以按语义检索已有记忆与 Wiki。
2. **归档外部资料**：把网页原始 HTML、PDF、图片或仓库文件及其全文译文放入 `garden/resources/`。
3. **沉淀稳定知识**：在 `garden/wiki/` 中编写摘要、学习结论、结构化笔记和主题导航，并链接原始 URL 与对应资源文件。
4. **使用 Obsidian 浏览与编辑**：将 `garden/` 作为 Vault 打开，通过双向链接和 Graph View 浏览知识关系。
5. **同步到 OpenViking**：运行 `sync_garden.py`，或启用 LaunchAgent 每 15 分钟自动同步。
6. **提交 Git 版本**：审阅 Wiki 变化后提交，让知识库保留清晰的演化历史。

## 自动运行

`launchd/` 提供两个模板：

- `com.agent-garden.openviking.plist`：登录后启动并守护 OpenViking。
- `com.agent-garden.sync.plist`：登录后启动同步，并每 15 分钟运行一次。

模板包含当前部署使用的绝对路径。部署到其他目录时，先更新 plist 中的 Python 路径、项目路径、配置路径和日志路径，再安装：

```bash
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/AgentGarden"
cp launchd/com.agent-garden.openviking.plist "$HOME/Library/LaunchAgents/"
cp launchd/com.agent-garden.sync.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.agent-garden.openviking.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.agent-garden.sync.plist"
```

## 同步机制

- 同步范围是 `garden/wiki/`；`resources/` 作为本地原始资料库供 Wiki 引用。
- Markdown 使用原文写入并通过远端正文回读校验。
- 默认同步采用异步语义处理；`--wait` 会等待本轮任务完成。
- `.runtime/sync-manifest.json` 保存每个页面的哈希、URI、任务和清理状态。
- 后续同步会继续核对待处理任务，并完成移动、删除和内容更新。
- `healthcheck.py` 汇总服务状态、语义任务、会话归档和 Wiki 同步状态。

## 当前部署身份

仓库当前使用 OpenViking 账户 `default`、用户 `gwen`，Wiki 根 URI 为 `viking://user/gwen/resources/garden`。其他部署可以在以下位置统一替换身份：

- `automation/install_runtime.py` 中的 OpenViking 环境变量与默认用户；
- `automation/sync_garden.py` 中的 `BASE_URI` 和客户端用户；
- `automation/healthcheck.py` 中的请求身份头；
- `launchd/` 中的本机绝对路径。

## 测试

```bash
python -m unittest discover -s tests -v
```

运行数据位于 `.runtime/`、`~/.openviking/` 和 `~/Library/Application Support/agent-garden/`；日志位于 `~/Library/Logs/AgentGarden/`。凭据保存在本机 OpenViking 配置中。