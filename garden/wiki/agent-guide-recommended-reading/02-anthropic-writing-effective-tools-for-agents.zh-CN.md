---
id: 02-anthropic-writing-effective-tools-for-agents-zh-cn
kind: translation
status: stable
source_uris:
  - https://www.anthropic.com/engineering/writing-tools-for-agents
created: 2026-09-20
updated: 2026-09-20
topics: [agents, tools, evaluation, recommended-reading, translation]
language: zh-CN
resource_path: resources/agent-guide-recommended-reading/02-anthropic-writing-tools-for-agents.html
---

> 中文翻译；原文归 Anthropic 所有。抓取与翻译日期：2026-09-20。
>
> 源文件：[[../../resources/agent-guide-recommended-reading/02-anthropic-writing-tools-for-agents.html|原始 HTML]]

# 与 Agent 一起编写高效的工具

发布于 2025 年 9 月 11 日

Agent 的效能取决于我们为它们提供的工具。本文将介绍如何编写高质量的工具和评估，以及如何借助 Claude 优化它自己的工具，从而提升性能。

[模型上下文协议（Model Context Protocol，MCP）](https://modelcontextprotocol.io/docs/getting-started/intro)可以为大语言模型（LLM）Agent 提供多达数百种工具，帮助它们解决现实世界中的任务。但怎样才能让这些工具发挥最大效用？

本文将介绍我们在多种 Agentic AI 系统中提升性能最有效的技术[^1]。

首先，我们会讲解如何：

* 构建工具原型并进行测试
* 创建并运行由 Agent 使用工具的全面评估
* 与 Claude Code 等 Agent 协作，自动提升工具性能

最后，我们会总结在实践中发现的编写高质量工具的关键原则：

* 选择应当实现（以及不应实现）的工具
* 通过工具命名空间明确功能边界
* 让工具向 Agent 返回有意义的上下文
* 优化工具响应的 Token 效率
* 对工具描述和规范进行提示词工程优化

## 什么是工具？

在计算领域，确定性系统在输入相同时，每次都会产生相同的输出；而像 Agent 这样的*非确定性*系统，即使初始条件相同，也可能生成不同的响应。

传统的软件开发是在确定性系统之间建立契约。例如，像 `getWeather(“NYC”)` 这样的函数调用，每次调用时都会以完全相同的方式获取纽约市的天气。

工具是一种新型软件，它体现的是确定性系统与非确定性 Agent 之间的契约。当用户问“我今天需要带伞吗？”时，Agent 可能会调用天气工具，也可能根据常识作答，甚至可能先询问用户所在的位置。有时，Agent 也可能产生幻觉，甚至无法理解工具的用法。

这意味着，我们需要从根本上重新思考为 Agent 编写软件的方式：不能再沿用为其他开发者或系统编写函数和 API 的思路来编写工具与 [MCP 服务器](https://modelcontextprotocol.io/)，而要针对 Agent 进行设计。

我们的目标是扩大 Agent 能够有效解决问题的范围，使它们可以借助工具尝试多种策略，并通过其中不同的可行路径完成任务。幸运的是，根据我们的经验，对 Agent 最“易用”的工具，往往也出人意料地便于人类直观理解。

## 如何编写工具

本节将介绍如何与 Agent 协作，既用它们来编写工具，也用它们来改进所提供的工具。首先快速搭建工具原型并在本地测试；接着运行全面评估，以衡量后续变更带来的影响。通过与 Agent 协作，你可以反复评估并改进工具，直到 Agent 在现实任务中取得优异表现。

### 构建原型

如果不亲自实践，就很难预先判断哪些工具对 Agent 易用、哪些不易用。第一步应当是快速搭建工具原型。如果你使用 [Claude Code](https://www.anthropic.com/claude-code) 编写工具（甚至可能一次性完成），最好向 Claude 提供这些工具所依赖的软件库、API 或 SDK 的文档，其中也可能包括 [MCP SDK](https://modelcontextprotocol.io/docs/sdk)。适合 LLM 阅读的文档通常可以在官方文档网站上的扁平化 `llms.txt` 文件中找到（例如我们的 [API 文档](https://docs.anthropic.com/llms.txt)）。

将工具封装在[本地 MCP 服务器](https://modelcontextprotocol.io/docs/develop/connect-local-servers)或[桌面扩展](https://www.anthropic.com/engineering/desktop-extensions)（DXT）中，就可以把工具连接到 Claude Code 或 Claude Desktop 应用中进行测试。

要将本地 MCP 服务器连接到 Claude Code，请运行 `claude mcp add   [args...]`。

要将本地 MCP 服务器或 DXT 连接到 Claude Desktop 应用，请分别进入 `Settings > Developer` 或 `Settings > Extensions`。

也可以把工具直接传入 [Anthropic API](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview) 调用，以便进行程序化测试。

亲自测试这些工具，找出所有不顺手之处。收集用户反馈，逐步建立对工具所要支持的用例和提示词的直觉认识。

### 运行评估

接下来，需要通过运行评估来衡量 Claude 使用工具的效果。首先，应以现实使用场景为依据，生成大量评估任务。我们建议与 Agent 协作，让它帮助分析结果，并判断应该如何改进工具。我们的[工具评估 Cookbook](https://platform.claude.com/cookbook/tool-evaluation-tool-evaluation)完整展示了这一端到端流程。

**生成评估任务**

有了早期原型后，Claude Code 可以快速探索工具并创建数十组提示词与响应对。提示词应当来自现实用例，并基于真实的数据源与服务（例如内部知识库和微服务）。我们建议避免过于简单或流于表面的“沙盒”环境，因为它们不够复杂，无法对工具进行充分的压力测试。优秀的评估任务可能需要多次工具调用，甚至多达数十次。

以下是一些优秀任务的示例：

* 安排我下周与 Jane 开会，讨论最新的 Acme Corp 项目。附上上一次项目规划会议的笔记，并预订一间会议室。
* 客户 ID 9182 报告称，一次购买尝试却被扣款三次。找出所有相关日志条目，并判断是否还有其他客户受到同一问题的影响。
* 客户 Sarah Chen 刚刚提交了取消服务的请求。请准备一份挽留方案。确定：(1) 她离开的原因；(2) 哪种挽留优惠最有吸引力；(3) 在提出方案前，我们应当注意哪些风险因素。

以下则是一些较弱的任务：

* 安排下周与 jane@acme.corp 开会。
* 在支付日志中搜索 `purchase_complete` 和 `customer_id=9182`。
* 查找客户 ID 45892 的取消请求。

每条评估提示词都应配有可验证的响应或结果。验证器可以非常简单，例如将标准答案与采样响应进行精确字符串比较；也可以非常高级，例如让 Claude 对响应进行评判。应避免使用过于严格的验证器，以免仅仅因为格式、标点或其他同样正确的措辞存在无关紧要的差异，就拒绝正确答案。

对于每组提示词—响应对，还可以选择指定你期望 Agent 在解决任务时调用的工具，以衡量评估过程中 Agent 是否正确理解了每个工具的用途。不过，由于正确解决任务可能存在多条有效路径，应尽量避免对策略规定得过细或过拟合。

**运行评估**

我们建议直接调用 LLM API，以程序化方式运行评估。使用简单的 Agent 循环（即用 `while` 循环交替封装 LLM API 调用与工具调用），每个评估任务对应一个循环。每个参与评估的 Agent 都应只获得一条任务提示词以及你的工具。

在评估 Agent 的系统提示词中，我们建议要求 Agent 不仅输出结构化的响应块（用于验证），还要输出推理块和反馈块。要求 Agent 在工具调用块和响应块*之前*输出这些内容，可能会触发思维链（Chain of Thought，CoT）行为，从而提升 LLM 的有效智能水平。

如果使用 Claude 运行评估，可以开启[交错式思考（interleaved thinking）](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking#interleaved-thinking)，直接获得类似的现成功能。它可以帮助你探查 Agent 为何调用或不调用某些工具，并指出工具描述与规范中有待改进的具体部分。

除了总体准确率，我们还建议收集其他指标，例如单次工具调用与单个任务的总运行时间、工具调用总次数、Token 总消耗量以及工具错误。跟踪工具调用有助于揭示 Agent 经常采用的工作流，也能发现可以整合工具的机会。

**分析结果**

Agent 是得力的合作伙伴，能够发现问题，并对互相矛盾的工具描述、低效的工具实现以及令人困惑的工具 Schema 等各类事项提供反馈。不过请记住，Agent 在反馈和响应中*没有说什么*，往往比说了什么更重要。LLM 并不总是[言如其意](https://www.anthropic.com/research/tracing-thoughts-language-model)。

观察 Agent 在哪些地方受阻或感到困惑。通读评估 Agent 的推理和反馈（或 CoT），找出不顺畅之处。检查原始记录（包括工具调用和工具响应），捕捉 Agent 的 CoT 中未明确描述的行为。要读出言外之意；请记住，参与评估的 Agent 并不一定知道正确答案和正确策略。

分析工具调用指标。大量重复的工具调用可能说明需要适当调整分页参数或 Token 限制参数；大量由无效参数引发的工具错误，则可能说明工具需要更清晰的描述或更好的示例。推出 Claude 的[网页搜索工具](https://www.anthropic.com/news/web-search)时，我们发现 Claude 会不必要地在工具的 `query` 参数后附加 `2025`，导致搜索结果出现偏差并降低性能（我们通过改进工具描述，将 Claude 引导到了正确方向）。

### 与 Agent 协作

你甚至可以让 Agent 分析结果并替你改进工具。只需将评估 Agent 的运行记录拼接起来，再粘贴到 Claude Code 中即可。Claude 非常擅长分析运行记录，并一次性重构大量工具。例如，它可以确保在做出新变更后，工具实现与描述仍然相互一致。

事实上，本文的大部分建议都来自我们使用 Claude Code 对内部工具实现进行反复优化的过程。我们的评估建立在内部工作区之上，复现了内部工作流的复杂性，其中包括真实的项目、文档和消息。

我们依靠留出测试集来确保没有对“训练”评估发生过拟合。这些测试集表明，即使已经采用“专家级”工具实现，我们仍能进一步提升性能——无论这些工具是由研究人员手工编写，还是由 Claude 自行生成。

下一节将分享我们从这一过程中得到的部分经验。

## 编写高效工具的原则

本节将我们的经验提炼为几条编写高效工具的指导原则。

### 为 Agent 选择正确的工具

工具并非越多，效果就越好。我们观察到一种常见错误：工具只是简单封装现有软件功能或 API 端点，却不考虑它是否适合 Agent 使用。这是因为 Agent 与传统软件具有不同的“可供性”（affordance），也就是说，它们感知这些工具所能执行之潜在操作的方式并不相同。

LLM Agent 的“上下文”有限（即它们一次能处理的信息量有上限），而计算机内存既便宜又充足。以在通讯录中查找联系人为例。传统软件程序可以高效地存储联系人列表，逐一处理并检查每个联系人，再继续检查下一个。

然而，如果 LLM Agent 使用的工具会返回**所有**联系人，然后不得不逐 Token 阅读每一项，它就会把有限的上下文空间浪费在无关信息上（这就像在通讯录中找人时，从每一页顶部一路读到底，也就是采用暴力搜索）。更好也更自然的方法——无论对 Agent 还是人类而言——都是先直接跳到相关页面，例如按字母顺序定位。

我们建议先精心构建少量工具，针对与评估任务相符且影响较大的特定工作流，然后再以此为基础逐步扩展。在通讯录示例中，与其实现 `list_contacts` 工具，不如选择实现 `search_contacts` 或 `message_contact` 工具。

工具可以整合多项功能，在内部处理可能*多项*彼此独立的操作（或 API 调用）。例如，工具可以在响应中补充相关元数据，也可以通过一次工具调用处理那些经常串联执行的多步骤任务。

以下是一些示例：

* 与其分别实现 `list_users`、`list_events` 和 `create_event` 工具，不如考虑实现一个 `schedule_event` 工具，由它查找空闲时间并安排活动。
* 与其实现 `read_logs` 工具，不如考虑实现 `search_logs` 工具，只返回相关日志行及其部分上下文。
* 与其分别实现 `get_customer_by_id`、`list_transactions` 和 `list_notes` 工具，不如实现一个 `get_customer_context` 工具，一次性汇总某位客户近期的所有相关信息。

务必确保构建的每个工具都有清晰、独特的用途。工具应使 Agent 能够以与人类相近的方式拆分并解决任务——前提是人类可以访问相同的底层资源——同时减少原本会被中间输出占用的上下文。

工具过多或功能重叠，也可能分散 Agent 的注意力，使其无法采用高效策略。审慎、有选择地规划要构建（或不构建）的工具，确实会带来丰厚回报。

### 为工具设置命名空间

你的 AI Agent 可能会获得数十个 MCP 服务器和数百种不同工具的访问权限，其中还包括其他开发者提供的工具。当工具功能重叠或用途含糊时，Agent 可能会困惑，不知道该使用哪一个。

命名空间（用共同前缀将相关工具分组）有助于划清大量工具之间的边界；MCP 客户端有时会默认这样做。例如，按服务为工具设置命名空间（如 `asana_search`、`jira_search`），以及按资源设置命名空间（如 `asana_projects_search`、`asana_users_search`），可以帮助 Agent 在正确的时机选择正确的工具。

我们发现，在基于前缀和基于后缀的命名空间方案之间做选择，会对工具使用评估产生不可忽视的影响。不同 LLM 上的效果各不相同，因此我们建议根据自己的评估结果选择命名方案。

Agent 可能调用错误的工具，可能用错误参数调用正确的工具，可能调用的工具太少，也可能错误地处理工具响应。通过有选择地实现工具，并让工具名称反映任务的自然划分，你既能减少加载到 Agent 上下文中的工具及工具描述数量，也能把 Agentic 计算从 Agent 的上下文卸载回工具调用本身，从而降低 Agent 犯错的总体风险。

### 从工具返回有意义的上下文

同理，工具实现应注意只向 Agent 返回高信号信息。与灵活性相比，应优先考虑上下文相关性，并避免返回底层技术标识符（例如 `uuid`、`256px_image_url`、`mime_type`）。`name`、`image_url` 和 `file_type` 等字段更有可能直接帮助 Agent 决定后续操作并生成响应。

与晦涩的标识符相比，Agent 通常也更善于处理自然语言名称、术语或标识。我们发现，只需将任意的字母数字 UUID 解析为语义更明确、更易理解的语言（甚至只是改成从 0 开始的 ID 方案），就能减少幻觉，显著提高 Claude 在检索任务中的精确度。

在某些情况下，Agent 可能既需要与自然语言输出交互，也需要与技术标识符输出交互，哪怕后者仅用于触发后续工具调用（例如 `search_user(name=’jane’)` → `send_message(id=12345)`）。你可以在工具中公开一个简单的 `response_format` 枚举参数，同时支持这两种方式，让 Agent 控制工具返回 `“concise”`（简洁）还是 `“detailed”`（详细）响应（见下图）。

还可以添加更多格式来提供更大的灵活性，就像 GraphQL 一样，可以准确选择希望接收哪些信息。以下是一个用于控制工具响应详略程度的 ResponseFormat 枚举示例：

```
enum ResponseFormat { DETAILED = "detailed", CONCISE = "concise" }
```

以下是详细工具响应的示例（206 个 Token）：

以下是简洁工具响应的示例（72 个 Token）：

即使是工具响应的结构——例如 XML、JSON 或 Markdown——也会影响评估性能；不存在一体适用的方案。这是因为 LLM 是通过预测下一个 Token 进行训练的，因此面对与训练数据相似的格式时，往往表现更好。最优响应结构会随任务和 Agent 的不同而有很大差异。我们建议根据自己的评估结果选择最佳的响应结构。

### 优化工具响应的 Token 效率

优化上下文的质量很重要，但优化工具响应返回上下文的*数量*同样重要。

对于任何可能占用大量上下文的工具响应，我们建议结合实现分页、范围选择、过滤和/或截断功能，并设置合理的默认参数值。在 Claude Code 中，我们默认将工具响应限制为 25,000 个 Token。我们预计 Agent 的有效上下文长度会随时间增长，但对上下文高效工具的需求不会消失。

如果选择截断响应，请务必用有帮助的说明来引导 Agent。你可以直接鼓励 Agent 采用更节省 Token 的策略，例如在知识检索任务中执行多次小范围、有针对性的搜索，而不是进行一次宽泛搜索。同样，如果工具调用引发错误（例如输入验证失败），可以对错误响应进行提示词工程设计，清晰传达具体、可操作的改进方法，而不是只给出晦涩的错误码或堆栈跟踪信息。

以下是一个被截断的工具响应示例：

以下是一个无帮助的错误响应示例：

以下是一个有帮助的错误响应示例：

### 对工具描述进行提示词工程优化

下面介绍改进工具最有效的方法之一：对工具描述和规范进行提示词工程优化。由于这些内容会被加载到 Agent 的上下文中，它们可以共同引导 Agent 形成有效的工具调用行为。

编写工具描述和规范时，应设想如何向团队中的新员工介绍这个工具。思考你可能默认掌握、却未明说的上下文——例如专用查询格式、小众术语的定义，以及底层资源之间的关系——并将它们明确写出来。清晰描述预期的输入和输出，并通过严格的数据模型强制执行，以避免歧义。尤其是输入参数，名称应当明确无歧义：不要使用名为 `user` 的参数，而应尝试使用 `user_id`。

借助评估，你可以更有把握地衡量提示词工程的影响。即使只是微调工具描述，也可能带来显著改进。在我们对工具描述进行精准调整后，Claude Sonnet 3.5 在 [SWE-bench Verified](https://www.anthropic.com/engineering/swe-bench-sonnet) 评估中取得了当时最先进的成绩，大幅降低错误率并提高任务完成率。

有关工具定义的其他最佳实践，可以参阅我们的[开发者指南](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use#best-practices-for-tool-definitions)。如果正在为 Claude 构建工具，我们还建议了解工具如何被动态加载到 Claude 的[系统提示词](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use#tool-use-system-prompt)中。最后，如果你正在为 MCP 服务器编写工具，[工具注解](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)有助于声明哪些工具需要开放世界访问权限，或会进行破坏性更改。

## 展望未来

要为 Agent 构建高效工具，我们需要调整软件开发实践的方向，从可预测的确定性模式转向非确定性模式。

通过本文介绍的评估驱动型迭代流程，我们发现了成功工具所共有的规律：高效工具经过有意且清晰的定义，审慎使用 Agent 上下文，可以在多种工作流中相互组合，并让 Agent 能够凭直觉解决现实世界中的任务。

展望未来，我们预计 Agent 与世界交互的具体机制将不断演进——从 MCP 协议更新，到底层 LLM 本身的升级。通过采用系统化、评估驱动的方法改进 Agent 工具，我们可以确保随着 Agent 能力增强，它们所使用的工具也同步演进。

## 致谢

本文由 Ken Aizawa 撰写，并得到以下各团队同事的宝贵贡献：研究团队（Barry Zhang、Zachary Witten、Daniel Jiang、Sami Al-Sheikh、Matt Bell、Maggie Vo）、MCP 团队（Theodora Chu、John Welsh、David Soria Parra、Adam Jones）、产品工程团队（Santiago Seira）、市场团队（Molly Vorwerck）、设计团队（Drew Roper），以及应用 AI 团队（Christian Ryan、Alexander Bricken）。

[^1]: 此处不包括底层 LLM 本身的训练。
