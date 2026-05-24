# Peppa 后续开发计划建议

## 背景

截至当前阶段，Peppa 已经不再只是第一版本地调试台骨架。

原计划中的最小调试闭环已经完成，并且项目已经进入记忆系统主线：

- CLI、FastAPI、本地 Web 调试台、模型切换和 trace 记录已经具备
- memory extraction 已经可以从对话 trace 中抽取长期记忆
- memory graph 已经可以在调试台中展示
- conversation identity 已经可以绑定当前入口对话对象
- recall 已经进入普通 chat 请求路径，并会把召回结果注入 prompt
- topic boundary tool 已经用于判断话题切换
- auto memory extraction 已经开始在后台自动触发

因此，后续开发的重点不应继续横向扩展入口或工具数量，而应优先把核心记忆链路做成稳定、可观察、可维护的闭环。

核心目标是：

```text
记住
  -> 看见
  -> 召回
  -> 影响回答
  -> 被人修正和维护
```

每个后续功能都应该有从实现到展示的最小闭环，并且能够为未来目标铺路。

## 当前进度判断

### 已完成或基本完成

- Python 项目结构、配置文件和本地状态目录约定
- CLI 命令和 FastAPI 服务
- React/Vite 深色调试台
- 多模型配置和模型切换
- SQLite conversations、messages、traces
- prompt、request、response 原始调试展示
- memory extraction tool schema 和抽取流程
- memory graph 持久化
- memory graph 页面
- node / edge 删除
- conversation identity 手动绑定
- tag-based memory recall 第一版
- recall context 注入普通 chat
- topic boundary tool
- 自动记忆抽取状态

### 已有能力但展示不足

recall 已经进入 agent core，但前端还缺少专门的 recall inspector。

目前开发者可以在 trace 的原始 JSON 中看到 `request_payload._peppa.memory_recall`，但这还不够直观。后续需要把以下信息清晰展示出来：

- 本轮输入命中了哪些 tag
- 哪些 node / edge 被召回
- 每条召回结果的原因和分数
- 哪些 evidence/source trace 支撑这条记忆
- 最终注入 prompt 的 memory context 是什么
- 哪些候选被丢弃，原因是什么

这一步会让“记忆是否真的影响回答”变得可观察。

### 明显缺口

`document_suggestions` 已经进入 schema 和抽取结果，但还没有形成闭环。

当前缺少：

- document suggestions 的前端列表
- 接受、忽略、延后处理状态
- 写入 Markdown 文档或文档 inbox 的流程
- 从语义记忆图指向外部文档的索引关系

这意味着“精确外置记忆”还只是被抽取出来，没有真正落地。

### 维护能力不足

当前 memory graph 支持删除 node / edge，但还缺少基础维护能力：

- node 合并
- tag 合并
- node 摘要编辑
- alias 或 normalized title 修正
- 冲突、覆盖和 supersedes 的人工处理

随着自动抽取频率上升，如果没有维护入口，图谱会逐渐变脏，recall 质量也会下降。

### 自动抽取仍偏黑箱

auto memory extraction 已经运行，但对开发者来说还不够透明。

后续需要展示：

- 当前是否有 pending traces
- 上次自动抽取处理到哪条 trace
- 上次触发原因是 turn count 还是 topic boundary
- 最近一次自动抽取是否成功
- 失败时的 error 和 extraction trace
- 手动立即补跑入口

这会让后台行为可调试，也为未来长期运行和多入口接入铺路。

## 后续开发原则

后续所有功能都应遵循以下原则：

- 每个功能都必须有从后端实现到前端展示的最小闭环
- 优先增强 agent 行为的可观察性，而不是只增加数据结构
- 优先让记忆真正影响回答，而不是继续扩展记忆本体
- 优先做人工可控维护，再考虑自动维护
- 精确、工程化、可反复查阅的内容应进入文档层，而不是全部塞进语义图
- skill 化记忆应等模式稳定后再沉淀，不要过早自动生成 skill
- 所有长期状态都应保持人类可读、可审计、可迁移
- 不引入 embedding、向量数据库或不可解释的长期相关性基础

## 建议优先级

### 1. Recall Inspector

这是下一步最值得优先做的功能。

最小闭环：

```text
用户发送消息
  -> 后端执行 recall
  -> trace 记录 recall 详情
  -> 前端展示 matched tags / nodes / edges / evidence / context text
  -> 开发者判断回答是否正确使用了记忆
```

建议实现内容：

- 在调试台中新增 `Recall` 面板或 trace 子面板
- 从 `request_payload._peppa.memory_recall` 中读取召回结果
- 分区展示 matched tags、entities、relationships、evidence 和 context text
- 在 chat trace 中突出显示本轮是否注入了 memory context
- 支持从 evidence 的 `source_trace_id` 打开原始 trace

为未来铺路：

- 后续可以基于这个面板调试 recall 排序
- 可以验证 topic boundary 是否改善召回范围
- 可以接入 document 和 skill 召回入口
- 可以支撑“为什么 Peppa 这样回答”的解释能力

### 2. Source Trace Drilldown

recall、memory graph 和 document suggestions 都依赖 source trace。应尽快让 source 可点击、可审计。

最小闭环：

```text
在 memory graph 或 recall evidence 中点击 source_trace_id
  -> 打开对应 trace
  -> 查看原始用户输入、assistant 回复、prompt/request/response
```

建议实现内容：

- 后端已有 `GET /api/traces/{trace_id}`，前端补齐使用入口
- Memory 页面 node / edge inspector 中展示 source trace 列表
- Recall Inspector 的 evidence 支持点击 source trace
- 打开后复用现有 JSON modal 或新建 trace detail drawer

为未来铺路：

- 所有长期记忆都可以回溯到原始经历
- 方便判断抽取错误是模型问题、schema 问题还是 source 本身含糊
- 后续 document suggestions 和 skill candidates 也可以复用这一能力

### 3. Memory Maintenance v1

在自动抽取继续扩大图谱前，需要先提供人工维护入口。

最小闭环：

```text
开发者在 Memory 页面选择重复或错误记忆
  -> 执行合并、编辑或删除
  -> 图谱刷新
  -> recall preview 反映维护后的结果
```

建议第一版只做人工操作：

- node merge
- tag merge
- node summary edit
- node title 或 alias 修正
- 保留 source observations，不丢失证据

暂时不建议做复杂自动合并。自动合并需要更强的冲突处理和可回滚机制，应该等人工维护流程稳定后再做。

为未来铺路：

- 保持图谱质量
- 降低 recall 噪声
- 为后续自动合并提供真实操作样本
- 为 supersedes、conflict resolution 和 memory evolution 打基础

### 4. Document Suggestions / Document Inbox

这是补齐“精确外置记忆层”的关键功能。

最小闭环：

```text
memory extraction 产生 document_suggestions
  -> 前端展示待处理建议
  -> 开发者接受或忽略
  -> 接受后写入 Markdown 文档或文档 inbox
  -> suggestion 状态更新
```

建议实现内容：

- 新增 document suggestions API
- 前端新增 `Documents` 或 `Inbox` 页面
- 展示 project、document_type、title、summary、source_quote、tags、confidence、reason
- 支持 `accept`、`ignore`、`defer`
- 第一版可以先写入 `docs/memory-inbox.md` 或 `docs/project-notes.md`
- 写入内容必须保留 source trace id，方便回溯

为未来铺路：

- 项目规则、技术决策、任务状态不必塞进语义图
- 后续 recall 可以从 node 关联到文档
- 后续 skill candidate 可以从稳定文档和真实案例中沉淀
- 支撑长期项目知识的精确维护

### 5. Auto Memory Status

自动抽取已经存在，但需要可视化和手动干预入口。

最小闭环：

```text
普通 chat 产生 trace
  -> 自动抽取根据 turn count 或 topic boundary 触发
  -> 前端展示自动抽取状态、触发原因和结果
  -> 失败时可定位 extraction trace
  -> 必要时可手动 run now
```

建议实现内容：

- 新增自动抽取状态 API
- 展示 `memory_auto_extraction_state`
- 展示 pending trace 数量
- 展示最近一次 extraction trace id、状态和 error
- 在 trace list 中更清晰标记已被自动抽取的普通 trace
- 提供手动触发自动抽取的按钮

为未来铺路：

- 长期运行时可观察后台行为
- 为 Telegram 和其他入口接入后的自动记忆流程做准备
- 为后续定时任务系统提供状态模型

### 6. Conversation / Topic 管理

这一步重要，但不应排在 recall 和维护之前。

最小闭环：

```text
开发者新建或切换 conversation
  -> trace 按 conversation 展示
  -> topic boundary 作为分段标记展示
  -> recall 只使用当前 conversation/topic 范围
```

建议实现内容：

- conversation list API
- 前端 conversation selector
- 新建 conversation 按钮
- trace list 支持按 conversation 过滤
- topic boundary 在 trace list 中作为分段标记展示

为未来铺路：

- 支持 Telegram、多入口、多上下文
- 支持不同入口绑定不同 conversation identity
- 改善 recall 的上下文范围控制

## 暂不建议优先做的方向

以下方向可以保留在长期目标中，但不适合作为当前下一步：

- Telegram 接入
- 复杂 tools 系统
- 自动 skill 生成
- resource / credit / economy system
- 复杂主体视角建模
- embedding 或向量数据库
- 大规模全文 RAG
- 多用户账号系统
- 复杂定时任务系统

原因是当前最重要的问题不是入口数量或能力数量，而是记忆链路是否稳定、可解释、可维护，以及是否真的改变 Peppa 的回答行为。

## 建议的下一轮开发顺序

推荐按以下顺序推进：

1. `Recall Inspector`
2. `Source Trace Drilldown`
3. `Memory Maintenance v1`
4. `Document Inbox`
5. `Auto Memory Status`
6. `Conversation / Topic 管理`

其中第一轮最小开发包建议只包含：

- Recall Inspector
- Source Trace Drilldown

这两个功能可以直接复用现有后端数据，不需要大改 schema，风险较低，但能显著提升调试能力。

完成后，Peppa 的核心链路会变成：

```text
chat trace
  -> memory extraction
  -> memory graph
  -> recall
  -> prompt injection
  -> recall inspector
  -> source trace audit
```

这会让“记忆是否正确、为什么被召回、是否影响回答”第一次真正闭环。

## 验收标准

每个后续功能完成时，都应该至少满足：

- 有后端 API 或 agent core 行为
- 有前端展示或 CLI 验证入口
- 有 trace 或 SQLite 状态可审计
- 有最小人工操作路径
- 能说明它如何影响后续 agent 行为
- 不依赖不可解释的长期状态

对于记忆相关功能，额外要求：

- 能回溯 source trace
- 能看到排序、命中或选择原因
- 能被人工修正
- 修正后能被 recall 或后续展示反映出来

## 总结

Peppa 当前最值得投入的方向，是把长期记忆从“能写入数据库”推进到“能被解释地使用，并能被人维护”。

后续开发应围绕一个核心闭环展开：

```text
经历被记录
  -> 重要内容被抽取
  -> 记忆被展示
  -> 相关记忆被召回
  -> 回答受到影响
  -> 错误记忆能被修正
  -> 精确内容沉淀到文档
  -> 稳定流程未来再沉淀为 skill
```

这条路线最贴合原始技术架构，也最能为未来 Telegram、多入口、长期运行、文档记忆和 skill 化记忆打基础。
