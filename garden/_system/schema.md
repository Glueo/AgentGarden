---
id: system-schema
kind: schema
status: stable
source_uris: []
created: 2026-08-07
updated: 2026-08-07
topics: [agent-garden, schema]
---

# 笔记 Schema 与分类生长规则

稳定笔记使用最小 frontmatter：

```yaml
id: stable-slug-or-uuid
kind: knowledge | source | hub | experience | policy | review
status: provisional | stable | superseded | review
source_uris: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
topics: []
```

分类优先使用双向链接、`topics` 与 Hub/MOC。只有一个主题形成稳定内容簇时才创建主题目录；目录迁移必须更新链接、同步清单和本页的迁移记录。

## 迁移记录

- 2026-08-07：建立生命周期目录和最小 frontmatter；未预设学科树。

