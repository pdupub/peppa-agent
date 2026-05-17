from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import sqlite3
import uuid

from peppa.models.tool_calls import ToolCall
from peppa.paths import DATABASE_PATH
from peppa.topics.tool_schema import TOPIC_BOUNDARY_TOOL_NAME


def ensure_topic_boundary_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS topic_boundaries (
            id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            tool_call_id TEXT,
            topic_title TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence REAL NOT NULL,
            tags_json TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            raw_arguments_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (trace_id) REFERENCES traces(id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE INDEX IF NOT EXISTS idx_topic_boundaries_trace
            ON topic_boundaries(trace_id);

        CREATE INDEX IF NOT EXISTS idx_topic_boundaries_conversation_created
            ON topic_boundaries(conversation_id, created_at);
        """
    )


class TopicBoundaryStore:
    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        with self._connect() as connection:
            ensure_topic_boundary_schema(connection)

    def record_tool_calls(
        self,
        *,
        trace_id: str,
        conversation_id: str,
        tool_calls: list[ToolCall],
    ) -> list[str]:
        record_ids = []
        now = _now()
        with self._connect() as connection:
            ensure_topic_boundary_schema(connection)
            for tool_call in tool_calls:
                if tool_call.name != TOPIC_BOUNDARY_TOOL_NAME:
                    continue
                record_ids.append(
                    self._insert_boundary(
                        connection=connection,
                        trace_id=trace_id,
                        conversation_id=conversation_id,
                        tool_call=tool_call,
                        now=now,
                    )
                )
        return record_ids

    def _insert_boundary(
        self,
        *,
        connection: sqlite3.Connection,
        trace_id: str,
        conversation_id: str,
        tool_call: ToolCall,
        now: str,
    ) -> str:
        record_id = _new_id("topic")
        parsed = _as_record(tool_call.arguments)
        parse_error = tool_call.parse_error
        title = _clean_text(parsed.get("topic_title"))
        reason = _clean_text(parsed.get("reason"))
        confidence = _confidence(parsed.get("confidence"))
        tags = _text_list(parsed.get("tags"))

        status = "valid"
        error = None
        if parse_error:
            status = "invalid"
            error = parse_error
        elif not title:
            status = "invalid"
            error = "topic_title is required."

        connection.execute(
            """
            INSERT INTO topic_boundaries (
                id,
                trace_id,
                conversation_id,
                tool_call_id,
                topic_title,
                reason,
                confidence,
                tags_json,
                status,
                error,
                raw_arguments_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                trace_id,
                conversation_id,
                tool_call.id,
                title,
                reason,
                confidence,
                json.dumps(tags, ensure_ascii=False),
                status,
                error,
                json.dumps(tool_call.arguments_raw, ensure_ascii=False),
                now,
            ),
        )
        return record_id

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = _clean_text(item)
        if text:
            result.append(text)
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
