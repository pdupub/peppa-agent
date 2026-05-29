# Topic Boundary Detection

## 目标

topic boundary 不再挂在普通 chat 请求里作为 side-effect tool。

普通 chat 只负责生成用户可见的正常文本回复；新话题判断被拆成独立的后台 detection run，和 memory extraction、identity update 属于同一类模型分析任务。

这样做的目标是：

- 主聊天 response 恢复为普通文本结构
- 后续 stream 可以只展示 assistant 正文
- topic boundary 的结构化结果可以单独审计
- memory recall 仍然可以用最近 topic boundary 缩小当前话题范围

## 运行时机

每个 conversation 维护独立的 `topic_boundary_auto_state`。

当某个 conversation 自上次成功 topic detection 后累计至少 5 条普通 chat trace 时，后台自动运行一次 topic detection。

本次 detection 输入：

- 上次成功 detection 之后的普通 chat trace
- 最多 12 条候选 trace
- 候选批次之前的一条 `previous_context`，只用于判断第一条候选是否已经切换话题

如果超过 12 条未处理 trace，会先处理最早的 12 条，成功后状态推进到本批最后一条。

## 输出结构

模型通过 `record_topic_boundaries` 工具返回结构化结果。

```json
{
  "boundaries": [
    {
      "start_trace_id": "trace_xxx",
      "topic_title": "新话题标题",
      "reason": "为什么从这一条开始是新话题",
      "confidence": 0.86,
      "tags": ["tag"]
    }
  ],
  "no_boundary_reason": ""
}
```

`start_trace_id` 必须来自本批候选 trace，不能来自 `previous_context`。如果没有明确新话题，`boundaries` 返回空数组，并填写 `no_boundary_reason`。

一次 detection run 可以返回多个 boundaries。

## 存储结构

`topic_boundary_runs` 记录一次后台判定运行：

- detection trace id
- source conversation id
- source trace ids
- previous trace id
- raw tool arguments
- status / error

`topic_boundaries` 只记录实际发现的新话题边界：

- `trace_id` 表示新话题开始的 chat trace
- `run_id` 指向产生它的 detection run
- `topic_title`
- `reason`
- `confidence`
- `tags_json`

历史上 `topic_boundaries.trace_id` 已经被 memory recall 用作当前话题起点，因此继续保留这个字段语义。

## 与记忆抽取的关系

普通 chat 完成后，后台 follow-up 顺序执行：

```text
chat
  -> topic boundary detection if enough pending traces
  -> auto memory extraction
```

如果本次 topic detection 发现了新话题，auto memory extraction 使用 `topic_boundary` 作为触发原因；否则保留原有按轮数触发的 `turn_count` 逻辑。

因此 topic boundary 从主聊天中移除后，仍然会参与自动记忆抽取触发和后续 recall 范围控制。
