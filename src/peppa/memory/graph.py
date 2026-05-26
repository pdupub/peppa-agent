from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import re
import sqlite3
import uuid

from peppa.identity import ensure_identity_schema
from peppa.memory.normalization import normalize_memory_graph_arguments
from peppa.memory.schema import MEMORY_TABLE_DELETE_ORDER, ensure_memory_graph_schema
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

            arguments = normalize_memory_graph_arguments(tool_call.arguments)
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
            tags = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT
                        id,
                        name,
                        normalized_name,
                        kind,
                        mention_count,
                        created_at,
                        updated_at
                    FROM memory_tags
                    WHERE status = 'active'
                    ORDER BY mention_count DESC, updated_at DESC, name ASC
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
                    WHERE tag.status = 'active'
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
                    WHERE tag.status = 'active'
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
                        (SELECT COUNT(*) FROM memory_tags WHERE status = 'active') AS tags,
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
            "tags": tags,
            "stats": stats,
        }

    def delete_node(self, node_id: str) -> bool:
        clean_node_id = _clean_text(node_id)
        if not clean_node_id:
            return False

        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            ensure_identity_schema(connection)
            node = connection.execute(
                """
                SELECT id
                FROM memory_nodes
                WHERE id = ? AND status = 'active'
                """,
                (clean_node_id,),
            ).fetchone()
            if node is None:
                return False

            edge_ids = [
                row["id"]
                for row in connection.execute(
                    """
                    SELECT id
                    FROM memory_edges
                    WHERE status = 'active'
                        AND (source_node_id = ? OR target_node_id = ?)
                    """,
                    (clean_node_id, clean_node_id),
                ).fetchall()
            ]
            affected_tag_ids = set(_tag_ids_for_nodes(connection, [clean_node_id]))
            affected_tag_ids.update(_tag_ids_for_edges(connection, edge_ids))

            if edge_ids:
                placeholders = _placeholders_from_ids(edge_ids)
                connection.execute(
                    f"DELETE FROM memory_edge_tags WHERE edge_id IN ({placeholders})",
                    edge_ids,
                )
                connection.execute(
                    f"""
                    UPDATE memory_edges
                    SET status = 'deleted',
                        updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    [now, *edge_ids],
                )

            connection.execute(
                "DELETE FROM memory_node_tags WHERE node_id = ?",
                (clean_node_id,),
            )
            connection.execute(
                """
                UPDATE memory_nodes
                SET status = 'deleted',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, clean_node_id),
            )
            _clear_identity_bindings(connection, [clean_node_id], now)
            _delete_orphan_tags(connection, affected_tag_ids, now)

        return True

    def delete_edge(self, edge_id: str) -> bool:
        clean_edge_id = _clean_text(edge_id)
        if not clean_edge_id:
            return False

        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            ensure_identity_schema(connection)
            edge = connection.execute(
                """
                SELECT id, source_node_id, target_node_id
                FROM memory_edges
                WHERE id = ? AND status = 'active'
                """,
                (clean_edge_id,),
            ).fetchone()
            if edge is None:
                return False

            endpoint_ids = _unique_texts([edge["source_node_id"], edge["target_node_id"]])
            affected_tag_ids = set(_tag_ids_for_edges(connection, [clean_edge_id]))
            connection.execute(
                "DELETE FROM memory_edge_tags WHERE edge_id = ?",
                (clean_edge_id,),
            )
            connection.execute(
                """
                UPDATE memory_edges
                SET status = 'deleted',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, clean_edge_id),
            )

            orphan_node_ids = [
                node_id
                for node_id in endpoint_ids
                if _is_active_orphan_node(connection, node_id)
            ]
            affected_tag_ids.update(_tag_ids_for_nodes(connection, orphan_node_ids))
            if orphan_node_ids:
                placeholders = _placeholders_from_ids(orphan_node_ids)
                connection.execute(
                    f"DELETE FROM memory_node_tags WHERE node_id IN ({placeholders})",
                    orphan_node_ids,
                )
                connection.execute(
                    f"""
                    UPDATE memory_nodes
                    SET status = 'deleted',
                        updated_at = ?
                    WHERE id IN ({placeholders})
                        AND status = 'active'
                    """,
                    [now, *orphan_node_ids],
                )
                _clear_identity_bindings(connection, orphan_node_ids, now)

            _delete_orphan_tags(connection, affected_tag_ids, now)

        return True

    def update_node_summary(self, node_id: str, summary: str) -> bool:
        clean_node_id = _clean_text(node_id)
        if not clean_node_id:
            return False

        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            node = connection.execute(
                """
                SELECT id
                FROM memory_nodes
                WHERE id = ? AND status = 'active'
                """,
                (clean_node_id,),
            ).fetchone()
            if node is None:
                return False
            connection.execute(
                """
                UPDATE memory_nodes
                SET summary = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (_clean_text(summary), now, clean_node_id),
            )
        return True

    def update_edge_summary(self, edge_id: str, summary: str) -> bool:
        clean_edge_id = _clean_text(edge_id)
        if not clean_edge_id:
            return False

        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            edge = connection.execute(
                """
                SELECT id
                FROM memory_edges
                WHERE id = ? AND status = 'active'
                """,
                (clean_edge_id,),
            ).fetchone()
            if edge is None:
                return False
            connection.execute(
                """
                UPDATE memory_edges
                SET summary = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (_clean_text(summary), now, clean_edge_id),
            )
        return True

    def update_tag(self, tag_id: str, *, name: str | None = None, kind: str | None = None) -> bool:
        clean_tag_id = _clean_text(tag_id)
        if not clean_tag_id:
            return False

        clean_name = None if name is None else _clean_text(name)
        if name is not None and not clean_name:
            raise ValueError("Tag name cannot be empty.")
        clean_kind = None if kind is None else _enum_value(kind, TAG_KINDS, "")
        if kind is not None and not clean_kind:
            raise ValueError("Invalid tag kind.")

        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            tag = connection.execute(
                """
                SELECT id, name, kind
                FROM memory_tags
                WHERE id = ? AND status = 'active'
                """,
                (clean_tag_id,),
            ).fetchone()
            if tag is None:
                return False

            next_name = clean_name if clean_name is not None else tag["name"]
            next_kind = clean_kind if clean_kind is not None else tag["kind"]
            conflict = connection.execute(
                """
                SELECT id
                FROM memory_tags
                WHERE normalized_name = ? AND id != ?
                """,
                (_tag_identity(next_name), clean_tag_id),
            ).fetchone()
            if conflict is not None:
                raise ValueError("Another tag already uses this name. Merge tags instead.")

            connection.execute(
                """
                UPDATE memory_tags
                SET name = ?,
                    normalized_name = ?,
                    kind = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (next_name, _tag_identity(next_name), next_kind, now, clean_tag_id),
            )
        return True

    def merge_tags(self, source_tag_id: str, target_tag_id: str) -> bool:
        clean_source_id = _clean_text(source_tag_id)
        clean_target_id = _clean_text(target_tag_id)
        if not clean_source_id or not clean_target_id:
            return False
        if clean_source_id == clean_target_id:
            raise ValueError("Cannot merge a tag into itself.")

        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            source = _active_row_by_id(connection, "memory_tags", clean_source_id)
            target = _active_row_by_id(connection, "memory_tags", clean_target_id)
            if source is None or target is None:
                return False

            _merge_tag_links(
                connection,
                table_name="memory_node_tags",
                owner_column="node_id",
                source_tag_id=clean_source_id,
                target_tag_id=clean_target_id,
                now=now,
            )
            _merge_tag_links(
                connection,
                table_name="memory_edge_tags",
                owner_column="edge_id",
                source_tag_id=clean_source_id,
                target_tag_id=clean_target_id,
                now=now,
            )
            connection.execute(
                """
                UPDATE memory_tag_observations
                SET tag_id = ?
                WHERE tag_id = ?
                """,
                (clean_target_id, clean_source_id),
            )
            connection.execute(
                """
                UPDATE memory_tags
                SET mention_count = mention_count + ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (int(source["mention_count"]), now, clean_target_id),
            )
            connection.execute(
                """
                UPDATE memory_tags
                SET status = 'deleted',
                    merged_into_tag_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (clean_target_id, now, clean_source_id),
            )
        return True

    def merge_nodes(self, source_node_id: str, target_node_id: str) -> bool:
        clean_source_id = _clean_text(source_node_id)
        clean_target_id = _clean_text(target_node_id)
        if not clean_source_id or not clean_target_id:
            return False
        if clean_source_id == clean_target_id:
            raise ValueError("Cannot merge a node into itself.")

        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            ensure_identity_schema(connection)
            source = _active_row_by_id(connection, "memory_nodes", clean_source_id)
            target = _active_row_by_id(connection, "memory_nodes", clean_target_id)
            if source is None or target is None:
                return False

            _merge_node_tag_links(
                connection,
                source_node_id=clean_source_id,
                target_node_id=clean_target_id,
                now=now,
            )
            connection.execute(
                """
                UPDATE memory_node_observations
                SET resolved_node_id = ?
                WHERE resolved_node_id = ?
                """,
                (clean_target_id, clean_source_id),
            )
            connection.execute(
                """
                UPDATE memory_edge_observations
                SET source_node_id = CASE WHEN source_node_id = ? THEN ? ELSE source_node_id END,
                    target_node_id = CASE WHEN target_node_id = ? THEN ? ELSE target_node_id END
                WHERE source_node_id = ? OR target_node_id = ?
                """,
                (
                    clean_source_id,
                    clean_target_id,
                    clean_source_id,
                    clean_target_id,
                    clean_source_id,
                    clean_source_id,
                ),
            )
            _redirect_edges_for_node_merge(
                connection,
                source_node_id=clean_source_id,
                target_node_id=clean_target_id,
                now=now,
            )
            _rebind_identity_bindings(connection, clean_source_id, clean_target_id, now)
            connection.execute(
                """
                UPDATE memory_nodes
                SET summary = ?,
                    confidence = ?,
                    mention_count = mention_count + ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _append_summary(target["summary"], source["summary"]),
                    max(_confidence(target["confidence"]), _confidence(source["confidence"])),
                    int(source["mention_count"]),
                    now,
                    clean_target_id,
                ),
            )
            connection.execute(
                """
                UPDATE memory_nodes
                SET status = 'deleted',
                    merged_into_node_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (clean_target_id, now, clean_source_id),
            )
        return True

    def merge_edges(self, source_edge_id: str, target_edge_id: str) -> bool:
        clean_source_id = _clean_text(source_edge_id)
        clean_target_id = _clean_text(target_edge_id)
        if not clean_source_id or not clean_target_id:
            return False
        if clean_source_id == clean_target_id:
            raise ValueError("Cannot merge an edge into itself.")

        now = _now()
        with self._connect() as connection:
            ensure_memory_graph_schema(connection)
            source = _active_row_by_id(connection, "memory_edges", clean_source_id)
            target = _active_row_by_id(connection, "memory_edges", clean_target_id)
            if source is None or target is None:
                return False
            _merge_edge_rows(
                connection,
                source_edge=source,
                target_edge=target,
                now=now,
            )
        return True

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
        normalized_name = _tag_identity(name)
        row, redirected = _find_tag_by_identity(connection, normalized_name)
        if row:
            if redirected:
                connection.execute(
                    """
                    UPDATE memory_tags
                    SET status = 'active',
                        mention_count = mention_count + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, row["id"]),
                )
                return row["id"], "matched_existing"
            connection.execute(
                """
                UPDATE memory_tags
                SET name = ?,
                    kind = ?,
                    status = 'active',
                    mention_count = mention_count + 1,
                    merged_into_tag_id = NULL,
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
                status,
                mention_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tag_id, name, normalized_name, kind, "active", 1, now, now),
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
        row, redirected = _find_node_by_identity(connection, node_type, normalized_title)
        if row:
            existing_confidence = _confidence(row["confidence"])
            next_summary = _append_summary(row["summary"], summary)
            if redirected:
                connection.execute(
                    """
                    UPDATE memory_nodes
                    SET summary = ?,
                        confidence = ?,
                        status = 'active',
                        mention_count = mention_count + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        next_summary,
                        max(existing_confidence, confidence),
                        now,
                        row["id"],
                    ),
                )
                return row["id"], "matched_existing"
            connection.execute(
                """
                UPDATE memory_nodes
                SET title = ?,
                    summary = ?,
                    confidence = ?,
                    status = 'active',
                    mention_count = mention_count + 1,
                    merged_into_node_id = NULL,
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
        row, redirected = _find_edge_by_identity(
            connection,
            source_node_id,
            target_node_id,
            relation_type,
        )
        if row:
            if row["status"] != "active" and not redirected:
                existing_confidence = _confidence(row["confidence"])
                connection.execute(
                    """
                    UPDATE memory_edges
                    SET summary = ?,
                        confidence = ?,
                        status = 'active',
                        mention_count = mention_count + 1,
                        merged_into_edge_id = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (summary, max(existing_confidence, confidence), now, row["id"]),
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


def _tag_identity(name: str) -> str:
    return _normalize(name)


def _node_identity(node_type: str, normalized_title: str) -> tuple[str, str]:
    return _clean_text(node_type), _normalize(normalized_title)


def _edge_identity(
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
) -> tuple[str, str, str]:
    return _clean_text(source_node_id), _clean_text(target_node_id), _clean_text(relation_type)


def _find_tag_by_identity(
    connection: sqlite3.Connection,
    tag_identity: str,
) -> tuple[sqlite3.Row | None, bool]:
    row = connection.execute(
        """
        SELECT id, name, normalized_name, kind, status, mention_count, merged_into_tag_id
        FROM memory_tags
        WHERE normalized_name = ?
        """,
        (tag_identity,),
    ).fetchone()
    return _resolve_merged_row(
        connection,
        row,
        table_name="memory_tags",
        merged_column="merged_into_tag_id",
    )


def _find_node_by_identity(
    connection: sqlite3.Connection,
    node_type: str,
    normalized_title: str,
) -> tuple[sqlite3.Row | None, bool]:
    identity = _node_identity(node_type, normalized_title)
    row = connection.execute(
        """
        SELECT
            id,
            type,
            title,
            normalized_title,
            summary,
            confidence,
            status,
            mention_count,
            merged_into_node_id
        FROM memory_nodes
        WHERE type = ? AND normalized_title = ?
        """,
        identity,
    ).fetchone()
    return _resolve_merged_row(
        connection,
        row,
        table_name="memory_nodes",
        merged_column="merged_into_node_id",
    )


def _find_edge_by_identity(
    connection: sqlite3.Connection,
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
) -> tuple[sqlite3.Row | None, bool]:
    identity = _edge_identity(source_node_id, target_node_id, relation_type)
    row = connection.execute(
        """
        SELECT
            id,
            source_node_id,
            target_node_id,
            relation_type,
            summary,
            confidence,
            status,
            mention_count,
            merged_into_edge_id
        FROM memory_edges
        WHERE source_node_id = ? AND target_node_id = ? AND relation_type = ?
        """,
        identity,
    ).fetchone()
    return _resolve_merged_row(
        connection,
        row,
        table_name="memory_edges",
        merged_column="merged_into_edge_id",
    )


def _resolve_merged_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row | None,
    *,
    table_name: str,
    merged_column: str,
) -> tuple[sqlite3.Row | None, bool]:
    redirected = False
    seen_ids: set[str] = set()
    while row is not None and row[merged_column]:
        next_id = _clean_text(row[merged_column])
        if not next_id or next_id in seen_ids:
            break
        seen_ids.add(next_id)
        next_row = connection.execute(
            f"""
            SELECT *
            FROM {table_name}
            WHERE id = ?
            """,
            (next_id,),
        ).fetchone()
        if next_row is None:
            break
        row = next_row
        redirected = True
    return row, redirected


def _active_row_by_id(
    connection: sqlite3.Connection,
    table_name: str,
    row_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        f"""
        SELECT *
        FROM {table_name}
        WHERE id = ? AND status = 'active'
        """,
        (_clean_text(row_id),),
    ).fetchone()


def _append_summary(existing_summary: Any, next_summary: Any) -> str:
    existing = _clean_text(existing_summary)
    incoming = _clean_text(next_summary)
    if not existing:
        return incoming
    if not incoming:
        return existing
    return f"{existing}\n\n{incoming}"


def _merge_reason(existing_reason: Any, next_reason: Any) -> str:
    existing = _clean_text(existing_reason)
    incoming = _clean_text(next_reason)
    if not existing:
        return incoming
    if not incoming or incoming == existing:
        return existing
    return f"{existing}; {incoming}"


def _merge_tag_links(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    owner_column: str,
    source_tag_id: str,
    target_tag_id: str,
    now: str,
) -> None:
    rows = connection.execute(
        f"""
        SELECT
            {owner_column} AS owner_id,
            confidence,
            reason,
            mention_count,
            first_seen_at,
            last_seen_at
        FROM {table_name}
        WHERE tag_id = ?
        """,
        (source_tag_id,),
    ).fetchall()
    for row in rows:
        owner_id = row["owner_id"]
        existing = connection.execute(
            f"""
            SELECT confidence, reason, mention_count, first_seen_at, last_seen_at
            FROM {table_name}
            WHERE {owner_column} = ? AND tag_id = ?
            """,
            (owner_id, target_tag_id),
        ).fetchone()
        if existing is not None:
            connection.execute(
                f"""
                UPDATE {table_name}
                SET confidence = ?,
                    reason = ?,
                    mention_count = ?,
                    first_seen_at = ?,
                    last_seen_at = ?
                WHERE {owner_column} = ? AND tag_id = ?
                """,
                (
                    max(_confidence(existing["confidence"]), _confidence(row["confidence"])),
                    _merge_reason(existing["reason"], row["reason"]),
                    int(existing["mention_count"]) + int(row["mention_count"]),
                    min(existing["first_seen_at"], row["first_seen_at"]),
                    max(existing["last_seen_at"], row["last_seen_at"], now),
                    owner_id,
                    target_tag_id,
                ),
            )
            connection.execute(
                f"""
                DELETE FROM {table_name}
                WHERE {owner_column} = ? AND tag_id = ?
                """,
                (owner_id, source_tag_id),
            )
            continue

        connection.execute(
            f"""
            UPDATE {table_name}
            SET tag_id = ?,
                last_seen_at = ?
            WHERE {owner_column} = ? AND tag_id = ?
            """,
            (target_tag_id, now, owner_id, source_tag_id),
        )


def _merge_node_tag_links(
    connection: sqlite3.Connection,
    *,
    source_node_id: str,
    target_node_id: str,
    now: str,
) -> None:
    rows = connection.execute(
        """
        SELECT tag_id, confidence, reason, mention_count, first_seen_at, last_seen_at
        FROM memory_node_tags
        WHERE node_id = ?
        """,
        (source_node_id,),
    ).fetchall()
    for row in rows:
        existing = connection.execute(
            """
            SELECT confidence, reason, mention_count, first_seen_at, last_seen_at
            FROM memory_node_tags
            WHERE node_id = ? AND tag_id = ?
            """,
            (target_node_id, row["tag_id"]),
        ).fetchone()
        if existing is not None:
            connection.execute(
                """
                UPDATE memory_node_tags
                SET confidence = ?,
                    reason = ?,
                    mention_count = ?,
                    first_seen_at = ?,
                    last_seen_at = ?
                WHERE node_id = ? AND tag_id = ?
                """,
                (
                    max(_confidence(existing["confidence"]), _confidence(row["confidence"])),
                    _merge_reason(existing["reason"], row["reason"]),
                    int(existing["mention_count"]) + int(row["mention_count"]),
                    min(existing["first_seen_at"], row["first_seen_at"]),
                    max(existing["last_seen_at"], row["last_seen_at"], now),
                    target_node_id,
                    row["tag_id"],
                ),
            )
            connection.execute(
                """
                DELETE FROM memory_node_tags
                WHERE node_id = ? AND tag_id = ?
                """,
                (source_node_id, row["tag_id"]),
            )
            continue

        connection.execute(
            """
            UPDATE memory_node_tags
            SET node_id = ?,
                last_seen_at = ?
            WHERE node_id = ? AND tag_id = ?
            """,
            (target_node_id, now, source_node_id, row["tag_id"]),
        )


def _merge_edge_tag_links(
    connection: sqlite3.Connection,
    *,
    source_edge_id: str,
    target_edge_id: str,
    now: str,
) -> None:
    rows = connection.execute(
        """
        SELECT tag_id, confidence, reason, mention_count, first_seen_at, last_seen_at
        FROM memory_edge_tags
        WHERE edge_id = ?
        """,
        (source_edge_id,),
    ).fetchall()
    for row in rows:
        existing = connection.execute(
            """
            SELECT confidence, reason, mention_count, first_seen_at, last_seen_at
            FROM memory_edge_tags
            WHERE edge_id = ? AND tag_id = ?
            """,
            (target_edge_id, row["tag_id"]),
        ).fetchone()
        if existing is not None:
            connection.execute(
                """
                UPDATE memory_edge_tags
                SET confidence = ?,
                    reason = ?,
                    mention_count = ?,
                    first_seen_at = ?,
                    last_seen_at = ?
                WHERE edge_id = ? AND tag_id = ?
                """,
                (
                    max(_confidence(existing["confidence"]), _confidence(row["confidence"])),
                    _merge_reason(existing["reason"], row["reason"]),
                    int(existing["mention_count"]) + int(row["mention_count"]),
                    min(existing["first_seen_at"], row["first_seen_at"]),
                    max(existing["last_seen_at"], row["last_seen_at"], now),
                    target_edge_id,
                    row["tag_id"],
                ),
            )
            connection.execute(
                """
                DELETE FROM memory_edge_tags
                WHERE edge_id = ? AND tag_id = ?
                """,
                (source_edge_id, row["tag_id"]),
            )
            continue

        connection.execute(
            """
            UPDATE memory_edge_tags
            SET edge_id = ?,
                last_seen_at = ?
            WHERE edge_id = ? AND tag_id = ?
            """,
            (target_edge_id, now, source_edge_id, row["tag_id"]),
        )


def _merge_edge_rows(
    connection: sqlite3.Connection,
    *,
    source_edge: sqlite3.Row,
    target_edge: sqlite3.Row,
    now: str,
) -> None:
    source_edge_id = source_edge["id"]
    target_edge_id = target_edge["id"]
    _merge_edge_tag_links(
        connection,
        source_edge_id=source_edge_id,
        target_edge_id=target_edge_id,
        now=now,
    )
    connection.execute(
        """
        UPDATE memory_edge_observations
        SET resolved_edge_id = ?
        WHERE resolved_edge_id = ?
        """,
        (target_edge_id, source_edge_id),
    )
    connection.execute(
        """
        UPDATE memory_edges
        SET summary = ?,
            confidence = ?,
            status = 'active',
            mention_count = mention_count + ?,
            merged_into_edge_id = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (
            _append_summary(target_edge["summary"], source_edge["summary"]),
            max(_confidence(target_edge["confidence"]), _confidence(source_edge["confidence"])),
            int(source_edge["mention_count"]),
            now,
            target_edge_id,
        ),
    )
    connection.execute(
        """
        UPDATE memory_edges
        SET status = 'deleted',
            merged_into_edge_id = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (target_edge_id, now, source_edge_id),
    )


def _redirect_edges_for_node_merge(
    connection: sqlite3.Connection,
    *,
    source_node_id: str,
    target_node_id: str,
    now: str,
) -> None:
    affected_tag_ids: set[str] = set()
    edges = connection.execute(
        """
        SELECT *
        FROM memory_edges
        WHERE status = 'active'
            AND (source_node_id = ? OR target_node_id = ?)
        ORDER BY created_at ASC
        """,
        (source_node_id, source_node_id),
    ).fetchall()
    for edge in edges:
        next_source_id = target_node_id if edge["source_node_id"] == source_node_id else edge["source_node_id"]
        next_target_id = target_node_id if edge["target_node_id"] == source_node_id else edge["target_node_id"]
        if next_source_id == next_target_id:
            affected_tag_ids.update(_tag_ids_for_edges(connection, [edge["id"]]))
            connection.execute(
                """
                UPDATE memory_edges
                SET status = 'deleted',
                    merged_into_edge_id = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, edge["id"]),
            )
            connection.execute("DELETE FROM memory_edge_tags WHERE edge_id = ?", (edge["id"],))
            continue

        matching_edge, _ = _find_edge_by_identity(
            connection,
            next_source_id,
            next_target_id,
            edge["relation_type"],
        )
        if matching_edge is not None and matching_edge["id"] != edge["id"]:
            _merge_edge_rows(
                connection,
                source_edge=edge,
                target_edge=matching_edge,
                now=now,
            )
            continue

        connection.execute(
            """
            UPDATE memory_edges
            SET source_node_id = ?,
                target_node_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (next_source_id, next_target_id, now, edge["id"]),
        )
    _delete_orphan_tags(connection, affected_tag_ids, now)


def _tag_ids_for_nodes(connection: sqlite3.Connection, node_ids: list[str]) -> list[str]:
    clean_ids = _unique_texts(node_ids)
    if not clean_ids:
        return []
    return [
        row["tag_id"]
        for row in connection.execute(
            f"""
            SELECT DISTINCT tag_id
            FROM memory_node_tags
            WHERE node_id IN ({_placeholders_from_ids(clean_ids)})
            """,
            clean_ids,
        ).fetchall()
    ]


def _tag_ids_for_edges(connection: sqlite3.Connection, edge_ids: list[str]) -> list[str]:
    clean_ids = _unique_texts(edge_ids)
    if not clean_ids:
        return []
    return [
        row["tag_id"]
        for row in connection.execute(
            f"""
            SELECT DISTINCT tag_id
            FROM memory_edge_tags
            WHERE edge_id IN ({_placeholders_from_ids(clean_ids)})
            """,
            clean_ids,
        ).fetchall()
    ]


def _is_active_orphan_node(connection: sqlite3.Connection, node_id: str) -> bool:
    node = connection.execute(
        """
        SELECT id
        FROM memory_nodes
        WHERE id = ? AND status = 'active'
        """,
        (node_id,),
    ).fetchone()
    if node is None:
        return False
    edge = connection.execute(
        """
        SELECT id
        FROM memory_edges
        WHERE status = 'active'
            AND (source_node_id = ? OR target_node_id = ?)
        LIMIT 1
        """,
        (node_id, node_id),
    ).fetchone()
    return edge is None


def _clear_identity_bindings(
    connection: sqlite3.Connection,
    node_ids: list[str],
    now: str,
) -> None:
    clean_ids = _unique_texts(node_ids)
    if not clean_ids:
        return
    connection.execute(
        f"""
        UPDATE conversation_context_identities
        SET memory_node_id = NULL,
            updated_at = ?
        WHERE memory_node_id IN ({_placeholders_from_ids(clean_ids)})
        """,
        [now, *clean_ids],
    )


def _rebind_identity_bindings(
    connection: sqlite3.Connection,
    source_node_id: str,
    target_node_id: str,
    now: str,
) -> None:
    connection.execute(
        """
        UPDATE conversation_context_identities
        SET memory_node_id = ?,
            updated_at = ?
        WHERE memory_node_id = ?
        """,
        (target_node_id, now, source_node_id),
    )


def _delete_orphan_tags(
    connection: sqlite3.Connection,
    tag_ids: set[str],
    now: str,
) -> None:
    clean_ids = _unique_texts(list(tag_ids))
    if not clean_ids:
        return

    orphan_ids = [
        tag_id
        for tag_id in clean_ids
        if not _tag_has_links(connection, tag_id)
    ]
    if not orphan_ids:
        return

    connection.execute(
        f"""
        UPDATE memory_tags
        SET status = 'deleted',
            updated_at = ?
        WHERE id IN ({_placeholders_from_ids(orphan_ids)})
        """,
        [now, *orphan_ids],
    )


def _tag_has_links(connection: sqlite3.Connection, tag_id: str) -> bool:
    node_link = connection.execute(
        """
        SELECT node_id
        FROM memory_node_tags
        WHERE tag_id = ?
        LIMIT 1
        """,
        (tag_id,),
    ).fetchone()
    if node_link is not None:
        return True
    edge_link = connection.execute(
        """
        SELECT edge_id
        FROM memory_edge_tags
        WHERE tag_id = ?
        LIMIT 1
        """,
        (tag_id,),
    ).fetchone()
    return edge_link is not None


def _placeholders_from_ids(items: list[str]) -> str:
    return ", ".join("?" for _ in items)


def _unique_texts(items: list[str]) -> list[str]:
    seen = set()
    unique_items = []
    for item in items:
        clean_item = _clean_text(item)
        if not clean_item or clean_item in seen:
            continue
        seen.add(clean_item)
        unique_items.append(clean_item)
    return unique_items


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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
