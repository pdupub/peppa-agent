from __future__ import annotations

from typing import Any


TOPIC_BOUNDARY_TOOL_NAME = "record_topic_boundaries"


TOPIC_BOUNDARY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOPIC_BOUNDARY_TOOL_NAME,
        "description": (
            "分析一批按时间排序的对话 trace，并记录其中明确开启新话题的边界。"
            "只能从候选 trace 中选择新话题起点，不能选择 previous_context。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "boundaries": {
                    "type": "array",
                    "description": "本批候选 trace 中发现的新话题边界；没有新话题时返回空数组。",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "start_trace_id": {
                                "type": "string",
                                "description": "新话题从哪一条候选 trace 开始，必须是真实 trace_id。",
                            },
                            "topic_title": {
                                "type": "string",
                                "description": "对新话题的人类可读短标题。",
                            },
                            "reason": {
                                "type": "string",
                                "description": "为什么判断这是新话题，而不是前一话题的延续。",
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "对新话题判断的置信度。",
                            },
                            "tags": {
                                "type": "array",
                                "description": "少量可用于后续回忆或分段的人类可读标签。",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "start_trace_id",
                            "topic_title",
                            "reason",
                            "confidence",
                            "tags",
                        ],
                    },
                },
                "no_boundary_reason": {
                    "type": "string",
                    "description": (
                        "如果 boundaries 为空，简短说明为什么这批候选 trace 没有明确新话题。"
                        "如果 boundaries 非空，可以留空。"
                    ),
                },
            },
            "required": ["boundaries", "no_boundary_reason"],
        },
    },
}


def topic_boundary_tools() -> list[dict[str, Any]]:
    return [TOPIC_BOUNDARY_TOOL]


def topic_boundary_tool_choice() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": TOPIC_BOUNDARY_TOOL_NAME},
    }
