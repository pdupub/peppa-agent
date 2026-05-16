from __future__ import annotations

from typing import Any


IDENTITY_TOOL_NAME = "update_conversation_identity"

IDENTITY_UPDATE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": IDENTITY_TOOL_NAME,
        "description": (
            "将当前对话入口绑定到一个已存在的用户身份 node。"
            "当用户明确说明自己是谁、叫什么、或确认自己就是某个候选身份时使用。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "memory_node_id": {
                    "type": "string",
                    "description": "必须是候选 person node 中真实存在的 id，不能编造。",
                },
                "title": {
                    "type": "string",
                    "description": (
                        "用户确认后的名字。若候选 node 已有相同名字，保持该名字；"
                        "若候选 node 是“用户”等占位身份，可使用用户自述的新名字。"
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "简短说明为什么确认当前对话对象就是这个 node。",
                },
            },
            "required": ["memory_node_id", "title", "reason"],
        },
    },
}


def identity_update_tools() -> list[dict[str, Any]]:
    return [IDENTITY_UPDATE_TOOL]


def identity_tool_choice() -> str:
    return "auto"
