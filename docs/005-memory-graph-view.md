# Memory Graph View

## 目标

本版本增加一个只读的记忆图展示页，用来观察当前 SQLite 中已经保存的长期记忆结构。

展示内容包括：

- node：当前系统掌握的节点
- edge：节点之间的关系
- tag：node/edge 关联的可联想词语
- stats：节点、关系、标签、记忆抽取次数的基础统计

这一版不做记忆修改、不做召回、不做搜索过滤，重点是让开发者能清楚看到当前记忆图是否被正确写入。

## 后端接口

新增接口：

```text
GET /api/memory/graph
```

接口从 `memory_nodes`、`memory_edges`、`memory_tags`、`memory_node_tags`、`memory_edge_tags` 以及 observation 表中汇总当前记忆图。

返回结构包含：

- `nodes`
- `edges`
- `stats`

node 和 edge 中会附带：

- 已关联的 tags
- 已关联的 source trace ids
- mention count
- confidence
- created/updated time

该接口只读，不会写入或修改数据库。

## 前端入口

调试台顶部 banner 中，在 `Temperature` 控件前增加 `Memory` 按钮。

点击后进入 `/memory` 页面，展示当前系统所有记忆内容。页面中提供返回调试台的 `Console` 按钮。

## 图形化展示

前端使用 AntV G6 渲染记忆图。

当前展示策略：

- 不同 node type 使用不同颜色
- 多个 edge 同时显示，不合并
- 使用 G6 的 parallel edge transform 让同一组节点之间的多条边以曲线方式分开
- 鼠标悬停 node 或 edge 时显示摘要和 tags
- 右侧 inspector 展示 node type、top tags、当前选中节点或关系

## 多 edge 策略

当前版本会展示数据库中已有的所有 edge。

后续写入记忆时，可以限制两个 node 之间最多保留 3 个或 5 个 edge。超过上限时不再建立新的 edge，或者只记录 observation/source，而不扩展 graph 主体。

这个限制应该发生在写入 graph 的阶段，而不是展示阶段。展示页只忠实呈现当前数据库状态。

## 非目标

本版本暂不包含：

- 图上的编辑操作
- 删除或合并 node/edge
- 按 tag 搜索过滤
- 点击 source trace 展开原文
- 记忆召回流程
- 线上用户可见页面
