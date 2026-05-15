---
name: memory-extraction
description: Extract Peppa long-term memory candidates from conversations using a human-readable associative memory graph with tags, nodes, edges, sources, and document-routing decisions.
---

# Memory Extraction

你负责从对话中提取 Peppa 的长期记忆候选。目标不是保存所有内容，而是判断哪些内容值得保留、应该保留在哪里，以及如何用人类可读的联想记忆图表达。

## 核心原则

Peppa 不使用 embedding、不使用向量数据库、不使用传统 RAG。

记忆结构应遵循：

```text
node / edge 保持结构稳定
tag 保持联想丰富
source 保持细节完整
document 保持工程化和精确内容
```

先分类，再判断去向，最后才提取图结构：

```text
上下文文本
  -> 分类
  -> 判断是否值得保留
  -> 判断保留位置：semantic_memory / external_document / trace_only / ignore
  -> 如果进入 semantic_memory，提取 tags / nodes / edges / sources
  -> 如果进入 external_document，语义记忆只保留项目或主题索引入口
```

## 内容去向

通常进入 `semantic_memory`：

- 用户自我介绍
- 用户长期偏好
- 稳定的人际关系、家庭、宠物信息
- 长期目标、计划、愿望
- 价值观和原则
- 重要纠正中体现出的长期偏好

通常进入 `external_document`：

- 项目规则和工程约定
- 技术决策细节
- 当前任务状态
- 设计文档内容
- 需要精确保存的大段信息

通常进入 `trace_only` 或 `ignore`：

- 寒暄
- 一次性百科问答
- 临时指令
- 短期情绪
- 不值得长期保存的普通闲聊

安全相关内容不要保存 secret 原文。可以保存安全规则，例如“不要把 API key 写进示例配置”。

## Tag 规则

tag 是替代 embedding 的人类可读联想入口。tag 的目标是帮助未来回忆，而不是表达事实。

tag 可以包括：

- 原文词
- 近义词
- 相关词
- 上位概念
- 抽象概念
- 情绪联想
- 场景联想
- 价值判断
- 特色动词组合

例如“我吃了我爸爸做的饭”可以产生：

```text
爸爸, 吃饭, 家庭, 家常菜, 幸福, 温暖, 陪伴, 亲情
```

## Node 规则

node 表示对象、实体、概念或活动。node 通常应该是名词或名词短语，可以稍长，但不应该是完整句子。

好的 node：

```text
我
毛毛
Peppa
记忆系统
骑马
红烧肉
```

不好的 node：

```text
我在草地上骑马
我希望开发前先讨论方案
Peppa 的数据库不能随便删除
```

如果用户说“我在草地上骑马”，更合适的是：

```text
node: 我
node: 骑马
node: 草地
edge: 我 participates_in 骑马
edge: 骑马 located_in 草地
tag: 骑马, 户外, 运动
```

## Edge 规则

edge 表示 node 之间的关系。两个 node 之间可以有多条 edge，因为它们可能存在多种关系。

edge 类型必须使用有限集合。不要自由创造 relation_type。具体动作、场景、情绪和细节放进 tags 或 source_quote。

例如“我骑马”不应该使用 `relation_type: 骑`，而应该是：

```text
source: 我
target: 马
relation_type: acts_on
tags: 骑马, 骑乘, 户外活动
source_quote: 我骑马
```

优先使用以下 relation_type：

```text
related_to
is_a
part_of
has_part
owns
owned_by
cares_for
cared_by
parent_of
child_of
friend_of
works_on
works_with
created_by
creates
uses
prefers
avoids
decided
requires
causes
located_in
participates_in
acts_on
supports
depends_on
mentions
documents
supersedes
conflicts_with
```

`related_to` 是保底泛关联，应尽量少用。`friend_of` 是双向关系。`acts_on` 表示 source 对 target 执行动作，具体动作写入 tags。`documents` 用于语义记忆 node 关联外部文档。`supersedes` 表示新记忆或新决策覆盖旧内容。

## 输出要求

如果提供了 `record_memory_graph_update` 工具，并且 provider 支持工具调用，请通过该工具返回结构化结果。

工具参数应包含：

```text
segments: 对输入内容的分类、保留位置、理由和置信度
memory_graph.tags: 可用于未来回忆的显式词和联想词
memory_graph.nodes: 适合进入语义记忆图的对象、实体、概念或活动
memory_graph.edges: node 之间的有限类型关系，字段名使用 relation_type
document_suggestions: 适合进入外部文档的大段、精确或工程化内容
```

提取时要保守：

- 不要把整段内容都记住
- 不要把寒暄和一次性百科问答错误写入长期记忆
- 不要把工程细节全部塞进语义记忆图
- 不要编造 source_quote
- 不确定时降低 confidence
- 如果某类内容不存在，返回空数组

优先保证 tags、nodes、edges 的质量，而不是数量。
