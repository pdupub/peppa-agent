from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import sqlite3
import uuid

from peppa.models.tool_calls import ToolCall
from peppa.paths import DATABASE_PATH
from peppa.topics.tool_schema import TOPIC_BOUNDARY_TOOL_NAME


TOPIC_BOUNDARY_DETECTION_STATE_ID_PREFIX = "conversation"
TOPIC_BOUNDARY_DETECTION_TURN_THRESHOLD = 5
MAX_TOPIC_BOUNDARY_DETECTION_TRACES = 12


@dataclass(frozen=True)
class TopicBoundaryAutoDetectionState:
    id: str
    conversation_id: str
    last_source_trace_id: str | None
    last_source_trace_created_at: str | None
    last_detection_trace_id: str | None
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "last_source_trace_id": self.last_source_trace_id,
            "last_source_trace_created_at": self.last_source_trace_created_at,
            "last_detection_trace_id": self.last_detection_trace_id,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class TopicBoundaryRecord:
    id: str
    trace_id: str
    conversation_id: str
    run_id: str | None
    topic_title: str
    reason: str
    confidence: float
    tags: list[str]
    status: str
    error: str | None
    created_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start_trace_id": self.trace_id,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "topic_title": self.topic_title,
            "reason": self.reason,
            "confidence": self.confidence,
            "tags": self.tags,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class TopicBoundaryRunRecord:
    id: str
    detection_trace_id: str
    conversation_id: str
    model: str
    tool_call_id: str | None
    source_trace_ids: list[str]
    previous_trace_id: str | None
    status: str
    error: str | None
    boundaries: list[TopicBoundaryRecord]
    created_at: str

    @property
    def success(self) -> bool:
        return self.status == "valid"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "detection_trace_id": self.detection_trace_id,
            "conversation_id": self.conversation_id,
            "model": self.model,
            "tool_call_id": self.tool_call_id,
            "source_trace_ids": self.source_trace_ids,
            "previous_trace_id": self.previous_trace_id,
            "status": self.status,
            "error": self.error,
            "boundaries": [boundary.public_dict() for boundary in self.boundaries],
            "created_at": self.created_at,
        }


def ensure_topic_boundary_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS topic_boundary_runs (
            id TEXT PRIMARY KEY,
            detection_trace_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            model TEXT NOT NULL,
            tool_call_id TEXT,
            source_trace_ids_json TEXT NOT NULL,
            previous_trace_id TEXT,
            raw_arguments_json TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (detection_trace_id) REFERENCES traces(id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (previous_trace_id) REFERENCES traces(id)
        );

        CREATE TABLE IF NOT EXISTS topic_boundaries (
            id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            run_id TEXT,
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
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (run_id) REFERENCES topic_boundary_runs(id)
        );

        CREATE TABLE IF NOT EXISTS topic_boundary_auto_state (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL UNIQUE,
            last_source_trace_id TEXT,
            last_source_trace_created_at TEXT,
            last_detection_trace_id TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (last_source_trace_id) REFERENCES traces(id),
            FOREIGN KEY (last_detection_trace_id) REFERENCES traces(id)
        );

        CREATE INDEX IF NOT EXISTS idx_topic_boundary_runs_conversation_created
            ON topic_boundary_runs(conversation_id, created_at);

        CREATE INDEX IF NOT EXISTS idx_topic_boundaries_trace
            ON topic_boundaries(trace_id);

        CREATE INDEX IF NOT EXISTS idx_topic_boundaries_conversation_created
            ON topic_boundaries(conversation_id, created_at);
        """
    )
    _ensure_column(connection, "topic_boundaries", "run_id", "TEXT")


class TopicBoundaryStore:
    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        with self._connect() as connection:
            ensure_topic_boundary_schema(connection)

    def get_auto_detection_state(
        self,
        conversation_id: str,
    ) -> TopicBoundaryAutoDetectionState | None:
        with self._connect() as connection:
            ensure_topic_boundary_schema(connection)
            row = connection.execute(
                """
                SELECT *
                FROM topic_boundary_auto_state
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return _auto_detection_state_from_row(row)

    def mark_auto_detection_complete(
        self,
        *,
        conversation_id: str,
        last_source_trace_id: str,
        last_source_trace_created_at: str,
        detection_trace_id: str,
    ) -> TopicBoundaryAutoDetectionState:
        now = _now()
        state_id = _auto_detection_state_id(conversation_id)
        with self._connect() as connection:
            ensure_topic_boundary_schema(connection)
            connection.execute(
                """
                INSERT INTO topic_boundary_auto_state (
                    id,
                    conversation_id,
                    last_source_trace_id,
                    last_source_trace_created_at,
                    last_detection_trace_id,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    last_source_trace_id = excluded.last_source_trace_id,
                    last_source_trace_created_at = excluded.last_source_trace_created_at,
                    last_detection_trace_id = excluded.last_detection_trace_id,
                    updated_at = excluded.updated_at
                """,
                (
                    state_id,
                    conversation_id,
                    last_source_trace_id,
                    last_source_trace_created_at,
                    detection_trace_id,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM topic_boundary_auto_state
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Failed to update topic boundary auto detection state.")
        return _auto_detection_state_from_row(row)

    def record_detection_tool_calls(
        self,
        *,
        detection_trace_id: str,
        conversation_id: str,
        model: str,
        source_trace_ids: list[str],
        previous_trace_id: str | None,
        tool_calls: list[ToolCall],
    ) -> TopicBoundaryRunRecord:
        now = _now()
        with self._connect() as connection:
            ensure_topic_boundary_schema(connection)
            return self._insert_detection_run(
                connection=connection,
                detection_trace_id=detection_trace_id,
                conversation_id=conversation_id,
                model=model,
                source_trace_ids=source_trace_ids,
                previous_trace_id=previous_trace_id,
                tool_calls=tool_calls,
                now=now,
            )

    def _insert_detection_run(
        self,
        *,
        connection: sqlite3.Connection,
        detection_trace_id: str,
        conversation_id: str,
        model: str,
        source_trace_ids: list[str],
        previous_trace_id: str | None,
        tool_calls: list[ToolCall],
        now: str,
    ) -> TopicBoundaryRunRecord:
        run_id = _new_id("topic_run")
        source_trace_id_set = set(source_trace_ids)
        tool_call = next(
            (candidate for candidate in tool_calls if candidate.name == TOPIC_BOUNDARY_TOOL_NAME),
            None,
        )
        parsed = _as_record(tool_call.arguments if tool_call else None)
        parse_error = tool_call.parse_error if tool_call else "Topic boundary tool call is missing."
        raw_arguments = tool_call.arguments_raw if tool_call else None
        boundaries = _as_list(parsed.get("boundaries"))
        run_errors: list[str] = []
        boundary_records: list[TopicBoundaryRecord] = []
        validated_boundaries: list[dict[str, Any]] = []

        if parse_error:
            run_errors.append(parse_error)
        elif not isinstance(parsed.get("boundaries"), list):
            run_errors.append("boundaries must be an array.")
        elif not boundaries and not _clean_text(parsed.get("no_boundary_reason")):
            run_errors.append("no_boundary_reason is required when boundaries is empty.")

        if not parse_error:
            for index, boundary in enumerate(boundaries, start=1):
                parsed_boundary = _as_record(boundary)
                validation_error = _boundary_validation_error(
                    parsed_boundary,
                    source_trace_id_set,
                )
                if validation_error:
                    run_errors.append(f"boundary #{index}: {validation_error}")
                else:
                    validated_boundaries.append(parsed_boundary)

        status = "valid" if not run_errors else "invalid"
        error = "; ".join(run_errors) if run_errors else None
        connection.execute(
            """
            INSERT INTO topic_boundary_runs (
                id,
                detection_trace_id,
                conversation_id,
                model,
                tool_call_id,
                source_trace_ids_json,
                previous_trace_id,
                raw_arguments_json,
                status,
                error,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                detection_trace_id,
                conversation_id,
                model,
                tool_call.id if tool_call else None,
                json.dumps(source_trace_ids, ensure_ascii=False),
                previous_trace_id,
                json.dumps(raw_arguments, ensure_ascii=False),
                status,
                error,
                now,
            ),
        )

        if not run_errors:
            for boundary in validated_boundaries:
                record, insert_error = self._insert_boundary(
                    connection=connection,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    tool_call_id=tool_call.id if tool_call else None,
                    source_trace_ids=source_trace_id_set,
                    boundary=boundary,
                    raw_arguments=raw_arguments,
                    now=now,
                )
                if record is not None:
                    boundary_records.append(record)
                if insert_error:
                    run_errors.append(insert_error)

        if run_errors and status == "valid":
            status = "invalid"
            error = "; ".join(run_errors)
            connection.execute(
                """
                UPDATE topic_boundary_runs
                SET status = ?,
                    error = ?
                WHERE id = ?
                """,
                (status, error, run_id),
            )

        return TopicBoundaryRunRecord(
            id=run_id,
            detection_trace_id=detection_trace_id,
            conversation_id=conversation_id,
            model=model,
            tool_call_id=tool_call.id if tool_call else None,
            source_trace_ids=source_trace_ids,
            previous_trace_id=previous_trace_id,
            status=status,
            error=error,
            boundaries=boundary_records,
            created_at=now,
        )

    def _insert_boundary(
        self,
        *,
        connection: sqlite3.Connection,
        run_id: str,
        conversation_id: str,
        tool_call_id: str | None,
        source_trace_ids: set[str],
        boundary: Any,
        raw_arguments: Any,
        now: str,
    ) -> tuple[TopicBoundaryRecord | None, str | None]:
        record_id = _new_id("topic")
        parsed = _as_record(boundary)
        start_trace_id = _clean_text(parsed.get("start_trace_id"))
        title = _clean_text(parsed.get("topic_title"))
        reason = _clean_text(parsed.get("reason"))
        confidence = _confidence(parsed.get("confidence"))
        tags = _text_list(parsed.get("tags"))

        if not start_trace_id:
            return None, "start_trace_id is required."
        if start_trace_id not in source_trace_ids:
            return None, f"start_trace_id is not in source traces: {start_trace_id}"
        if not title:
            return None, "topic_title is required."

        connection.execute(
            """
            INSERT INTO topic_boundaries (
                id,
                trace_id,
                conversation_id,
                run_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                start_trace_id,
                conversation_id,
                run_id,
                tool_call_id,
                title,
                reason,
                confidence,
                json.dumps(tags, ensure_ascii=False),
                "valid",
                None,
                json.dumps(raw_arguments, ensure_ascii=False),
                now,
            ),
        )
        return (
            TopicBoundaryRecord(
                id=record_id,
                trace_id=start_trace_id,
                conversation_id=conversation_id,
                run_id=run_id,
                topic_title=title,
                reason=reason,
                confidence=confidence,
                tags=tags,
                status="valid",
                error=None,
                created_at=now,
            ),
            None,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _auto_detection_state_from_row(row: sqlite3.Row) -> TopicBoundaryAutoDetectionState:
    return TopicBoundaryAutoDetectionState(
        id=row["id"],
        conversation_id=row["conversation_id"],
        last_source_trace_id=row["last_source_trace_id"],
        last_source_trace_created_at=row["last_source_trace_created_at"],
        last_detection_trace_id=row["last_detection_trace_id"],
        updated_at=row["updated_at"],
    )


def _auto_detection_state_id(conversation_id: str) -> str:
    return f"{TOPIC_BOUNDARY_DETECTION_STATE_ID_PREFIX}_{conversation_id}"


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _boundary_validation_error(
    boundary: dict[str, Any],
    source_trace_ids: set[str],
) -> str | None:
    start_trace_id = _clean_text(boundary.get("start_trace_id"))
    title = _clean_text(boundary.get("topic_title"))
    if not start_trace_id:
        return "start_trace_id is required."
    if start_trace_id not in source_trace_ids:
        return f"start_trace_id is not in source traces: {start_trace_id}"
    if not title:
        return "topic_title is required."
    return None


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
