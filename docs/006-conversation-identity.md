# Conversation Identity

## 目标

Conversation identity 用于让 Peppa 在当前入口中知道自己正在和谁对话。

它不是完整的用户身份合并系统，也不直接改变 memory graph 的结构。第一版只维护“入口实例 -> 已有 person node”的可选绑定关系，并在 system prompt 中注入当前对话对象名称。

## 数据结构

新增表：

```text
conversation_context_identities
- id
- channel
- channel_instance
- memory_node_id
- created_at
- updated_at
```

`memory_node_id` 是可空 foreign key，指向 `memory_nodes.id`。

同一个 `channel + channel_instance` 只有一条记录。

当前默认入口：

```text
web/default
cli/default
```

## 当前身份名称

表中不存单独的用户名称。

读取当前对话对象时：

- 如果 `memory_node_id` 为空，名称为 `用户`
- 如果 `memory_node_id` 不为空，名称为关联的 `memory_nodes.title`

这样可以避免 identity 表和 memory node 表出现两份不同的名字。

## System Prompt 注入

`prompts/agent/system.md` 中包含变量：

```text
{{current_user_identity}}
```

普通 chat 构造 prompt 时会将它替换为当前入口的对话对象名称。

例如默认状态：

```text
作为 Peppa，一个处于早期开发阶段的 AI agent，你正在与用户进行持续对话。
```

绑定到 person node `ABC` 后：

```text
作为 Peppa，一个处于早期开发阶段的 AI agent，你正在与ABC进行持续对话。
```

## Identity Tool

新增 tool：

```text
update_conversation_identity
```

schema 位于：

```text
src/peppa/identity/tool_schema.py
```

skill 位于：

```text
skills/conversation-identity/SKILL.md
```

这个 tool 只能绑定已有的 person node，不能编造 node id。

如果候选 node 已经有明确名字，并且和用户自述身份一致，则只建立入口绑定。

如果候选 node 是 `用户` 等占位身份，并且用户明确说“我是 ABC”或“我叫 ABC”，则可以先将该 node 的 `title` 更新为 `ABC`，再建立入口绑定。

如果候选 node 已经是另一个明确名字，第一版不会自动重命名，避免把两个身份误合并。

## 临时触发方式

调试台中可以勾选 history trace，然后点击 `Identify N`。

Peppa 会：

- 按时间顺序整理选中的 trace
- 列出当前已有的 person node 候选
- 加载 `skills/conversation-identity/SKILL.md`
- 调用当前模型的 identity tool
- 如果 tool call 合法，则更新 `conversation_context_identities`
- 将原始 request 和 response 保存为 trace，方便调试

第一版不会在普通 chat 中自动触发身份绑定。

## Reset Memory

`peppa reset-memory` 会清空 memory graph，同时将所有 conversation identity 的 `memory_node_id` 置空。

因此 reset 后当前对话对象会回到默认的 `用户`，但 conversations、messages 和 traces 仍然保留。
