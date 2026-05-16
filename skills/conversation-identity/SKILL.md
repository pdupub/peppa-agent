---
name: conversation-identity
description: Bind the current conversation channel to an existing user identity node when the user clearly identifies themselves.
---

# Conversation Identity

你负责判断当前对话入口正在和哪个已有的用户身份 node 对话。

只有当用户明确表达自己的身份时，才调用 `update_conversation_identity`，例如：

- 我是某某
- 我叫某某
- 你可以叫我某某
- 对，我就是候选身份中的某某

不要因为用户提到其他人、举例、开玩笑、角色扮演、或说明 Peppa 的身份而调用工具。

你只能使用输入中提供的候选 person node，不能编造 `memory_node_id`。如果没有合适候选，或者不确定，不要调用工具。

如果候选 node 的名字已经与用户自述身份一致，只绑定该 node。如果候选 node 是“用户”等占位身份，并且用户明确给出了自己的名字，可以用这个名字作为 `title` 来更新该 node。
