# Peppa Memory Requirements

## 目标

Peppa 的记忆系统不使用传统 RAG，不使用 embedding，不依赖本地模型或向量数据库。

记忆系统的目标是构建一个人类可读、可解释、可调试的联想记忆图。这个记忆图用明确的词语 tag 代替不可解释的高维向量，用 node 表示事物和概念，用 edge 表示 node 之间的有限类型关系，用 source 保留原始证据。

核心原则：

```text
node / edge 保持结构稳定
tag 保持联想丰富
source 保持细节完整
document 保持工程化和精确内容
```

## 非目标

当前记忆系统不做：

- embedding
- 本地向量生成模型
- 向量数据库
- 传统 RAG
- 把所有对话内容无差别写入长期记忆
- 把项目工程细节全部塞进语义记忆图
- 让模型自由生成无限多 edge 类型

## 记忆和文档的区别

Peppa 的长期信息分为两类：

```text
脑子里的记忆：轻量、可联想、适合召回的语义图
笔记本里的记忆：复杂、精确、内容多的文档或工程记录
```

项目规则、技术决策、当前任务状态、事实纠正等内容，在没有进入长期记忆前，可以看作工程化记忆。这类内容通常不应该完整记在语义记忆图中，而应该记录到 Markdown 文档、设计文档、任务文档或其他外部化载体中。

语义记忆图只需要记住：

- 有这个项目或任务
- 项目大概是什么
- 哪些 tag 可以联想到它
- 它关联哪些文档、trace 或 source
- 用户对于项目协作的高层偏好或长期原则

例如：

```text
项目细节：config.toml 放根目录、state/peppa.sqlite3 不能随便删、调试台使用深色主题
```

不应该全部塞进长期语义记忆。更合适的是：

```text
node: Peppa
tags: Peppa, AI agent, 记忆系统, 调试台, 项目架构
doc_link: docs/001-technical-architecture.md
```

当真正需要细节时，再从 Peppa 这个 node 关联到项目文档展开。

## 处理流程

每轮对话内容进入记忆系统前，应先进行分类和去向判断。

推荐流程：

```text
上下文文本
  -> 分类
  -> 判断是否值得保留
  -> 判断保留位置：语义记忆 / 外部文档 / 临时 trace / 不保留
  -> 如果进入语义记忆，提取 tags / nodes / edges / sources
  -> 如果进入外部文档，语义记忆只保留项目或主题索引入口
```

这意味着 memory extraction 的输出不应只包含 `tags/nodes/edges`，还应该包含分类和去向判断。

## 内容分类

测试记忆提取时，应覆盖以下类型。

### 无需记忆的寒暄

例如：

```text
你好
早上好
见到你很高兴
谢谢
哈哈
```

通常不进入长期记忆。

### 一次性知识问答

例如：

```text
红烧肉怎么做？
月亮距离地球多远？
光速是多少？
光速为什么恒定？
纽约明天天气怎么样？
```

这类问题通常不进入长期记忆。除非连续多次出现，体现出用户的稳定兴趣、学习目标或项目需求。

### 用户自我介绍

例如：

```text
我是程序员
我住在上海
我养了一条狗
我有一个 6 岁的孩子
我英语听力比较弱
```

这类内容通常适合进入长期语义记忆。

### 用户偏好

例如：

```text
我希望开发前先讨论方案
我喜欢代码清晰简单
我不喜欢一上来就大改
回答我时尽量用中文
```

这类内容通常适合进入长期语义记忆，且后续召回优先级较高。

### 项目规则和工程约定

例如：

```text
config.toml 放根目录，不提交 git
state/peppa.sqlite3 是 agent 身份数据，不能随便删
文档文件名用英文，正文用中文
开发前先把共识写进 docs
```

这类内容通常应优先写入项目文档。语义记忆只保留项目、规则主题和文档索引。

### 技术决策

例如：

```text
Peppa 使用 Python + FastAPI
前端用 React + Vite
不使用本地模型
不使用 embedding
记忆系统使用 tag/node/edge 的语义图
```

这类内容通常应优先进入文档。语义记忆可记录高层项目方向和关联文档。

### 当前任务状态

例如：

```text
我们刚刚实现了 temperature 控件
下一步要测试 memory tool call schema
tool_calls 同时返回 content 不稳定，所以放弃这条路
```

这类内容通常是阶段性工程记录，适合进入文档、任务记录或 trace。只有高层结论和项目状态索引适合进入语义记忆。

### 事实纠正

例如：

```text
我说的是文件名用英文，不是 Markdown 标题用英文
我不是让你现在改代码，只是讨论
这个按钮不是没用，是为了未来会话上下文边界
```

如果是用户长期偏好或协作原则，应进入语义记忆。如果是项目细节纠正，应优先进入文档，并在语义记忆中保留索引。

### 人际关系、家庭、宠物

例如：

```text
我有一条狗，叫毛毛
我女儿今年上小学
我父母住在杭州
我朋友小李是设计师
```

这类内容通常适合进入长期语义记忆，但要避免过度推断。

### 计划、目标、愿望

例如：

```text
我想开发一个长期运行的 AI agent
我计划以后支持 Telegram
我希望最终能 curl install
我想提高英语口语
```

这类内容通常适合进入长期语义记忆。

### 情绪和状态

例如：

```text
我今天有点累
这个 bug 让我很烦
我最近工作压力很大
我对复杂工具链很抗拒
```

短期情绪通常不进入长期记忆。长期状态、稳定倾向或明确偏好可以进入语义记忆。

### 价值观和原则

例如：

```text
我更看重稳定性而不是炫技
我希望工具可解释
我不喜欢黑盒系统
简单可靠比复杂强大更重要
```

这类内容通常适合进入长期语义记忆。

### 创作设定和虚构上下文

例如：

```text
这个角色叫林安，是一个失忆的医生
游戏世界里魔法来自星尘
主角小时候住在海边
```

这类内容可以进入项目或创作上下文，但必须标记为虚构或创作设定，不能当作现实事实。

### 临时指令

例如：

```text
这次回答短一点
这段代码先别格式化
今天先不跑测试
这轮先不要写代码
```

通常不进入长期记忆。只有反复出现并体现稳定偏好时，才上升为长期记忆。

### 安全、隐私、凭证相关

例如：

```text
我的 API key 是 ...
不要把 key 写进示例配置
真实 config.toml 要 gitignore
```

不应记住具体 secret。可以记住安全规则和处理原则。

### 矛盾、更新和覆盖

例如：

```text
之前说用 ~/.peppa-agent，现在改成项目根目录
我放弃 tool_calls 同时返回 content 的方案
不要再按上一个方向做了
```

这类内容很重要。系统应能识别新内容覆盖旧内容，并建立 `supersedes` 或类似关系。

## 混合会话

真实会话往往混合多个类型。测试集必须包含混合场景。

例如：

```text
你好，最近我在给我女儿准备小学考试，顺便问一下月亮距离地球多远？另外 Peppa 的记忆系统不要用 embedding。
```

这段中包含：

```text
寒暄：你好 -> 不记
个人/家庭：女儿、小学考试 -> 可能记
百科问题：月亮距离 -> 不记
项目技术决策：不要用 embedding -> 写入文档，语义记忆保留项目索引
```

模型不应该整段都记，也不应该整段都丢弃。

## Tag

tag 是 Peppa 记忆系统中替代 embedding 的人类可读联想入口。

tag 不只是关键词，也不是简单分词结果。tag 可以包括：

- 原文词
- 近义词
- 相关词
- 上位概念
- 抽象概念
- 情绪联想
- 场景联想
- 价值判断
- 特色动词组合

tag 的目标是帮助未来回忆，而不是表达事实。

例如：

```text
我吃了我爸爸做的饭
```

可能的 tag：

```text
我
爸爸
吃饭
家庭
家常菜
幸福
温暖
陪伴
亲情
```

这些 tag 让未来可以通过 `吃饭` 联想到 `幸福`，通过 `幸福` 联想到某次旅行或家庭事件。记忆和回忆之间建立联系的不是高维数字，而是明确的人类词语。

建议 tag 类型包括：

```text
literal        原文出现
synonym        近义或同义
hypernym       上位概念
related        相关概念
emotion        情绪联想
scene          场景联想
value          价值或原则
action_phrase 特色动词组合
```

## Node

node 表示记忆图中的对象、实体、概念或活动。

node 通常应该是名词或名词短语，可以稍长，但不应该是完整句子。

好的 node：

```text
我
毛毛
Peppa
记忆系统
骑马
红烧肉
上海天气
```

不好的 node：

```text
我在草地上骑马
我希望开发前先讨论方案
Peppa 的数据库不能随便删除
```

这些更适合作为 edge、tag、source、偏好或文档内容表达。

如果遇到：

```text
我在草地上骑马
```

更合适的拆分是：

```text
node: 我
node: 骑马
node: 草地
edge: 我 participates_in 骑马
edge: 骑马 located_in 草地
tag: 骑马, 户外, 运动
source: 我在草地上骑马
```

## Edge

edge 表示 node 之间的关系。edge 可以是单向的，也可以是双向的。

这里的单向不表示另一个方向没有意义，而是两个方向的关系名称或语义相反。

例如：

```text
我 -> 毛毛: owns / cares_for
毛毛 -> 我: owned_by / cared_by
```

```text
我 -> 包子: parent_of
包子 -> 我: child_of
```

朋友关系是双向的：

```text
我 <-> 包子: friend_of
```

两个 node 之间可以有多个 edge，因为它们可能存在多种关系。

例如：

```text
我 -> 包子: parent_of
我 <-> 包子: friend_of
我 -> 包子: works_with
```

## Edge 类型约束

edge 的关系类型不能让模型自由生成。自由生成会导致大量相近关系重复出现，例如：

```text
骑
骑乘
参加骑马
体验骑马
在草地上骑
```

这些本质上可能是同一类关系，却会污染图结构。

因此 edge 的 `relation_type` 应该是有限集合。数量可以扩充到 30 个左右，但不应超过 50 个。

具体动作、场景、情绪和细节应放入 tag 或 source 中，而不是作为 edge 类型。

例如：

```text
我骑马
```

不应该记录为：

```text
relation_type: 骑
```

而应该记录为：

```text
source: 我
target: 马
relation_type: acts_on
tags: 骑马, 骑乘, 户外活动
source_quote: 我骑马
```

这样图结构保持稳定，细节仍然可以从 tag 和 source 中找回。

## Edge 类型候选

第一版 edge 类型应保持有限、稳定、可解释。候选类型如下，后续可以调整，但总量不应超过 50。

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

说明：

- `related_to` 是保底泛关联，应尽量少用。
- `friend_of` 是双向关系。
- `parent_of` 和 `child_of` 表示相反方向，但实际写入时可以考虑规范化为一种方向，以便去重。
- `acts_on` 表示 source 对 target 执行动作，具体动作写入 tags。
- `supersedes` 表示新记忆或新决策覆盖旧内容。
- `documents` 可用于语义记忆 node 关联到外部文档。

## Source

source 是 node 和 edge 的原始证据。

source 应保留：

- 原始对话片段
- trace id
- message id
- 时间
- 可能的 source_quote

node 和 edge 不需要承载全部细节。细节应通过 source 追溯。

例如：

```text
source_quote: 我昨天在草地上骑了一匹马，感觉很开心
```

图里可以只记录：

```text
node: 我
node: 马
edge: 我 acts_on 马
tags: 骑马, 户外, 开心
```

更多细节从 source 找。

## Document

document 用于承载复杂、精确、内容多的长期信息，尤其是工程化记忆。

适合进入 document 的内容：

- 项目架构
- 技术决策细节
- 开发约定
- 任务状态
- 设计文档
- 流程文档
- prompt 说明
- tool schema 说明

语义记忆图只需要通过 node 和 edge 关联到 document。

例如：

```text
node: Peppa
edge: Peppa documents docs/004-memory-requirements.md
tags: 记忆系统, 人类可读联想记忆图
```

## 推荐提取输出结构

未来 memory extraction 的输出不应只包含 `tags/nodes/edges`。建议结构包括：

```json
{
  "segments": [
    {
      "text": "原始片段",
      "category": "user_preference",
      "retention": "semantic_memory",
      "reason": "这是用户的长期协作偏好"
    }
  ],
  "memory_graph": {
    "tags": [],
    "nodes": [],
    "edges": []
  },
  "document_suggestions": [
    {
      "project": "Peppa",
      "document_type": "architecture",
      "summary": "建议写入项目架构文档的内容",
      "source_quote": "原始证据"
    }
  ]
}
```

`retention` 可选值建议包括：

```text
semantic_memory
external_document
trace_only
ignore
```

## 测试重点

当前阶段的测试重点是验证大模型是否能稳定、合理地完成以下任务：

- 对输入内容分类
- 判断是否需要保留
- 判断进入语义记忆、外部文档、trace 还是忽略
- 提取合理的 tag
- 提取名词或名词短语 node
- 使用有限 edge 类型建立关系
- 不把工程细节全部塞进语义记忆
- 不把寒暄和一次性百科问答错误记忆
- 不记录 secret
- 不编造 source_quote

## 当前实现边界

当前项目中已经有 memory tool-call 测试入口，但它只是实验工具。

当前尚未实现：

- 正式记忆图 schema
- tag 写入
- node 写入
- edge 写入
- source 链接
- document 写入建议处理
- recall
- memory context 注入
- 去重和合并
- supersedes 处理

下一步应先调试和稳定 memory extraction 的 prompt 与 tool schema，再进入正式写入和召回实现。
