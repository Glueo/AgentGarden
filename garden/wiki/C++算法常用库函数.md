---
id: cpp-algorithm-library-reference
kind: knowledge
status: stable
source_uris:
  - viking://user/gwen/sessions/20260820_131752_ccf700/history/archive_002
created: 2026-08-20
updated: 2026-08-20
topics: [algorithms, cpp, stl]
---

# C++ 算法常用库函数

只记录在刷题时实际遗忘、容易写错或值得复习的 API；每条附上最小用途和常见边界。

## `vector`

### 初始化

```cpp
vector<int> a = {x};
```

创建仅含 `x` 的动态数组。

### 末尾访问：`back`

```cpp
a.back();
```

返回末尾元素。调用前数组必须非空。

### 末尾追加：`push_back`

```cpp
a.push_back(x);
```

将 `x` 追加到数组末尾。

### 区间插入 / 拼接：`insert`

```cpp
a.insert(a.end(), b.begin(), b.end());
```

把 `b` 的全部元素追加到 `a` 末尾。参数依次为插入位置、区间起点、区间终点（左闭右开）。

- `a.end()` 表示插到 `a` 的最后。
- 若只插入单个元素，用 `a.insert(pos, x)`；末尾追加单个元素时优先使用 `push_back(x)`。
- 来源：[[算法复习#LeetCode 3069：将元素分配到两个数组中 I（2026-08-20）|LeetCode 3069 复盘]]。
