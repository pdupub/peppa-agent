from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import re
import sqlite3
import uuid

from peppa.paths import DATABASE_PATH


DEFAULT_USER_IDENTITY = "用户"
GENERIC_PERSON_TITLES = {
    "user",
    "current user",
    "unknown user",
    "unnamed user",
    "使用者",
    "当前用户",
    "未知用户",
    "用户",
}


def ensure_identity_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversation_context_identities (
            id TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            channel_instance TEXT NOT NULL,
            memory_node_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(channel, channel_instance),
            FOREIGN KEY (memory_node_id)
                REFERENCES memory_nodes(id)
                ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_conversation_context_identities_node
            ON conversation_context_identities(memory_node_id);
        """
    )


@dataclass(frozen=True)
class ConversationIdentity:
    id: str
    channel: str
    channel_instance: str
    memory_node_id: str | None
    current_user_identity: str
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "channel": self.channel,
            "channel_instance": self.channel_instance,
            "memory_node_id": self.memory_node_id,
            "current_user_identity": self.current_user_identity,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class IdentityCandidateNode:
    id: str
    title: str
    summary: str
    confidence: float
    mention_count: int
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "confidence": self.confidence,
            "mention_count": self.mention_count,
            "updated_at": self.updated_at,
        }


class ConversationIdentityStore:
    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        with self._connect() as connection:
            ensure_identity_schema(connection)

    def get_or_create_identity(
        self,
        *,
        channel: str,
        channel_instance: str,
    ) -> ConversationIdentity:
        clean_channel = _clean_required_text(channel, "channel")
        clean_channel_instance = _clean_required_text(channel_instance, "channel_instance")
        with self._connect() as connection:
            ensure_identity_schema(connection)
            row = self._identity_row(
                connection,
                channel=clean_channel,
                channel_instance=clean_channel_instance,
            )
            if row is None:
                now = _now()
                identity_id = _new_id("identity")
                connection.execute(
                    """
                    INSERT INTO conversation_context_identities (
                        id,
                        channel,
                        channel_instance,
                        memory_node_id,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identity_id,
                        clean_channel,
                        clean_channel_instance,
                        None,
                        now,
                        now,
                    ),
                )
                row = self._identity_row(
                    connection,
                    channel=clean_channel,
                    channel_instance=clean_channel_instance,
                )
            if row is None:
                raise ValueError("Failed to create conversation identity.")
            return _identity_from_row(row)

    def list_person_candidates(self) -> list[IdentityCandidateNode]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    title,
                    summary,
                    confidence,
                    mention_count,
                    updated_at
                FROM memory_nodes
                WHERE type = 'person'
                    AND status = 'active'
                    AND normalized_title != 'peppa'
                ORDER BY mention_count DESC, updated_at DESC, title ASC
                """
            ).fetchall()
        return [_candidate_from_row(row) for row in rows]

    def bind_identity(
        self,
        *,
        channel: str,
        channel_instance: str,
        memory_node_id: str,
        title: str,
    ) -> ConversationIdentity:
        clean_channel = _clean_required_text(channel, "channel")
        clean_channel_instance = _clean_required_text(channel_instance, "channel_instance")
        clean_node_id = _clean_required_text(memory_node_id, "memory_node_id")
        clean_title = _clean_required_text(title, "title")
        normalized_title = _normalize(clean_title)
        now = _now()

        with self._connect() as connection:
            ensure_identity_schema(connection)
            node = connection.execute(
                """
                SELECT id, type, title, normalized_title
                FROM memory_nodes
                WHERE id = ? AND status = 'active'
                """,
                (clean_node_id,),
            ).fetchone()
            if node is None:
                raise ValueError(f"Memory node does not exist: {clean_node_id}")
            if node["type"] != "person":
                raise ValueError("Conversation identity can only bind to a person node.")
            if _normalize(node["title"]) == "peppa":
                raise ValueError("Conversation identity cannot bind to Peppa's own node.")

            existing_normalized_title = _normalize(node["title"])
            if normalized_title != existing_normalized_title:
                if existing_normalized_title not in GENERIC_PERSON_TITLES:
                    raise ValueError(
                        "Refusing to rename a non-generic person node during identity binding."
                    )
                conflict = connection.execute(
                    """
                    SELECT id
                    FROM memory_nodes
                    WHERE type = 'person'
                        AND normalized_title = ?
                        AND id != ?
                    """,
                    (normalized_title, clean_node_id),
                ).fetchone()
                if conflict is not None:
                    raise ValueError("Another person node already uses this title.")
                connection.execute(
                    """
                    UPDATE memory_nodes
                    SET title = ?,
                        normalized_title = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (clean_title, normalized_title, now, clean_node_id),
                )

            identity = self._identity_row(
                connection,
                channel=clean_channel,
                channel_instance=clean_channel_instance,
            )
            if identity is None:
                connection.execute(
                    """
                    INSERT INTO conversation_context_identities (
                        id,
                        channel,
                        channel_instance,
                        memory_node_id,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("identity"),
                        clean_channel,
                        clean_channel_instance,
                        clean_node_id,
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE conversation_context_identities
                    SET memory_node_id = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (clean_node_id, now, identity["id"]),
                )

            row = self._identity_row(
                connection,
                channel=clean_channel,
                channel_instance=clean_channel_instance,
            )
            if row is None:
                raise ValueError("Failed to update conversation identity.")
            return _identity_from_row(row)

    def bind_identity_from_tool_arguments(
        self,
        *,
        channel: str,
        channel_instance: str,
        arguments: dict[str, Any],
    ) -> ConversationIdentity:
        return self.bind_identity(
            channel=channel,
            channel_instance=channel_instance,
            memory_node_id=_clean_required_text(arguments.get("memory_node_id"), "memory_node_id"),
            title=_clean_required_text(arguments.get("title"), "title"),
        )

    def _identity_row(
        self,
        connection: sqlite3.Connection,
        *,
        channel: str,
        channel_instance: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT
                identity.id,
                identity.channel,
                identity.channel_instance,
                CASE
                    WHEN node.id IS NULL THEN NULL
                    ELSE identity.memory_node_id
                END AS memory_node_id,
                COALESCE(node.title, ?) AS current_user_identity,
                identity.created_at,
                identity.updated_at
            FROM conversation_context_identities AS identity
            LEFT JOIN memory_nodes AS node
                ON node.id = identity.memory_node_id
                AND node.status = 'active'
            WHERE identity.channel = ?
                AND identity.channel_instance = ?
            """,
            (DEFAULT_USER_IDENTITY, channel, channel_instance),
        ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _identity_from_row(row: sqlite3.Row) -> ConversationIdentity:
    return ConversationIdentity(
        id=row["id"],
        channel=row["channel"],
        channel_instance=row["channel_instance"],
        memory_node_id=row["memory_node_id"],
        current_user_identity=row["current_user_identity"] or DEFAULT_USER_IDENTITY,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _candidate_from_row(row: sqlite3.Row) -> IdentityCandidateNode:
    return IdentityCandidateNode(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        confidence=row["confidence"],
        mention_count=row["mention_count"],
        updated_at=row["updated_at"],
    )


def _clean_required_text(value: Any, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
