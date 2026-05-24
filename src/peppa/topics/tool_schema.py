from __future__ import annotations

from typing import Any


TOPIC_BOUNDARY_TOOL_NAME = "mark_topic_boundary"


TOPIC_BOUNDARY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOPIC_BOUNDARY_TOOL_NAME,
        "description": (
            "当且仅当用户在本轮输入中明确开启一个新的对话话题时调用。"
            "不要因为追问、澄清、补充细节、修正当前任务或继续讨论同一主题而调用。"
            "这是一个后台记录工具；调用它时仍然应该在 content 中正常回复用户。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "topic_title": {
                    "type": "string",
                    "description": "对新话题的人类可读短标题。",
                },
                "reason": {
                    "type": "string",
                    "description": "为什么判断这是新话题，而不是当前话题的延续。",
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
                "assistant_message": {
                    "type": "string",
                    "description": (
                        "本轮应该展示给用户的完整正常回复正文。调用该工具时必须填写，"
                        "内容应和 assistant content 中的可见回复一致，只回应本轮新话题相关内容，"
                        "不要因为上下文或记忆背景中存在其他信息而回应旧话题，不要提及工具调用。"
                    ),
                },
            },
            "required": [
                "topic_title",
                "reason",
                "confidence",
                "tags",
                "assistant_message",
            ],
        },
    },
}


def topic_boundary_tools() -> list[dict[str, Any]]:
    return [TOPIC_BOUNDARY_TOOL]


def topic_boundary_tool_choice() -> str:
    return "auto"
