from __future__ import annotations

import sqlite3


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
            status TEXT NOT NULL DEFAULT 'active',
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

        CREATE TABLE IF NOT EXISTS memory_auto_extraction_state (
            id TEXT PRIMARY KEY,
            last_source_trace_id TEXT,
            last_source_trace_created_at TEXT,
            last_extraction_trace_id TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (last_source_trace_id) REFERENCES traces(id),
            FOREIGN KEY (last_extraction_trace_id) REFERENCES traces(id)
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
    _ensure_column(
        connection,
        table_name="memory_tags",
        column_name="status",
        column_definition="TEXT NOT NULL DEFAULT 'active'",
    )


MEMORY_TABLE_DELETE_ORDER = (
    "memory_auto_extraction_state",
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


def _ensure_column(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(row["name"] == column_name for row in columns):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
