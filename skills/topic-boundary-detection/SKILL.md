---
name: topic-boundary-detection
description: Detect explicit topic boundaries from ordered conversation traces.
---

# Topic Boundary Detection

你负责从一批按时间顺序排列的对话 trace 中判断是否出现明确的新话题边界。

输入包含：

- `previous_context`：候选批次之前的一条上下文 trace，只用于比较延续关系，不能作为新话题起点。
- `candidate_traces`：本次可以判定边界的候选 trace 列表。

当且仅当某条候选 trace 的用户输入明显开启一个新的对话话题时，记录一个 boundary。

应该记录 boundary：

- 用户切换到不同任务
- 用户切换到不同项目
- 用户切换到不同生活话题
- 用户提出新的长期目标或计划

不应该记录 boundary：

- 对当前话题追问
- 澄清当前问题
- 补充当前任务细节
- 修正当前方向
- 继续同一项目的下一步
- 你不确定是否新话题

如果第一条候选 trace 相比 `previous_context` 已经是新话题，可以把第一条候选 trace 作为 `start_trace_id`。

如果候选批次中多次切换话题，可以返回多个 boundaries。每个 `start_trace_id` 必须来自 `candidate_traces` 中真实存在的 `trace_id`，不能编造，不能使用 `previous_context.trace_id`。

不要生成给用户看的聊天回复。请通过 `record_topic_boundaries` 工具返回结构化结果：

- `boundaries`: 新话题边界数组；没有明确新话题时返回空数组
- `no_boundary_reason`: 当 `boundaries` 为空时，说明为什么没有明确新话题

每个 boundary 包含：

- `start_trace_id`: 新话题从哪条候选 trace 开始
- `topic_title`: 新话题短标题
- `reason`: 为什么这是新话题
- `confidence`: 0 到 1 的置信度
- `tags`: 少量人类可读标签
