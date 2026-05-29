from __future__ import annotations

from typing import Any


MEMORY_TOOL_NAME = "record_memory_graph_update"

RETENTION_VALUES = ["semantic_memory", "external_document", "trace_only", "ignore"]

SEGMENT_CATEGORIES = [
    "greeting",
    "one_off_qa",
    "user_identity",
    "user_preference",
    "relationship",
    "project_context",
    "task_state",
    "correction",
    "fictional_setting",
    "temporary_instruction",
    "emotion",
    "safety",
    "other",
]

TAG_KINDS = ["explicit", "inferred", "topic", "preference", "identity"]

NODE_TYPES = [
    "person",
    "project",
    "preference",
    "event",
    "concept",
    "decision",
    "rule",
    "artifact",
]

EDGE_RELATION_TYPES = [
    "related_to",
    "is_a",
    "part_of",
    "has_part",
    "owns",
    "owned_by",
    "cares_for",
    "cared_by",
    "parent_of",
    "child_of",
    "friend_of",
    "works_on",
    "works_with",
    "created_by",
    "creates",
    "uses",
    "prefers",
    "avoids",
    "decided",
    "requires",
    "causes",
    "located_in",
    "participates_in",
    "acts_on",
    "supports",
    "depends_on",
    "mentions",
    "documents",
    "supersedes",
    "conflicts_with",
]

DOCUMENT_TYPES = [
    "architecture",
    "decision",
    "task_state",
    "prompt",
    "tool_schema",
    "workflow",
    "creative_setting",
    "other",
]


MEMORY_GRAPH_UPDATE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": MEMORY_TOOL_NAME,
        "description": (
            "从给定对话中提取长期记忆候选。先判断内容分类和保留位置，"
            "再使用 tags 记录可回忆的关键词和联想概念，使用 nodes 记录人、项目、事件、偏好、规则、概念等，"
            "使用 edges 记录 nodes 之间的有限类型关系。工程化、精确或大段内容应进入 document_suggestions。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "segments": {
                    "type": "array",
                    "description": "对输入内容进行分类，并判断每段内容应如何保留。",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "source_trace_id": {
                                "type": "string",
                                "description": "必须使用输入上下文中实际存在的 trace_id，不能编造。",
                            },
                            "text": {"type": "string"},
                            "category": {"type": "string", "enum": SEGMENT_CATEGORIES},
                            "retention": {"type": "string", "enum": RETENTION_VALUES},
                            "reason": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": [
                            "source_trace_id",
                            "text",
                            "category",
                            "retention",
                            "reason",
                            "confidence",
                        ],
                    },
                },
                "memory_graph": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "适合进入语义记忆图的 tags、nodes、edges。",
                    "properties": {
                        "tags": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "name": {"type": "string"},
                                    "kind": {"type": "string", "enum": TAG_KINDS},
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
                                    "type": {"type": "string", "enum": NODE_TYPES},
                                    "title": {
                                        "type": "string",
                                        "description": (
                                            "node 的短标题。必须是短名词或短名词短语；"
                                            "英文最多 3 个单词，中文不超过 8 个汉字。"
                                            "不要写完整句子，细节放入 summary、source_quote、tags 或 edge。"
                                        ),
                                    },
                                    "summary": {"type": "string"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                    "source_trace_id": {
                                        "type": "string",
                                        "description": "必须使用输入上下文中实际存在的 trace_id，不能编造。",
                                    },
                                    "source_quote": {"type": "string"},
                                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                },
                                "required": [
                                    "ref",
                                    "type",
                                    "title",
                                    "summary",
                                    "tags",
                                    "source_trace_id",
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
                                    "relation_type": {"type": "string", "enum": EDGE_RELATION_TYPES},
                                    "summary": {"type": "string"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                    "source_trace_id": {
                                        "type": "string",
                                        "description": "必须使用输入上下文中实际存在的 trace_id，不能编造。",
                                    },
                                    "source_quote": {"type": "string"},
                                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                },
                                "required": [
                                    "source_ref",
                                    "target_ref",
                                    "relation_type",
                                    "summary",
                                    "tags",
                                    "source_trace_id",
                                    "source_quote",
                                    "confidence",
                                ],
                            },
                        },
                    },
                    "required": ["tags", "nodes", "edges"],
                },
                "document_suggestions": {
                    "type": "array",
                    "description": "适合写入外部文档而不是塞进语义记忆图的内容建议。",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "project": {"type": "string"},
                            "document_type": {"type": "string", "enum": DOCUMENT_TYPES},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "source_trace_id": {
                                "type": "string",
                                "description": "必须使用输入上下文中实际存在的 trace_id，不能编造。",
                            },
                            "source_quote": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reason": {"type": "string"},
                        },
                        "required": [
                            "project",
                            "document_type",
                            "title",
                            "summary",
                            "source_trace_id",
                            "source_quote",
                            "tags",
                            "confidence",
                            "reason",
                        ],
                    },
                },
            },
            "required": ["segments", "memory_graph", "document_suggestions"],
        },
    },
}


def memory_graph_update_tools() -> list[dict[str, Any]]:
    return [MEMORY_GRAPH_UPDATE_TOOL]


def memory_tool_choice() -> str:
    return "auto"
