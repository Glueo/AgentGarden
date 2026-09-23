---
id: system-schema
kind: schema
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-09-23
topics: [agent-garden, schema]
---

# 笔记 Schema 与分类生长规则

稳定笔记使用最小 frontmatter：

```yaml
id: stable-slug-or-uuid
kind: knowledge | translation | hub | experience | policy | review
status: provisional | stable | superseded | review
source_uris: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
topics: []
```

## Resources 与 Wiki 的边界

`garden/resources/` 是本地材料归档区，保存外部原始文件快照和忠实的全文译文：

- 网页保存服务器返回的原始 HTML，扩展名使用 `.html`；
- 仓库文件保存对应文件的原始格式，例如 README 使用 `.md`；
- PDF、图片、数据集与其他附件保持下载时的文件格式和原始内容；
- 原始快照保持原始格式与内容，不加入翻译、摘要或 frontmatter；全文译文作为独立 `.zh-CN.md` 文件与原件并排存放，保留来源与译者说明，不改写原件。

`garden/wiki/` 是知识沉淀区，保存摘要、结构化笔记、个人学习结论与进度、Hub/MOC 和导航。由资源生成的 Wiki 页面在 `source_uris` 中记录原始 URL，并链接 `resources/` 中的原件或全文译文。

同一材料的原始快照与全文译文属于 `resources/`，可复用的提炼结论属于 `wiki/`。网页 HTML 原件始终保留，译文以独立文件归档。同步范围只包含 `wiki/`。

分类优先使用双向链接、`topics` 与 Hub/MOC。只有一个主题形成稳定内容簇时才创建主题目录；目录迁移必须更新链接、同步清单和本页的迁移记录。

## 迁移记录

- 2026-08-07：建立生命周期目录和最小 frontmatter；未预设学科树。
- 2026-09-20：明确 `resources/` 保存未经处理的源文件，`wiki/` 保存翻译与知识沉淀；网页源文件固定保存为原始 HTML。
- 2026-09-21：同步范围收敛为仅 `wiki/`；`resources/` 作为本地源文件归档，不再单向同步到 OpenViking，已索引的 `resources/` 内容从 OpenViking 移除。
- 2026-09-22：`wiki/` 建立总索引，并按算法、求职与实习、Agent 工程、语言学习四个稳定主题分目录；每个目录使用 `index.md` 声明收录与排除范围。
- 2026-09-23：全文译文与原件一同归档至 `resources/`；Wiki 和 OpenViking 仅保留知识提炼、学习进度与导航。

