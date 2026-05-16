from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import re
import sqlite3
import uuid

from peppa.identity import ensure_identity_schema
from peppa.memory.tool_schema import (
    DOCUMENT_TYPES,
    EDGE_RELATION_TYPES,
    MEMORY_TOOL_NAME,
    NODE_TYPES,
    RETENTION_VALUES,
    SEGMENT_CATEGORIES,
    TAG_KINDS,
)
from peppa.models.tool_calls import ToolCall
from peppa.paths import DATABASE_PATH


def ensure_memory_graph_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(type, normalized_title)
        );

        CREATE TABLE IF NOT EXISTS memory_edges (
            id TEXT PRIMARY KEY,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_node_id, target_node_id, relation_type),
            FOREIGN KEY (source_node_id) REFERENCES memory_nodes(id),
            FOREIGN KEY (target_node_id) REFERENCES memory_nodes(id)
        );

        CREATE TABLE IF NOT EXISTS memory_tags (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_node_tags (
            node_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (node_id, tag_id),
            FOREIGN KEY (node_id) REFERENCES memory_nodes(id),
            FOREIGN KEY (tag_id) REFERENCES memory_tags(id)
        );

        CREATE TABLE IF NOT EXISTS memory_edge_tags (
            edge_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (edge_id, tag_id),
            FOREIGN KEY (edge_id) REFERENCES memory_edges(id),
            FOREIGN KEY (tag_id) REFERENCES memory_tags(id)
        );

        CREATE TABLE IF NOT EXISTS memory_extraction_runs (
            id TEXT PRIMARY KEY,
            extraction_trace_id TEXT NOT NULL,
            model TEXT NOT NULL,
            tool_call_id TEXT,
            source_trace_ids_json TEXT NOT NULL,
            raw_arguments_json TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (extraction_trace_id) REFERENCES traces(id)
        );

        CREATE TABLE IF NOT EXISTS memory_segments (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source_trace_id TEXT,
            text TEXT NOT NULL,
            category TEXT NOT NULL,
            retention TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES memory_extraction_runs(id)
        );

        CREATE TABLE IF NOT EXISTS memory_tag_observations (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tag_id TEXT,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            kind TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            action TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES memory_extraction_runs(id),
            FOREIGN KEY (tag_id) REFERENCES memory_tags(id)
        );

        CREATE TABLE IF NOT EXISTS memory_node_observations (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            candidate_ref TEXT,
            resolved_node_id TEXT,
            action TEXT NOT NULL,
            source_trace_id TEXT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            summary TEXT NOT NULL,
            source_quote TEXT NOT NULL,
            confidence REAL NOT NULL,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES memory_extraction_runs(id),
            FOREIGN KEY (resolved_node_id) REFERENCES memory_nodes(id)
        );

        CREATE TABLE IF NOT EXISTS memory_edge_observations (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            resolved_edge_id TEXT,
            action TEXT NOT NULL,
            source_trace_id TEXT,
            source_ref TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            source_node_id TEXT,
            target_node_id TEXT,
            relation_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            source_quote TEXT NOT NULL,
            confidence REAL NOT NULL,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES memory_extraction_runs(id),
            FOREIGN KEY (resolved_edge_id) REFERENCES memory_edges(id),
            FOREIGN KEY (source_node_id) REFERENCES memory_nodes(id),
            FOREIGN KEY (target_node_id) REFERENCES memory_nodes(id)
        );

        CREATE TABLE IF NOT EXISTS memory_document_suggestions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source_trace_id TEXT,
            project TEXT NOT NULL,
            document_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            source_quote TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES memory_extraction_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_memory_nodes_title
            ON memory_nodes(type, normalized_title);

        CREATE INDEX IF NOT EXISTS idx_memory_edges_nodes
            ON memory_edges(source_node_id, target_node_id);

        CREATE INDEX IF NOT EXISTS idx_memory_tags_name
            ON memory_tags(normalized_name);

        CREATE INDEX IF NOT EXISTS idx_memory_node_observations_node
            ON memory_node_observations(resolved_node_id);

        CREATE INDEX IF NOT EXISTS idx_memory_edge_observations_edge
            ON memory_edge_observations(resolved_edge_id);
        """
    )


MEMORY_TABLE_DELETE_ORDER = (
    "memory_edge_tags",
    "memory_node_tags",
    "memory_document_suggestions",
    "memory_edge_observations",
    "memory_node_observations",
    "memory_tag_observations",
    "memory_segments",
    "memory_extraction_runs",
    "memory_edges",
    "memory_nodes",
    "memory_tags",
)


class MemoryGraphStore:
    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)

    def reset_memory(self) -> None:
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            ensure_identity_schema(connection)
            connection.execute(
                """
                UPDATE conversation_context_identities
                SET memory_node_id = NULL,
                    updated_at = ?
                WHERE memory_node_id IS NOT NULL
                """,
                (_now(),),
            )
            for table_name in MEMORY_TABLE_DELETE_ORDER:
                connection.execute(f"DELETE FROM {table_name}")

    def record_tool_calls(
        self,
        *,
        extraction_trace_id: str,
        model: str,
        tool_calls: list[ToolCall],
        source_trace_ids: list[str],
    ) -> list[str]:
        run_ids = []
        for tool_call in tool_calls:
            if tool_call.name != MEMORY_TOOL_NAME:
                continue
            raw_arguments = tool_call.arguments_raw
            if tool_call.parse_error or tool_call.arguments is None:
                run_ids.append(
                    self._record_failed_run(
                        extraction_trace_id=extraction_trace_id,
                        model=model,
                        tool_call_id=tool_call.id,
                        source_trace_ids=source_trace_ids,
                        raw_arguments=raw_arguments,
                        error=tool_call.parse_error or "Tool call arguments are missing.",
                    )
                )
                continue

            # Comment out this line to use provider tool-call arguments exactly as returned.
            arguments = _normalize_memory_graph_arguments(tool_call.arguments)
            run_ids.append(
                self.record_memory_graph_update(
                    extraction_trace_id=extraction_trace_id,
                    model=model,
                    tool_call_id=tool_call.id,
                    source_trace_ids=source_trace_ids,
                    arguments=arguments,
                )
            )
        return run_ids

    def record_memory_graph_update(
        self,
        *,
        extraction_trace_id: str,
        model: str,
        tool_call_id: str | None,
        source_trace_ids: list[str],
        arguments: dict[str, Any],
    ) -> str:
        run_id = _new_id("mem_run")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_extraction_runs (
                    id,
                    extraction_trace_id,
                    model,
                    tool_call_id,
                    source_trace_ids_json,
                    raw_arguments_json,
                    status,
                    error,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    extraction_trace_id,
                    model,
                    tool_call_id,
                    _json_dumps(source_trace_ids),
                    _json_dumps(arguments),
                    "processing",
                    None,
                    now,
                ),
            )
            self._apply_arguments(
                connection=connection,
                run_id=run_id,
                source_trace_ids=source_trace_ids,
                arguments=arguments,
                now=now,
            )
            connection.execute(
                """
                UPDATE memory_extraction_runs
                SET status = ?
                WHERE id = ?
                """,
                ("completed", run_id),
            )
        return run_id

    def get_memory_graph(self) -> dict[str, Any]:
        with self._connect() as connection:
            nodes = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT
                        id,
                        type,
                        title,
                        summary,
                        confidence,
                        mention_count,
                        created_at,
                        updated_at
                    FROM memory_nodes
                    WHERE status = 'active'
                    ORDER BY mention_count DESC, updated_at DESC, title ASC
                    """
                ).fetchall()
            ]
            edges = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT
                        edge.id,
                        edge.source_node_id,
                        source.title AS source_title,
                        source.type AS source_type,
                        edge.target_node_id,
                        target.title AS target_title,
                        target.type AS target_type,
                        edge.relation_type,
                        edge.summary,
                        edge.confidence,
                        edge.mention_count,
                        edge.created_at,
                        edge.updated_at
                    FROM memory_edges AS edge
                    JOIN memory_nodes AS source
                        ON source.id = edge.source_node_id
                    JOIN memory_nodes AS target
                        ON target.id = edge.target_node_id
                    WHERE edge.status = 'active'
                    ORDER BY edge.mention_count DESC, edge.updated_at DESC, edge.relation_type ASC
                    """
                ).fetchall()
            ]

            node_tags = _group_tags(
                connection.execute(
                    """
                    SELECT
                        link.node_id AS owner_id,
                        tag.id,
                        tag.name,
                        tag.kind,
                        link.confidence,
                        link.reason,
                        link.mention_count
                    FROM memory_node_tags AS link
                    JOIN memory_tags AS tag
                        ON tag.id = link.tag_id
                    ORDER BY tag.name ASC
                    """
                ).fetchall()
            )
            edge_tags = _group_tags(
                connection.execute(
                    """
                    SELECT
                        link.edge_id AS owner_id,
                        tag.id,
                        tag.name,
                        tag.kind,
                        link.confidence,
                        link.reason,
                        link.mention_count
                    FROM memory_edge_tags AS link
                    JOIN memory_tags AS tag
                        ON tag.id = link.tag_id
                    ORDER BY tag.name ASC
                    """
                ).fetchall()
            )
            node_sources = _group_source_trace_ids(
                connection.execute(
                    """
                    SELECT resolved_node_id AS owner_id, source_trace_id
                    FROM memory_node_observations
                    WHERE resolved_node_id IS NOT NULL
                        AND source_trace_id IS NOT NULL
                    """
                ).fetchall()
            )
            edge_sources = _group_source_trace_ids(
                connection.execute(
                    """
                    SELECT resolved_edge_id AS owner_id, source_trace_id
                    FROM memory_edge_observations
                    WHERE resolved_edge_id IS NOT NULL
                        AND source_trace_id IS NOT NULL
                    """
                ).fetchall()
            )
            stats = dict(
                connection.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM memory_nodes WHERE status = 'active') AS nodes,
                        (SELECT COUNT(*) FROM memory_edges WHERE status = 'active') AS edges,
                        (SELECT COUNT(*) FROM memory_tags) AS tags,
                        (SELECT COUNT(*) FROM memory_extraction_runs) AS extraction_runs
                    """
                ).fetchone()
            )

        return {
            "nodes": [
                {
                    **node,
                    "tags": node_tags.get(node["id"], []),
                    "source_trace_ids": node_sources.get(node["id"], []),
                }
                for node in nodes
            ],
            "edges": [
                {
                    **edge,
                    "tags": edge_tags.get(edge["id"], []),
                    "source_trace_ids": edge_sources.get(edge["id"], []),
                }
                for edge in edges
            ],
            "stats": stats,
        }

    def _record_failed_run(
        self,
        *,
        extraction_trace_id: str,
        model: str,
        tool_call_id: str | None,
        source_trace_ids: list[str],
        raw_arguments: Any,
        error: str,
    ) -> str:
        run_id = _new_id("mem_run")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_extraction_runs (
                    id,
                    extraction_trace_id,
                    model,
                    tool_call_id,
                    source_trace_ids_json,
                    raw_arguments_json,
                    status,
                    error,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    extraction_trace_id,
                    model,
                    tool_call_id,
                    _json_dumps(source_trace_ids),
                    _json_dumps(raw_arguments),
                    "failed",
                    error,
                    _now(),
                ),
            )
        return run_id

    def _apply_arguments(
        self,
        *,
        connection: sqlite3.Connection,
        run_id: str,
        source_trace_ids: list[str],
        arguments: dict[str, Any],
        now: str,
    ) -> None:
        valid_source_ids = set(source_trace_ids)
        ref_to_node_id: dict[str, str] = {}

        for item in _as_list(arguments.get("segments")):
            self._insert_segment(connection, run_id, item, valid_source_ids, now)

        graph = _as_record(arguments.get("memory_graph"))

        for item in _as_list(graph.get("tags")):
            self._record_tag_observation(connection, run_id, item, now)

        for item in _as_list(graph.get("nodes")):
            ref, node_id = self._record_node_observation(
                connection, run_id, item, valid_source_ids, now
            )
            if ref and node_id:
                ref_to_node_id[ref] = node_id

        for item in _as_list(graph.get("edges")):
            self._record_edge_observation(
                connection, run_id, item, ref_to_node_id, valid_source_ids, now
            )

        for item in _as_list(arguments.get("document_suggestions")):
            self._insert_document_suggestion(connection, run_id, item, valid_source_ids, now)

    def _insert_segment(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        item: Any,
        valid_source_ids: set[str],
        now: str,
    ) -> None:
        record = _as_record(item)
        source_trace_id = _clean_text(record.get("source_trace_id"))
        status = "valid" if source_trace_id in valid_source_ids else "invalid"
        category = _enum_value(record.get("category"), SEGMENT_CATEGORIES, "other")
        retention = _enum_value(record.get("retention"), RETENTION_VALUES, "trace_only")
        connection.execute(
            """
            INSERT INTO memory_segments (
                id,
                run_id,
                source_trace_id,
                text,
                category,
                retention,
                reason,
                confidence,
                status,
                raw_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("mem_segment"),
                run_id,
                source_trace_id or None,
                _clean_text(record.get("text")),
                category,
                retention,
                _clean_text(record.get("reason")),
                _confidence(record.get("confidence")),
                status,
                _json_dumps(record),
                now,
            ),
        )

    def _record_tag_observation(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        item: Any,
        now: str,
    ) -> None:
        record = _as_record(item)
        name = _clean_text(record.get("name"))
        normalized_name = _normalize(name)
        kind = _enum_value(record.get("kind"), TAG_KINDS, "topic")
        confidence = _confidence(record.get("confidence"))
        reason = _clean_text(record.get("reason"))
        tag_id = None
        action = "invalid"

        if normalized_name:
            tag_id, action = self._upsert_tag(
                connection,
                name=name,
                kind=kind,
                now=now,
            )

        connection.execute(
            """
            INSERT INTO memory_tag_observations (
                id,
                run_id,
                tag_id,
                name,
                normalized_name,
                kind,
                confidence,
                reason,
                action,
                raw_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("mem_tag_obs"),
                run_id,
                tag_id,
                name,
                normalized_name,
                kind,
                confidence,
                reason,
                action,
                _json_dumps(record),
                now,
            ),
        )

    def _record_node_observation(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        item: Any,
        valid_source_ids: set[str],
        now: str,
    ) -> tuple[str | None, str | None]:
        record = _as_record(item)
        ref = _clean_text(record.get("ref"))
        node_type = _enum_value(record.get("type"), NODE_TYPES, "")
        title = _clean_text(record.get("title"))
        normalized_title = _normalize(title)
        source_trace_id = _clean_text(record.get("source_trace_id"))
        summary = _clean_text(record.get("summary"))
        source_quote = _clean_text(record.get("source_quote"))
        confidence = _confidence(record.get("confidence"))
        node_id = None
        action = "invalid"

        if ref and node_type and normalized_title and source_trace_id in valid_source_ids:
            node_id, action = self._upsert_node(
                connection,
                node_type=node_type,
                title=title,
                normalized_title=normalized_title,
                summary=summary,
                confidence=confidence,
                now=now,
            )
            for tag_name in _text_list(record.get("tags")):
                tag_id, _ = self._upsert_tag(
                    connection,
                    name=tag_name,
                    kind="topic",
                    now=now,
                )
                self._link_node_tag(
                    connection,
                    node_id=node_id,
                    tag_id=tag_id,
                    confidence=confidence,
                    reason=f"node:{title}",
                    now=now,
                )

        connection.execute(
            """
            INSERT INTO memory_node_observations (
                id,
                run_id,
                candidate_ref,
                resolved_node_id,
                action,
                source_trace_id,
                type,
                title,
                normalized_title,
                summary,
                source_quote,
                confidence,
                raw_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("mem_node_obs"),
                run_id,
                ref or None,
                node_id,
                action,
                source_trace_id or None,
                node_type,
                title,
                normalized_title,
                summary,
                source_quote,
                confidence,
                _json_dumps(record),
                now,
            ),
        )
        return ref or None, node_id

    def _record_edge_observation(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        item: Any,
        ref_to_node_id: dict[str, str],
        valid_source_ids: set[str],
        now: str,
    ) -> None:
        record = _as_record(item)
        source_ref = _clean_text(record.get("source_ref"))
        target_ref = _clean_text(record.get("target_ref"))
        source_trace_id = _clean_text(record.get("source_trace_id"))
        relation_type = _enum_value(record.get("relation_type"), EDGE_RELATION_TYPES, "")
        summary = _clean_text(record.get("summary"))
        source_quote = _clean_text(record.get("source_quote"))
        confidence = _confidence(record.get("confidence"))
        source_node_id = ref_to_node_id.get(source_ref)
        target_node_id = ref_to_node_id.get(target_ref)
        edge_id = None
        action = "invalid"

        if (
            source_node_id
            and target_node_id
            and relation_type
            and source_trace_id in valid_source_ids
        ):
            edge_id, action = self._upsert_edge(
                connection,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                relation_type=relation_type,
                summary=summary,
                confidence=confidence,
                now=now,
            )
            for tag_name in _text_list(record.get("tags")):
                tag_id, _ = self._upsert_tag(
                    connection,
                    name=tag_name,
                    kind="topic",
                    now=now,
                )
                self._link_edge_tag(
                    connection,
                    edge_id=edge_id,
                    tag_id=tag_id,
                    confidence=confidence,
                    reason=f"edge:{relation_type}",
                    now=now,
                )

        connection.execute(
            """
            INSERT INTO memory_edge_observations (
                id,
                run_id,
                resolved_edge_id,
                action,
                source_trace_id,
                source_ref,
                target_ref,
                source_node_id,
                target_node_id,
                relation_type,
                summary,
                source_quote,
                confidence,
                raw_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("mem_edge_obs"),
                run_id,
                edge_id,
                action,
                source_trace_id or None,
                source_ref,
                target_ref,
                source_node_id,
                target_node_id,
                relation_type,
                summary,
                source_quote,
                confidence,
                _json_dumps(record),
                now,
            ),
        )

    def _insert_document_suggestion(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        item: Any,
        valid_source_ids: set[str],
        now: str,
    ) -> None:
        record = _as_record(item)
        source_trace_id = _clean_text(record.get("source_trace_id"))
        status = "valid" if source_trace_id in valid_source_ids else "invalid"
        document_type = _enum_value(record.get("document_type"), DOCUMENT_TYPES, "other")
        connection.execute(
            """
            INSERT INTO memory_document_suggestions (
                id,
                run_id,
                source_trace_id,
                project,
                document_type,
                title,
                summary,
                source_quote,
                tags_json,
                confidence,
                reason,
                status,
                raw_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("mem_doc"),
                run_id,
                source_trace_id or None,
                _clean_text(record.get("project")),
                document_type,
                _clean_text(record.get("title")),
                _clean_text(record.get("summary")),
                _clean_text(record.get("source_quote")),
                _json_dumps(_text_list(record.get("tags"))),
                _confidence(record.get("confidence")),
                _clean_text(record.get("reason")),
                status,
                _json_dumps(record),
                now,
            ),
        )

    def _upsert_tag(
        self,
        connection: sqlite3.Connection,
        *,
        name: str,
        kind: str,
        now: str,
    ) -> tuple[str, str]:
        normalized_name = _normalize(name)
        row = connection.execute(
            """
            SELECT id
            FROM memory_tags
            WHERE normalized_name = ?
            """,
            (normalized_name,),
        ).fetchone()
        if row:
            connection.execute(
                """
                UPDATE memory_tags
                SET name = ?,
                    kind = ?,
                    mention_count = mention_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (name, kind, now, row["id"]),
            )
            return row["id"], "matched_existing"

        tag_id = _new_id("mem_tag")
        connection.execute(
            """
            INSERT INTO memory_tags (
                id,
                name,
                normalized_name,
                kind,
                mention_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tag_id, name, normalized_name, kind, 1, now, now),
        )
        return tag_id, "created"

    def _upsert_node(
        self,
        connection: sqlite3.Connection,
        *,
        node_type: str,
        title: str,
        normalized_title: str,
        summary: str,
        confidence: float,
        now: str,
    ) -> tuple[str, str]:
        row = connection.execute(
            """
            SELECT id, confidence, summary
            FROM memory_nodes
            WHERE type = ? AND normalized_title = ?
            """,
            (node_type, normalized_title),
        ).fetchone()
        if row:
            existing_confidence = _confidence(row["confidence"])
            next_summary = summary if summary and confidence >= existing_confidence else row["summary"]
            connection.execute(
                """
                UPDATE memory_nodes
                SET title = ?,
                    summary = ?,
                    confidence = ?,
                    mention_count = mention_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    next_summary,
                    max(existing_confidence, confidence),
                    now,
                    row["id"],
                ),
            )
            return row["id"], "matched_existing"

        node_id = _new_id("mem_node")
        connection.execute(
            """
            INSERT INTO memory_nodes (
                id,
                type,
                title,
                normalized_title,
                summary,
                confidence,
                status,
                mention_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                node_type,
                title,
                normalized_title,
                summary,
                confidence,
                "active",
                1,
                now,
                now,
            ),
        )
        return node_id, "created"

    def _upsert_edge(
        self,
        connection: sqlite3.Connection,
        *,
        source_node_id: str,
        target_node_id: str,
        relation_type: str,
        summary: str,
        confidence: float,
        now: str,
    ) -> tuple[str, str]:
        row = connection.execute(
            """
            SELECT id, confidence, summary
            FROM memory_edges
            WHERE source_node_id = ? AND target_node_id = ? AND relation_type = ?
            """,
            (source_node_id, target_node_id, relation_type),
        ).fetchone()
        if row:
            existing_confidence = _confidence(row["confidence"])
            next_summary = summary if summary and confidence >= existing_confidence else row["summary"]
            connection.execute(
                """
                UPDATE memory_edges
                SET summary = ?,
                    confidence = ?,
                    mention_count = mention_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (next_summary, max(existing_confidence, confidence), now, row["id"]),
            )
            return row["id"], "matched_existing"

        edge_id = _new_id("mem_edge")
        connection.execute(
            """
            INSERT INTO memory_edges (
                id,
                source_node_id,
                target_node_id,
                relation_type,
                summary,
                confidence,
                status,
                mention_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                source_node_id,
                target_node_id,
                relation_type,
                summary,
                confidence,
                "active",
                1,
                now,
                now,
            ),
        )
        return edge_id, "created"

    def _link_node_tag(
        self,
        connection: sqlite3.Connection,
        *,
        node_id: str,
        tag_id: str,
        confidence: float,
        reason: str,
        now: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT confidence
            FROM memory_node_tags
            WHERE node_id = ? AND tag_id = ?
            """,
            (node_id, tag_id),
        ).fetchone()
        if row:
            connection.execute(
                """
                UPDATE memory_node_tags
                SET confidence = ?,
                    reason = ?,
                    mention_count = mention_count + 1,
                    last_seen_at = ?
                WHERE node_id = ? AND tag_id = ?
                """,
                (max(_confidence(row["confidence"]), confidence), reason, now, node_id, tag_id),
            )
            return

        connection.execute(
            """
            INSERT INTO memory_node_tags (
                node_id,
                tag_id,
                confidence,
                reason,
                mention_count,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (node_id, tag_id, confidence, reason, 1, now, now),
        )

    def _link_edge_tag(
        self,
        connection: sqlite3.Connection,
        *,
        edge_id: str,
        tag_id: str,
        confidence: float,
        reason: str,
        now: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT confidence
            FROM memory_edge_tags
            WHERE edge_id = ? AND tag_id = ?
            """,
            (edge_id, tag_id),
        ).fetchone()
        if row:
            connection.execute(
                """
                UPDATE memory_edge_tags
                SET confidence = ?,
                    reason = ?,
                    mention_count = mention_count + 1,
                    last_seen_at = ?
                WHERE edge_id = ? AND tag_id = ?
                """,
                (max(_confidence(row["confidence"]), confidence), reason, now, edge_id, tag_id),
            )
            return

        connection.execute(
            """
            INSERT INTO memory_edge_tags (
                edge_id,
                tag_id,
                confidence,
                reason,
                mention_count,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (edge_id, tag_id, confidence, reason, 1, now, now),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _normalize_memory_graph_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(arguments)
    collected = {"tags": [], "nodes": [], "edges": []}
    _collect_memory_graph_lists(normalized, collected)

    if not any(collected.values()):
        return normalized

    memory_graph = normalized.get("memory_graph")
    if not isinstance(memory_graph, dict):
        memory_graph = {}
        normalized["memory_graph"] = memory_graph

    for key, items in collected.items():
        if not items:
            continue
        existing_items = _as_list(memory_graph.get(key))
        memory_graph[key] = _unique_records([*existing_items, *items])

    return normalized


def _collect_memory_graph_lists(value: Any, collected: dict[str, list[dict[str, Any]]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in collected:
                collected[key].extend(_graph_items(key, item))
            _collect_memory_graph_lists(item, collected)
        return

    if isinstance(value, list):
        for item in value:
            _collect_memory_graph_lists(item, collected)


def _graph_items(key: str, value: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in _as_list(value)
        if isinstance(item, dict) and _is_memory_graph_item(key, item)
    ]


def _is_memory_graph_item(key: str, item: dict[str, Any]) -> bool:
    if key == "tags":
        return bool(_clean_text(item.get("name")))
    if key == "nodes":
        return bool(
            _clean_text(item.get("ref"))
            and _clean_text(item.get("type"))
            and _clean_text(item.get("title"))
        )
    if key == "edges":
        return bool(
            _clean_text(item.get("source_ref"))
            and _clean_text(item.get("target_ref"))
            and _clean_text(item.get("relation_type"))
        )
    return False


def _unique_records(items: list[Any]) -> list[dict[str, Any]]:
    seen = set()
    unique_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        marker = _json_dumps_sorted(item)
        if marker in seen:
            continue
        seen.add(marker)
        unique_items.append(item)
    return unique_items


def _group_tags(rows: list[sqlite3.Row]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        owner_id = row["owner_id"]
        grouped.setdefault(owner_id, []).append(
            {
                "id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "confidence": row["confidence"],
                "reason": row["reason"],
                "mention_count": row["mention_count"],
            }
        )
    return grouped


def _group_source_trace_ids(rows: list[sqlite3.Row]) -> dict[str, list[str]]:
    grouped: dict[str, set[str]] = {}
    for row in rows:
        owner_id = row["owner_id"]
        source_trace_id = row["source_trace_id"]
        grouped.setdefault(owner_id, set()).add(source_trace_id)
    return {owner_id: sorted(source_ids) for owner_id, source_ids in grouped.items()}


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_list(value: Any) -> list[str]:
    return [_clean_text(item) for item in _as_list(value) if _clean_text(item)]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _enum_value(value: Any, allowed_values: list[str], fallback: str) -> str:
    text = _clean_text(value)
    return text if text in allowed_values else fallback


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_dumps_sorted(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
