# Peppa Memory Extraction

## 目标

这个功能用于让 Peppa 从已发生的对话中提取长期记忆候选。

它不是单独的临时实验入口，而是未来正式记忆写入流程的前半段。当前阶段先把抽取入口暴露在开发调试台中，方便持续观察和调整：

- tool 定义是否合理
- 模型是否能正常调用 tool
- tool call 参数是否符合预期
- `segments`、`memory_graph`、`document_suggestions` 的内容质量是否足够好
- 内容去向是否符合 `semantic_memory`、`external_document`、`trace_only`、`ignore` 的边界

抽取结果稳定后，后续会继续进入 recall 和 memory context 注入流程。

## 使用方式

在调试台的 `Recent Traces` 中，可以勾选若干普通 trace。

点击 `Extract N` 按钮后，Peppa 会：

- 按时间顺序整理选中的 trace
- 使用当前选择的模型
- 使用当前模型对应的 temperature
- 调用 `/api/memory/extract`
- 加载 `skills/memory-extraction/SKILL.md` 作为 system 内容，并用当前 conversation identity 替换 `{{current_user_identity}}`
- 使用 `tool_choice = "auto"`，让模型优先通过 `record_memory_graph_update` 返回结构化结果
- 通过模型配置中的 `tool_adapter` 生成实际请求，并解析 provider 返回的 tool calls
- 将原始 request 和 response 保存为一条新的 trace
- 从统一后的 tool calls 中筛选 `record_memory_graph_update`
- 在参数已经是合法 JSON 的前提下，对 `tags`、`nodes`、`edges` 做一次轻量格式归位
- 将有效的 tags、nodes、edges 写入当前记忆图
- 将 segments、node/edge/tag observations、document suggestions 写入抽取记录表

生成结果会写入本地 SQLite。也可以直接在调试台的 `Response` 面板中查看模型返回的原始 `tool_calls`。

如果模型没有调用 tool，或者 provider 对 tools 支持不稳定，也会直接体现在 `Response` 或 `error` 中。

## Tool Call Adapter

记忆抽取不直接解析不同 provider 的原始 response。模型调用层会先把返回值解析成统一的 tool call 结构：

- `id`
- `name`
- `arguments_raw`
- `arguments`
- `parse_error`

记忆模块只关心 `name == record_memory_graph_update` 的 tool call。其他 tool call 会被忽略。

当前 adapter 行为：

- `deepseek`：保持标准 OpenAI-compatible tool call 格式
- `qwen`：携带 tools 时添加 `enable_thinking = false`
- `qwen`：如果 tool call arguments 出现 provider 特有的多重引号转义或缺失 JSON 值，会在 qwen adapter 内做一次轻量修复，再解析成统一 tool call
- `kimi`：为 function tool 添加 `strict = false`，`kimi-k2.6` 携带 tools 时添加 `thinking = { type = "disabled" }`

这个 adapter 是通用模型能力，不包含 memory schema。未来如果其他功能需要 tool call，应复用同一层适配，只替换自己的 tool schema 和业务处理逻辑。

## 格式归位

部分 OpenAI-compatible provider 能返回合法 JSON，但字段位置可能不完全符合 schema。例如模型可能返回：

```json
{
  "memory_graph": {
    "tags": [],
    "nodes": []
  },
  "edges": []
}
```

标准结构应为：

```json
{
  "memory_graph": {
    "tags": [],
    "nodes": [],
    "edges": []
  }
}
```

因此在 JSON 解析成功之后、写入记忆图之前，会做一次轻量格式归位：递归查找符合 graph schema 形状的 `tags`、`nodes`、`edges`，并合并到 `memory_graph` 的标准字段中。

这个步骤只移动结构位置，不修改 tag 名称、node 标题、edge 关系类型或其他语义内容。如果原始返回已经符合标准结构，内容保持等价。若 tool call 参数本身不是合法 JSON，则不会尝试修复，仍会记录为失败。

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

- memory recall
- memory context 注入
- 文档自动写入
- 复杂 node merge
- `supersedes` 的真实覆盖逻辑

当前已实现第一版持久化：按 `type + normalized_title` 去重 node，按 `source_node_id + target_node_id + relation_type` 去重 edge，按 `normalized_name` 去重 tag。每次抽取仍会额外记录 observation，用于追溯来源和统计提及频率。
