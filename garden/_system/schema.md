---
id: system-schema
kind: schema
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-09-20
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

`garden/resources/` 是源文件归档区，只保存从外部取得的原始文件快照：

- 网页保存服务器返回的原始 HTML，扩展名使用 `.html`；
- 仓库文件保存对应文件的原始格式，例如 README 使用 `.md`；
- PDF、图片、数据集与其他附件保持下载时的文件格式和原始内容；
- 源文件不得加入翻译、摘要、frontmatter、说明性页眉或其他改写内容。

`garden/wiki/` 是知识处理区，保存翻译、摘要、结构化笔记、知识沉淀、Hub/MOC 与人工整理结果。由资源生成的 Wiki 页面必须在 `source_uris` 中记录原始 URL，并通过 `resource_path` 或正文链接指向 `resources/` 中的源文件。

同一材料的原始快照属于 `resources/`，翻译或沉淀结果属于 `wiki/`。不得用提取后的 Markdown、清洗文本或译文代替网页 HTML 源文件。

分类优先使用双向链接、`topics` 与 Hub/MOC。只有一个主题形成稳定内容簇时才创建主题目录；目录迁移必须更新链接、同步清单和本页的迁移记录。

## 迁移记录

- 2026-08-07：建立生命周期目录和最小 frontmatter；未预设学科树。
- 2026-09-20：明确 `resources/` 保存未经处理的源文件，`wiki/` 保存翻译与知识沉淀；网页源文件固定保存为原始 HTML。

