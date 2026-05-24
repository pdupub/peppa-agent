# Topic Boundary Tool

## 目标

`mark_topic_boundary` 是普通 chat 请求中携带的轻量 side-effect tool。

它用于根据最近对话上下文判断本轮用户输入是否明显开启了新的对话话题。用户仍然看到模型的正常回答；只有当模型判断出现新话题时，才通过 `tool_choice = "auto"` 附带 tool call，记录一个可审计的边界候选。

## 使用边界

应该调用：

- 用户切换到不同任务
- 用户切换到不同项目
- 用户切换到不同生活话题
- 用户提出新的长期目标或计划

不应该调用：

- 对当前话题追问
- 澄清当前问题
- 补充当前任务细节
- 修正当前方向
- 继续同一项目的下一步
- 模型不确定是否新话题

## 数据形态

tool 参数保持很小：

```text
topic_title
reason
confidence
tags
assistant_message
```

其中 `assistant_message` 是本轮给用户看的正常回复正文。它应该只回应本轮新话题相关内容，不应因为上下文或记忆背景存在其他信息而回应旧话题。它不写入 `topic_boundaries` 的结构化列，但会保留在 raw tool arguments 中。

`topic_title`、`reason`、`confidence` 和 `tags` 会写入 `topic_boundaries` 表，供后续会话分段、记忆抽取范围和 recall 使用。聊天 trace 仍然保留原始 request / response，必要时可以从 response payload 审计模型是否发起了 tool call。

## 空 content 兜底

部分模型在返回 tool call 时会把普通 assistant `content` 留空。服务端会先使用 `content`；如果 `content` 为空且本轮包含 `mark_topic_boundary`，则从 tool arguments 的 `assistant_message` 回填普通 assistant 消息。

回填后的内容会写入现有 `messages.content` 和 `traces.assistant_message`，不改变数据库结构。这样网页回显、后续上下文条数选择、记忆抽取和身份抽取都会把它当作普通 assistant 回复处理。
