# Peppa Memory Recall

## 目标

memory recall 用于让 Peppa 在回答前主动找回可能相关的长期信息，并把必要内容注入本轮对话上下文。

它的目标不是实现传统 RAG，也不是从大量文本中直接拼接相似片段，而是利用已经建立的 tag、graph、source、document 和未来的 skill，让记忆真正改变后续行为。

recall 过程可以让模型辅助生成联想词或判断候选价值，但被记录、展示和用于排序的内容必须是人类可读的结构化信息。第一版不使用向量距离作为相关性基础，也不把模型内部中间表示保存为记忆状态。

## 基本路径

第一版 recall 应保持简单、可解释：

```text
用户输入
  -> 提取或生成联想 tag
  -> 用 tag 查找相关 node / edge
  -> 沿 graph 扩展少量相邻信息
  -> 必要时展开 source trace / document / skill
  -> 组装 memory context
  -> 注入模型请求
```

tag 是 recall 的主要入口。它可以来自用户输入中的显式词，也可以由模型根据输入生成少量联想词。图谱负责把 tag 命中的内容组织成可解释路径，source 负责提供证据，document 负责提供精确细节，skill 负责提供可执行的工作方式。

## 返回内容分层

recall 结果不应只返回一串文本，而应按用途分层：

- 对话上下文：短、直接、和当前回答最相关的信息
- 证据来源：相关 source trace id、message id 或 source quote
- 外部文档：需要精确展开时可引用的文档路径或摘要
- skill 入口：当前任务应遵循的项目流程或协作方式

第一版注入 prompt 的内容应保守，优先短摘要和少量高置信结果。完整 trace 或文档只在必要时展开，避免把上下文塞满。

## 排序因素

第一版 recall 的排序可以先使用可解释信号，而不是 embedding：

- tag 命中数量
- tag 与 node / edge 的关联强度
- node / edge 的 mention count
- source 时间和最近更新
- category 或 retention 的重要程度
- 当前 conversation identity 是否相关

这些信号都应能在调试台展示，方便观察为什么某条记忆被召回。

如果未来引入新的排序信号，也必须能解释其含义，并能追溯到 tag、graph、source、document 或 skill 等可读数据。不可解释的分数不能成为召回结果的唯一理由。

## 调试可见性

每次 chat trace 中应记录 recall 过程：

- 输入中提取出的 tag
- 命中的 tag / node / edge
- 展开的 source / document / skill
- 最终注入 prompt 的 memory context
- 被丢弃的候选及简短原因

调试台现有的 `memory_hits` 位置可以作为第一版展示入口。

## 当前非目标

第一版 recall 暂不做：

- embedding 或向量数据库
- 大规模全文 RAG
- 复杂多跳图推理
- 自动生成或修改 skill
- 资源积分或经济系统
- 复杂主体视角建模

当前优先级是先让已保存的记忆能被找回并影响回答，形成最小闭环。
