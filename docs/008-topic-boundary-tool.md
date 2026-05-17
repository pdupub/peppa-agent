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
```

这些数据会写入 `topic_boundaries` 表，供后续会话分段、记忆抽取范围和 recall 使用。聊天 trace 仍然保留原始 request / response，必要时可以从 response payload 审计模型是否发起了 tool call。

## 当前取舍

当前版本不增加 content 为空的自动兜底。

这是有意保留的观察点：如果模型在调用该 tool 时经常返回空 `content`，说明这种“正常回答 + 附带 tool call”的设计在当前模型上不够稳定，需要调整方案。
