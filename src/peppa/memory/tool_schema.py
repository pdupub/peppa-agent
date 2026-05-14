from __future__ import annotations

from typing import Any


MEMORY_TOOL_NAME = "record_memory_graph_update"


MEMORY_GRAPH_UPDATE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": MEMORY_TOOL_NAME,
        "description": (
            "从给定对话中提取长期记忆候选。使用 tags 记录可回忆的关键词和联想概念，"
            "使用 nodes 记录人、项目、事件、偏好、规则、概念等，使用 edges 记录 nodes 之间的关系。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "kind": {
                                "type": "string",
                                "enum": ["explicit", "inferred", "topic", "preference", "identity"],
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reason": {"type": "string"},
                        },
                        "required": ["name", "kind", "confidence", "reason"],
                    },
                },
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "ref": {
                                "type": "string",
                                "description": "本次 tool call 内的临时引用，例如 node_1。",
                            },
                            "type": {
                                "type": "string",
                                "enum": [
                                    "person",
                                    "project",
                                    "preference",
                                    "event",
                                    "concept",
                                    "decision",
                                    "rule",
                                    "artifact",
                                ],
                            },
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "source_quote": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": [
                            "ref",
                            "type",
                            "title",
                            "summary",
                            "tags",
                            "source_quote",
                            "confidence",
                        ],
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "source_ref": {"type": "string"},
                            "target_ref": {"type": "string"},
                            "relation": {"type": "string"},
                            "summary": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "source_quote": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": [
                            "source_ref",
                            "target_ref",
                            "relation",
                            "summary",
                            "tags",
                            "source_quote",
                            "confidence",
                        ],
                    },
                },
            },
            "required": ["tags", "nodes", "edges"],
        },
    },
}


def memory_graph_update_tools() -> list[dict[str, Any]]:
    return [MEMORY_GRAPH_UPDATE_TOOL]


def memory_tool_choice() -> str:
    return "auto"
