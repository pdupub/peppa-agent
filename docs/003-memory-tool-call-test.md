# Peppa Memory Tool Call Test

## 目标

这个功能用于单独测试大语言模型能否以 `tool_calls` 的形式生成记忆候选。

测试重点不是写入数据库，也不是召回记忆，而是观察：

- tool 定义是否合理
- 模型是否能正常调用 tool
- tool call 参数是否符合预期
- tags、nodes、edges 的内容质量是否足够好

只有这部分稳定后，后续才会进入正式记忆图写入和召回流程。

## 使用方式

在调试台的 `Recent Traces` 中，可以勾选若干普通 trace。

点击 `Memory N` 按钮后，Peppa 会：

- 按时间顺序整理选中的 trace
- 使用当前选择的模型
- 使用当前模型对应的 temperature
- 调用独立的 memory tool-call 测试接口
- 使用 `tool_choice = "auto"` 并通过 prompt 要求模型优先调用 `record_memory_graph_update`
- 将原始 request 和 response 保存为一条新的 trace

生成结果不做额外处理。可以直接在调试台的 `Response` 面板中查看模型返回的原始 tool_calls。

如果模型没有调用 tool，或者 provider 对 tools 支持不稳定，也会直接体现在 `Response` 或 `error` 中。

## 输入范围

当前只使用选中 trace 中的：

- trace id
- model
- user message
- assistant message
- error 信息，如果没有 assistant message

不会把旧 trace 的完整 response payload 或 request payload 放入测试上下文，避免上下文过大。

## 禁用选择

如果一条 trace 是 memory tool-call 测试产生的，或者它的 response 中已经包含 tool_calls，则该 trace 的 checkbox 会被禁用。

这样可以避免把 tool-call 测试结果再次选入下一次测试上下文。

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

这个功能只是为了方便调试和迭代 memory extraction 的 tool schema 与 prompt。
