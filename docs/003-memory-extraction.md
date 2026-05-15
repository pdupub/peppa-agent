# Peppa Memory Extraction

## 目标

这个功能用于让 Peppa 从已发生的对话中提取长期记忆候选。

它不是单独的临时实验入口，而是未来正式记忆写入流程的前半段。当前阶段先把抽取入口暴露在开发调试台中，方便持续观察和调整：

- tool 定义是否合理
- 模型是否能正常调用 tool
- tool call 参数是否符合预期
- `segments`、`memory_graph`、`document_suggestions` 的内容质量是否足够好
- 内容去向是否符合 `semantic_memory`、`external_document`、`trace_only`、`ignore` 的边界

只有抽取规则稳定后，后续才会进入正式记忆图写入、去重合并和召回流程。

## 使用方式

在调试台的 `Recent Traces` 中，可以勾选若干普通 trace。

点击 `Extract N` 按钮后，Peppa 会：

- 按时间顺序整理选中的 trace
- 使用当前选择的模型
- 使用当前模型对应的 temperature
- 调用 `/api/memory/extract`
- 加载 `skills/memory-extraction/SKILL.md` 作为 system 内容
- 使用 `tool_choice = "auto"`，让模型优先通过 `record_memory_graph_update` 返回结构化结果
- 将原始 request 和 response 保存为一条新的 trace

生成结果当前不做额外处理。可以直接在调试台的 `Response` 面板中查看模型返回的原始 `tool_calls`。

如果模型没有调用 tool，或者 provider 对 tools 支持不稳定，也会直接体现在 `Response` 或 `error` 中。

## 输入范围

当前只使用选中 trace 中的：

- trace id
- model
- user message
- assistant message
- error 信息，如果没有 assistant message

不会把旧 trace 的完整 response payload 或 request payload 放入抽取上下文，避免上下文过大。

## 禁用选择

如果一条 trace 是 memory extraction 产生的，或者它的 response 中已经包含 `tool_calls`，则该 trace 的 checkbox 会被禁用。

这样可以避免把结构化抽取结果再次选入下一次抽取上下文。

## 当前边界

当前阶段不实现：

- tags 写入
- nodes 写入
- edges 写入
- 去重合并
- source 链接
- graph 持久化
- memory recall
- memory context 注入

当前目标是稳定 memory extraction 的 skill 与 tool schema。数据库中只记录这次模型调用的 trace，尚不把返回内容写入记忆图。
