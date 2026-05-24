from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import sqlite3

from peppa.memory.schema import ensure_memory_graph_schema
from peppa.memory.storage import TraceRecord
from peppa.paths import DATABASE_PATH


AUTO_MEMORY_EXTRACTION_STATE_ID = "default"
AUTO_MEMORY_EXTRACTION_TURN_THRESHOLD = 5


@dataclass(frozen=True)
class MemoryAutoExtractionState:
    id: str
    last_source_trace_id: str | None
    last_source_trace_created_at: str | None
    last_extraction_trace_id: str | None
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "last_source_trace_id": self.last_source_trace_id,
            "last_source_trace_created_at": self.last_source_trace_created_at,
            "last_extraction_trace_id": self.last_extraction_trace_id,
            "updated_at": self.updated_at,
        }


class MemoryAutoExtractionStore:
    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)

    def get_state(self) -> MemoryAutoExtractionState | None:
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            row = connection.execute(
                """
                SELECT *
                FROM memory_auto_extraction_state
                WHERE id = ?
                """,
                (AUTO_MEMORY_EXTRACTION_STATE_ID,),
            ).fetchone()
        if row is None:
            return None
        return _state_from_row(row)

    def mark_extracted(
        self,
        *,
        last_source_trace: TraceRecord,
        extraction_trace_id: str,
    ) -> MemoryAutoExtractionState:
        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            connection.execute(
                """
                INSERT INTO memory_auto_extraction_state (
                    id,
                    last_source_trace_id,
                    last_source_trace_created_at,
                    last_extraction_trace_id,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_source_trace_id = excluded.last_source_trace_id,
                    last_source_trace_created_at = excluded.last_source_trace_created_at,
                    last_extraction_trace_id = excluded.last_extraction_trace_id,
                    updated_at = excluded.updated_at
                """,
                (
                    AUTO_MEMORY_EXTRACTION_STATE_ID,
                    last_source_trace.id,
                    last_source_trace.created_at,
                    extraction_trace_id,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM memory_auto_extraction_state
                WHERE id = ?
                """,
                (AUTO_MEMORY_EXTRACTION_STATE_ID,),
            ).fetchone()
        if row is None:
            raise ValueError("Failed to update auto memory extraction state.")
        return _state_from_row(row)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _state_from_row(row: sqlite3.Row) -> MemoryAutoExtractionState:
    return MemoryAutoExtractionState(
        id=row["id"],
        last_source_trace_id=row["last_source_trace_id"],
        last_source_trace_created_at=row["last_source_trace_created_at"],
        last_extraction_trace_id=row["last_extraction_trace_id"],
        updated_at=row["updated_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
