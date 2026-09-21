---
id: 04-langgraph-readme-zh-cn
kind: translation
status: stable
source_uris:
  - https://github.com/langchain-ai/langgraph
created: 2026-09-20
updated: 2026-09-20
topics: [agents, langgraph, orchestration, recommended-reading, translation]
language: zh-CN
resource_path: resources/agent-guide-recommended-reading/04-langgraph-README.md
---

> 中文翻译；原 README 归 LangChain Inc. 及贡献者所有。抓取与翻译日期：2026-09-20。
>
> 源文件：[[../../resources/agent-guide-recommended-reading/04-langgraph-README.md|原始 README]]

<div align="center">
  <a href="https://www.langchain.com/langgraph">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/images/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset=".github/images/logo-light.svg">
      <img alt="LangGraph Logo" src=".github/images/logo-dark.svg" width="50%">
    </picture>
  </a>
</div>

<div align="center">
  <h3>用于构建有状态智能体的底层编排框架。</h3>
</div>

<div align="center">
  <a href="https://opensource.org/licenses/MIT" target="_blank"><img src="https://img.shields.io/pypi/l/langgraph" alt="PyPI - License"></a>
  <a href="https://pypistats.org/packages/langgraph" target="_blank"><img src="https://img.shields.io/pepy/dt/langgraph" alt="PyPI - Downloads"></a>
  <a href="https://pypi.org/project/langgraph/" target="_blank"><img src="https://img.shields.io/pypi/v/langgraph.svg?label=%20" alt="Version"></a>
  <a href="https://x.com/langchain_oss" target="_blank"><img src="https://img.shields.io/twitter/url/https/twitter.com/langchain_oss.svg?style=social&label=Follow%20%40LangChain" alt="Twitter / X"></a>
</div>

<br>

LangGraph 深受塑造智能体未来的众多公司信赖，包括 Klarna、Replit、Elastic 等。它是一个底层编排框架，用于构建、管理和部署长时间运行的有状态智能体。

```bash
pip install -U langgraph
```

> [!TIP]
> 如果你希望快速构建智能体，不妨了解 **[Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)**——这是一个构建于 LangGraph 之上的高层软件包，适用于能够制定计划、使用子智能体，并借助文件系统完成复杂任务的智能体。

如需功能对等的 JS/TS 库，请参阅 [LangGraph.js](https://github.com/langchain-ai/langgraphjs) 和 [JS 文档](https://docs.langchain.com/oss/javascript/langgraph/overview)。

## 为什么使用 LangGraph？

LangGraph 为*任何*长时间运行的有状态工作流或智能体提供底层支撑基础设施：

- **[持久化执行](https://docs.langchain.com/oss/python/langgraph/durable-execution)**——构建能够从故障中恢复并可长时间运行的智能体；它们会自动从中断之处准确恢复执行。
- **[人在回路](https://docs.langchain.com/oss/python/langgraph/interrupts)**——可在执行过程中的任意时刻检查和修改智能体状态，从而无缝引入人工监督。
- **[全面的记忆机制](https://docs.langchain.com/oss/python/langgraph/memory)**——同时利用支持持续推理的短期工作记忆和跨会话的长期持久记忆，打造真正有状态的智能体。
- **[使用 LangSmith 调试](https://www.langchain.com/langsmith)**——借助可追踪执行路径、捕获状态转换并提供详细运行时指标的可视化工具，深入洞察复杂的智能体行为。
- **[生产就绪的部署](https://docs.langchain.com/langsmith/deployments)**——使用专为应对有状态、长时间运行工作流的独特挑战而设计的可扩展基础设施，放心部署复杂的智能体系统。

> [!TIP]
> 如需开发、调试和部署 AI 智能体及 LLM 应用，请参阅 [LangSmith](https://docs.langchain.com/langsmith/home)。

## LangGraph 生态系统

LangGraph 既可以独立使用，也能与任何 LangChain 产品无缝集成，为开发者提供一整套智能体构建工具。

要提升 LLM 应用开发体验，可将 LangGraph 与以下产品搭配使用：

- [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)——构建能够制定计划、使用子智能体，并借助文件系统完成复杂任务的智能体。
- [LangChain](https://docs.langchain.com/oss/python/langchain/overview)——提供集成和可组合组件，简化 LLM 应用开发。
- [LangSmith](https://www.langchain.com/langsmith)——有助于智能体评估和可观测性。调试表现不佳的 LLM 应用运行过程、评估智能体轨迹、洞察生产环境中的运行情况，并持续提升性能。
- [LangSmith Deployment](https://docs.langchain.com/langsmith/deployments)——借助专为长时间运行的有状态工作流打造的部署平台，轻松部署和扩展智能体。在团队内发现、复用、配置和共享智能体，并通过 [LangSmith Studio](https://docs.langchain.com/langsmith/studio) 中的可视化原型设计快速迭代。

---

## 文档

- [docs.langchain.com](https://docs.langchain.com/oss/python/langgraph/overview)——完整文档，包括概念概述和指南
- [reference.langchain.com/python/langgraph](https://reference.langchain.com/python/langgraph)——LangGraph 软件包的 API 参考文档
- [LangGraph 快速入门](https://docs.langchain.com/oss/python/langgraph/quickstart)——开始使用 LangGraph 进行构建
- [Chat LangChain](https://chat.langchain.com/)——与 LangChain 文档对话，获取问题的答案

**讨论**：访问 [LangChain Forum](https://forum.langchain.com)，与社区成员交流并分享你的技术问题、想法和反馈。

## 其他资源

- **[指南](https://docs.langchain.com/oss/python/learn)**——针对流式处理、添加记忆与持久化以及设计模式（例如分支、子图等）等主题，提供可快速采用的实用代码片段。
- **[LangChain Academy](https://academy.langchain.com/courses/intro-to-langgraph)**——通过我们免费且结构清晰的课程学习 LangGraph 基础知识。
- **[案例研究](https://www.langchain.com/built-with-langgraph)**——了解行业领军企业如何使用 LangGraph 大规模交付 AI 应用。
- [贡献指南](https://docs.langchain.com/oss/python/contributing/overview)——了解如何为 LangChain 项目作出贡献，并寻找适合首次参与的问题。
- [行为准则](https://github.com/langchain-ai/langchain/?tab=coc-ov-file)——我们的社区准则和参与规范。

---

## 致谢

LangGraph 的灵感来自 [Pregel](https://research.google/pubs/pub37252/) 和 [Apache Beam](https://beam.apache.org/)。其公共接口借鉴了 [NetworkX](https://networkx.org/documentation/latest/) 的设计。LangGraph 由 LangChain 的创建者 LangChain Inc. 打造，但无需搭配 LangChain 即可使用。
