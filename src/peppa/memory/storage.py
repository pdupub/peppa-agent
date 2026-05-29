from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import sqlite3
import uuid

from peppa.paths import DATABASE_PATH, ensure_runtime_dirs
from peppa.identity import ensure_identity_schema
from peppa.memory.schema import ensure_memory_graph_schema
from peppa.topics import ensure_topic_boundary_schema


# Deprecated compatibility value for the old traces.memory_json column.
# Recall metadata now lives in request_payload["_peppa"]["memory_recall"].
DEPRECATED_TRACE_MEMORY_JSON = "null"


@dataclass(frozen=True)
class TraceRecord:
    id: str
    conversation_id: str
    model: str
    user_message: str
    assistant_message: str | None
    prompt_messages: list[dict[str, Any]]
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None
    duration_ms: int | None
    error: str | None
    created_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "model": self.model,
            "user_message": self.user_message,
            "assistant_message": self.assistant_message,
            "prompt_messages": self.prompt_messages,
            "request_payload": self.request_payload,
            "response_payload": self.response_payload,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "created_at": self.created_at,
        }


class Storage:
    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        ensure_runtime_dirs()
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );

                CREATE TABLE IF NOT EXISTS traces (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    assistant_message TEXT,
                    prompt_json TEXT NOT NULL,
                    memory_json TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT,
                    duration_ms INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                    ON messages(conversation_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_traces_created
                    ON traces(created_at DESC);
                """
            )
            ensure_memory_graph_schema(connection)
            ensure_identity_schema(connection)
            ensure_topic_boundary_schema(connection)

    def create_conversation(self, title: str) -> str:
        conversation_id = _new_id("conv")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, title[:120] or "Untitled", now, now),
            )
        return conversation_id

    def add_message(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        model: str | None = None,
    ) -> str:
        message_id = _new_id("msg")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, role, content, model, now),
            )
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE id = ?
                """,
                (now, conversation_id),
            )
        return message_id

    def list_messages(self, *, conversation_id: str, limit: int = 12) -> list[dict[str, Any]]:
        safe_limit = max(0, min(limit, 50))
        if safe_limit == 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM (
                    SELECT role, content, created_at
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC
                """,
                (conversation_id, safe_limit),
            ).fetchall()
        return [
            {"role": row["role"], "content": row["content"]}
            for row in rows
            if row["role"] in {"user", "assistant"} and row["content"].strip()
        ]

    def create_trace(
        self,
        *,
        conversation_id: str,
        model: str,
        user_message: str,
        assistant_message: str | None,
        prompt_messages: list[dict[str, Any]],
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | None,
        duration_ms: int | None,
        error: str | None,
    ) -> TraceRecord:
        trace = TraceRecord(
            id=_new_id("trace"),
            conversation_id=conversation_id,
            model=model,
            user_message=user_message,
            assistant_message=assistant_message,
            prompt_messages=prompt_messages,
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=duration_ms,
            error=error,
            created_at=_now(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO traces (
                    id,
                    conversation_id,
                    model,
                    user_message,
                    assistant_message,
                    prompt_json,
                    memory_json,
                    request_json,
                    response_json,
                    duration_ms,
                    error,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.id,
                    trace.conversation_id,
                    trace.model,
                    trace.user_message,
                    trace.assistant_message,
                    json.dumps(trace.prompt_messages, ensure_ascii=False),
                    DEPRECATED_TRACE_MEMORY_JSON,
                    json.dumps(trace.request_payload, ensure_ascii=False),
                    json.dumps(trace.response_payload, ensure_ascii=False)
                    if trace.response_payload is not None
                    else None,
                    trace.duration_ms,
                    trace.error,
                    trace.created_at,
                ),
            )
        return trace

    def list_traces(self, limit: int = 25) -> list[TraceRecord]:
        safe_limit = max(1, min(limit, 100))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM traces
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [_trace_from_row(row) for row in rows]

    def list_traces_after(self, created_at: str | None) -> list[TraceRecord]:
        with self._connect() as connection:
            if created_at:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM traces
                    WHERE created_at > ?
                    ORDER BY created_at ASC
                    """,
                    (created_at,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM traces
                    ORDER BY created_at ASC
                    """
                ).fetchall()
        return [_trace_from_row(row) for row in rows]

    def list_conversation_traces_after(
        self,
        *,
        conversation_id: str,
        created_at: str | None,
    ) -> list[TraceRecord]:
        with self._connect() as connection:
            if created_at:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM traces
                    WHERE conversation_id = ?
                        AND created_at > ?
                    ORDER BY created_at ASC
                    """,
                    (conversation_id, created_at),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM traces
                    WHERE conversation_id = ?
                    ORDER BY created_at ASC
                    """,
                    (conversation_id,),
                ).fetchall()
        return [_trace_from_row(row) for row in rows]

    def get_previous_conversation_trace(
        self,
        *,
        conversation_id: str,
        before_created_at: str,
    ) -> TraceRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM traces
                WHERE conversation_id = ?
                    AND created_at < ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (conversation_id, before_created_at),
            ).fetchone()
        if row is None:
            return None
        return _trace_from_row(row)

    def get_trace(self, trace_id: str) -> TraceRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM traces
                WHERE id = ?
                """,
                (trace_id,),
            ).fetchone()
        if row is None:
            return None
        return _trace_from_row(row)

    def update_trace_error(self, trace_id: str, error: str) -> TraceRecord | None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE traces
                SET error = ?
                WHERE id = ?
                """,
                (error, trace_id),
            )
            row = connection.execute(
                """
                SELECT *
                FROM traces
                WHERE id = ?
                """,
                (trace_id,),
            ).fetchone()
        if row is None:
            return None
        return _trace_from_row(row)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _trace_from_row(row: sqlite3.Row) -> TraceRecord:
    return TraceRecord(
        id=row["id"],
        conversation_id=row["conversation_id"],
        model=row["model"],
        user_message=row["user_message"],
        assistant_message=row["assistant_message"],
        prompt_messages=json.loads(row["prompt_json"]),
        request_payload=json.loads(row["request_json"]),
        response_payload=json.loads(row["response_json"]) if row["response_json"] else None,
        duration_ms=row["duration_ms"],
        error=row["error"],
        created_at=row["created_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
