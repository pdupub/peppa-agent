from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
import sqlite3

from peppa.paths import DATABASE_PATH


MAX_RECALLED_NODES = 8
MAX_RECALLED_EDGES = 8
MAX_EVIDENCE_ITEMS = 10
MIN_TAG_CHARS = 2


@dataclass(frozen=True)
class MemoryRecallResult:
    query: str
    matched_tags: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    useful_background: list[str]
    evidence: list[dict[str, Any]]
    context_text: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "matched_tags": self.matched_tags,
            "entities": self.entities,
            "relationships": self.relationships,
            "useful_background": self.useful_background,
            "evidence": self.evidence,
            "context_text": self.context_text,
        }


class MemoryRecallStore:
    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = database_path

    def recall_conversation_topic(
        self,
        *,
        conversation_id: str,
        current_user_message: str,
        prompt_history_messages: int,
    ) -> MemoryRecallResult:
        clean_message = current_user_message.strip()
        if not clean_message:
            return _empty_result(clean_message)

        recall_query = self._build_topic_recall_query(
            conversation_id=conversation_id,
            current_user_message=clean_message,
            history_user_message_limit=max(0, prompt_history_messages // 2),
        )
        return self.recall(recall_query)

    def recall(self, query: str) -> MemoryRecallResult:
        clean_query = query.strip()
        if not clean_query:
            return _empty_result(clean_query)

        with self._connect() as connection:
            matched_tags = self._match_tags(connection, clean_query)
            if not matched_tags:
                return _empty_result(clean_query)

            nodes, edges = self._build_recall_graph(connection, matched_tags)
            evidence = self._build_evidence(connection, nodes, edges, matched_tags)

        useful_background = _build_useful_background(
            query=clean_query,
            matched_tags=matched_tags,
            nodes=nodes,
            edges=edges,
        )
        context_text = _render_context_text(
            matched_tags=matched_tags,
            nodes=nodes,
            edges=edges,
            useful_background=useful_background,
            evidence=evidence,
        )
        return MemoryRecallResult(
            query=clean_query,
            matched_tags=matched_tags,
            entities=nodes,
            relationships=edges,
            useful_background=useful_background,
            evidence=evidence,
            context_text=context_text,
        )

    def _match_tags(self, connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
        normalized_query = _normalize(query)
        rows = connection.execute(
            """
            SELECT id, name, normalized_name, kind, mention_count, updated_at
            FROM memory_tags
            ORDER BY mention_count DESC, updated_at DESC, name ASC
            """
        ).fetchall()

        matched = []
        for row in rows:
            normalized_name = _clean_text(row["normalized_name"])
            if len(normalized_name.replace(" ", "")) < MIN_TAG_CHARS:
                continue
            if normalized_name not in normalized_query:
                continue
            matched.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "normalized_name": normalized_name,
                    "kind": row["kind"],
                    "mention_count": row["mention_count"],
                    "updated_at": row["updated_at"],
                    "score": _tag_score(row),
                    "matched_reason": f"用户输入命中 tag: {row['name']}",
                }
            )

        matched.sort(key=lambda item: (-item["score"], item["name"]))
        return matched

    def _build_topic_recall_query(
        self,
        *,
        conversation_id: str,
        current_user_message: str,
        history_user_message_limit: int,
    ) -> str:
        with self._connect() as connection:
            boundary_trace = connection.execute(
                """
                SELECT trace.created_at
                FROM topic_boundaries AS boundary
                JOIN traces AS trace
                    ON trace.id = boundary.trace_id
                WHERE boundary.conversation_id = ?
                    AND boundary.status = 'valid'
                ORDER BY trace.created_at DESC, boundary.created_at DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()

            params: list[Any] = [conversation_id]
            boundary_filter = ""
            if boundary_trace is not None:
                boundary_filter = "AND created_at >= ?"
                params.append(boundary_trace["created_at"])

            rows = []
            if history_user_message_limit > 0:
                rows = connection.execute(
                    f"""
                    SELECT user_message
                    FROM (
                        SELECT user_message, created_at
                        FROM traces
                        WHERE conversation_id = ?
                            {boundary_filter}
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                    ORDER BY created_at ASC
                    """,
                    [*params, history_user_message_limit],
                ).fetchall()

        messages = [_clean_text(row["user_message"]) for row in rows]
        messages.append(current_user_message)
        return "\n".join(_unique_texts([message for message in messages if message]))

    def _build_recall_graph(
        self,
        connection: sqlite3.Connection,
        matched_tags: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tag_scores = {tag["id"]: float(tag["score"]) for tag in matched_tags}
        node_scores: dict[str, float] = {}
        edge_scores: dict[str, float] = {}
        node_reasons: dict[str, list[str]] = {}
        edge_reasons: dict[str, list[str]] = {}

        for row in connection.execute(
            """
            SELECT
                link.node_id,
                link.confidence,
                link.mention_count,
                tag.id AS tag_id,
                tag.name AS tag_name
            FROM memory_node_tags AS link
            JOIN memory_tags AS tag
                ON tag.id = link.tag_id
            WHERE tag.id IN ({placeholders})
            """.format(placeholders=_placeholders(matched_tags)),
            [tag["id"] for tag in matched_tags],
        ).fetchall():
            score = tag_scores[row["tag_id"]] + 8 * _confidence(row["confidence"])
            score += min(3.0, float(row["mention_count"]) * 0.35)
            node_scores[row["node_id"]] = node_scores.get(row["node_id"], 0.0) + score
            node_reasons.setdefault(row["node_id"], []).append(f"node tag: {row['tag_name']}")

        for row in connection.execute(
            """
            SELECT
                link.edge_id,
                link.confidence,
                link.mention_count,
                tag.id AS tag_id,
                tag.name AS tag_name
            FROM memory_edge_tags AS link
            JOIN memory_tags AS tag
                ON tag.id = link.tag_id
            WHERE tag.id IN ({placeholders})
            """.format(placeholders=_placeholders(matched_tags)),
            [tag["id"] for tag in matched_tags],
        ).fetchall():
            score = tag_scores[row["tag_id"]] + 9 * _confidence(row["confidence"])
            score += min(3.0, float(row["mention_count"]) * 0.35)
            edge_scores[row["edge_id"]] = edge_scores.get(row["edge_id"], 0.0) + score
            edge_reasons.setdefault(row["edge_id"], []).append(f"edge tag: {row['tag_name']}")

        self._expand_edges_from_nodes(connection, node_scores, edge_scores, edge_reasons)
        self._include_edge_endpoints(connection, node_scores, edge_scores, node_reasons)

        nodes = self._load_nodes(connection, node_scores, node_reasons)
        edges = self._load_edges(connection, edge_scores, edge_reasons)
        return nodes[:MAX_RECALLED_NODES], edges[:MAX_RECALLED_EDGES]

    def _expand_edges_from_nodes(
        self,
        connection: sqlite3.Connection,
        node_scores: dict[str, float],
        edge_scores: dict[str, float],
        edge_reasons: dict[str, list[str]],
    ) -> None:
        if not node_scores:
            return
        rows = connection.execute(
            """
            SELECT id, source_node_id, target_node_id, confidence, mention_count
            FROM memory_edges
            WHERE status = 'active'
                AND (
                    source_node_id IN ({placeholders})
                    OR target_node_id IN ({placeholders})
                )
            """.format(placeholders=_placeholders_from_ids(node_scores)),
            [*node_scores.keys(), *node_scores.keys()],
        ).fetchall()
        for row in rows:
            if (
                row["source_node_id"] not in node_scores
                or row["target_node_id"] not in node_scores
            ):
                continue
            source_score = node_scores.get(row["source_node_id"], 0.0)
            target_score = node_scores.get(row["target_node_id"], 0.0)
            anchor_score = max(source_score, target_score)
            score = anchor_score * 0.45 + 3 * _confidence(row["confidence"])
            score += min(2.0, float(row["mention_count"]) * 0.25)
            edge_scores[row["id"]] = max(edge_scores.get(row["id"], 0.0), score)
            edge_reasons.setdefault(row["id"], []).append("1-hop from matched node")

    def _include_edge_endpoints(
        self,
        connection: sqlite3.Connection,
        node_scores: dict[str, float],
        edge_scores: dict[str, float],
        node_reasons: dict[str, list[str]],
    ) -> None:
        if not edge_scores:
            return
        rows = connection.execute(
            """
            SELECT id, source_node_id, target_node_id
            FROM memory_edges
            WHERE status = 'active'
                AND id IN ({placeholders})
            """.format(placeholders=_placeholders_from_ids(edge_scores)),
            list(edge_scores.keys()),
        ).fetchall()
        for row in rows:
            score = edge_scores[row["id"]] * 0.5
            for node_id in (row["source_node_id"], row["target_node_id"]):
                node_scores[node_id] = max(node_scores.get(node_id, 0.0), score)
                node_reasons.setdefault(node_id, []).append("endpoint of matched edge")

    def _load_nodes(
        self,
        connection: sqlite3.Connection,
        node_scores: dict[str, float],
        node_reasons: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        if not node_scores:
            return []
        rows = connection.execute(
            """
            SELECT id, type, title, summary, confidence, mention_count, created_at, updated_at
            FROM memory_nodes
            WHERE status = 'active'
                AND id IN ({placeholders})
            """.format(placeholders=_placeholders_from_ids(node_scores)),
            list(node_scores.keys()),
        ).fetchall()
        tags = _group_tags(
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
                WHERE link.node_id IN ({placeholders})
                ORDER BY link.mention_count DESC, tag.name ASC
                """.format(placeholders=_placeholders_from_ids(node_scores)),
                list(node_scores.keys()),
            ).fetchall()
        )
        source_trace_ids = _group_source_trace_ids(
            connection.execute(
                """
                SELECT resolved_node_id AS owner_id, source_trace_id
                FROM memory_node_observations
                WHERE resolved_node_id IN ({placeholders})
                    AND source_trace_id IS NOT NULL
                """.format(placeholders=_placeholders_from_ids(node_scores)),
                list(node_scores.keys()),
            ).fetchall()
        )
        nodes = []
        for row in rows:
            nodes.append(
                {
                    **dict(row),
                    "tags": tags.get(row["id"], []),
                    "source_trace_ids": source_trace_ids.get(row["id"], []),
                    "score": round(node_scores.get(row["id"], 0.0), 3),
                    "matched_reasons": _unique_texts(node_reasons.get(row["id"], [])),
                }
            )
        nodes.sort(
            key=lambda item: (
                -float(item["score"]),
                -float(item["confidence"]),
                -int(item["mention_count"]),
                item["title"],
            )
        )
        return nodes

    def _load_edges(
        self,
        connection: sqlite3.Connection,
        edge_scores: dict[str, float],
        edge_reasons: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        if not edge_scores:
            return []
        rows = connection.execute(
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
                AND edge.id IN ({placeholders})
            """.format(placeholders=_placeholders_from_ids(edge_scores)),
            list(edge_scores.keys()),
        ).fetchall()
        tags = _group_tags(
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
                WHERE link.edge_id IN ({placeholders})
                ORDER BY link.mention_count DESC, tag.name ASC
                """.format(placeholders=_placeholders_from_ids(edge_scores)),
                list(edge_scores.keys()),
            ).fetchall()
        )
        source_trace_ids = _group_source_trace_ids(
            connection.execute(
                """
                SELECT resolved_edge_id AS owner_id, source_trace_id
                FROM memory_edge_observations
                WHERE resolved_edge_id IN ({placeholders})
                    AND source_trace_id IS NOT NULL
                """.format(placeholders=_placeholders_from_ids(edge_scores)),
                list(edge_scores.keys()),
            ).fetchall()
        )
        edges = []
        for row in rows:
            edges.append(
                {
                    **dict(row),
                    "tags": tags.get(row["id"], []),
                    "source_trace_ids": source_trace_ids.get(row["id"], []),
                    "score": round(edge_scores.get(row["id"], 0.0), 3),
                    "matched_reasons": _unique_texts(edge_reasons.get(row["id"], [])),
                }
            )
        edges.sort(
            key=lambda item: (
                -float(item["score"]),
                -float(item["confidence"]),
                -int(item["mention_count"]),
                item["relation_type"],
            )
        )
        return edges

    def _build_evidence(
        self,
        connection: sqlite3.Connection,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        matched_tags: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence = []
        matched_normalized_tags = [tag["normalized_name"] for tag in matched_tags]
        node_ids = [node["id"] for node in nodes]
        edge_ids = [edge["id"] for edge in edges]
        if node_ids:
            rows = connection.execute(
                """
                SELECT resolved_node_id, source_trace_id, source_quote, confidence, created_at
                FROM memory_node_observations
                WHERE resolved_node_id IN ({placeholders})
                    AND source_trace_id IS NOT NULL
                ORDER BY confidence DESC, created_at DESC
                """.format(placeholders=_placeholders_from_ids(node_ids)),
                node_ids,
            ).fetchall()
            node_titles = {node["id"]: node["title"] for node in nodes}
            for row in rows:
                if not _evidence_matches_tags(
                    row["source_quote"],
                    node_titles.get(row["resolved_node_id"], ""),
                    matched_normalized_tags,
                ):
                    continue
                evidence.append(
                    {
                        "owner_type": "node",
                        "owner_id": row["resolved_node_id"],
                        "owner_title": node_titles.get(row["resolved_node_id"], ""),
                        "source_trace_id": row["source_trace_id"],
                        "source_quote": row["source_quote"],
                        "confidence": row["confidence"],
                        "created_at": row["created_at"],
                    }
                )
        if edge_ids:
            rows = connection.execute(
                """
                SELECT resolved_edge_id, source_trace_id, source_quote, confidence, created_at
                FROM memory_edge_observations
                WHERE resolved_edge_id IN ({placeholders})
                    AND source_trace_id IS NOT NULL
                ORDER BY confidence DESC, created_at DESC
                """.format(placeholders=_placeholders_from_ids(edge_ids)),
                edge_ids,
            ).fetchall()
            edge_titles = {
                edge["id"]: f"{edge['source_title']} -> {edge['relation_type']} -> {edge['target_title']}"
                for edge in edges
            }
            for row in rows:
                if not _evidence_matches_tags(
                    row["source_quote"],
                    edge_titles.get(row["resolved_edge_id"], ""),
                    matched_normalized_tags,
                ):
                    continue
                evidence.append(
                    {
                        "owner_type": "edge",
                        "owner_id": row["resolved_edge_id"],
                        "owner_title": edge_titles.get(row["resolved_edge_id"], ""),
                        "source_trace_id": row["source_trace_id"],
                        "source_quote": row["source_quote"],
                        "confidence": row["confidence"],
                        "created_at": row["created_at"],
                    }
                )

        seen = set()
        unique = []
        evidence.sort(key=lambda item: (-float(item["confidence"]), item["created_at"]))
        for item in evidence:
            marker = item["source_trace_id"]
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(item)
        return unique[:MAX_EVIDENCE_ITEMS]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _empty_result(query: str) -> MemoryRecallResult:
    return MemoryRecallResult(
        query=query,
        matched_tags=[],
        entities=[],
        relationships=[],
        useful_background=[],
        evidence=[],
        context_text="",
    )


def _build_useful_background(
    *,
    query: str,
    matched_tags: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[str]:
    del query
    if not matched_tags:
        return []

    background = []
    if nodes:
        node_titles = "、".join(node["title"] for node in nodes[:5])
        background.append(f"相关实体包括：{node_titles}。")

    if edges:
        relation_text = "；".join(
            f"{edge['source_title']} {edge['relation_type']} {edge['target_title']}"
            for edge in edges[:3]
        )
        background.append(f"相关关系包括：{relation_text}。")

    if any(node["type"] == "preference" for node in nodes) or any(
        edge["relation_type"] in {"prefers", "avoids"} for edge in edges
    ):
        background.append("回答时应优先考虑已召回的用户偏好或规避项。")

    return background


def _render_context_text(
    *,
    matched_tags: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    useful_background: list[str],
    evidence: list[dict[str, Any]],
) -> str:
    if not matched_tags and not nodes and not edges:
        return ""

    sections = ["Relevant Memory."]

    if nodes:
        node_items = []
        for node in nodes:
            node_items.append(
                f"{_inline_text(node['title'])} ({_inline_text(node['type'])}): "
                f"{_inline_text(node['summary'])}"
            )
        sections.append(f"Entities: {'; '.join(node_items)}.")

    if edges:
        edge_items = []
        for edge in edges:
            edge_items.append(
                f"{_inline_text(edge['source_title'])} -> "
                f"{_inline_text(edge['relation_type'])} -> "
                f"{_inline_text(edge['target_title'])}: {_inline_text(edge['summary'])}"
            )
        sections.append(f"Relationships: {'; '.join(edge_items)}.")

    if useful_background:
        background_items = [_inline_text(item) for item in useful_background if _inline_text(item)]
        if background_items:
            sections.append(f"Useful Background: {' '.join(background_items)}")

    if evidence:
        evidence_items = []
        for item in evidence[:MAX_EVIDENCE_ITEMS]:
            quote = _inline_text(item.get("source_quote"))
            owner_title = _inline_text(item["owner_title"])
            if quote and owner_title:
                evidence_items.append(f"{owner_title}: {quote}")
            elif quote:
                evidence_items.append(quote)
            elif owner_title:
                evidence_items.append(owner_title)
        if evidence_items:
            sections.append(f"Evidence: {'; '.join(_unique_texts(evidence_items))}.")

    return " ".join(_inline_text(section) for section in sections if _inline_text(section))


def _tag_score(row: sqlite3.Row) -> float:
    kind_weight = {
        "explicit": 6.0,
        "identity": 6.0,
        "preference": 5.0,
        "topic": 4.0,
        "inferred": 3.0,
    }.get(row["kind"], 3.0)
    return kind_weight + min(4.0, float(row["mention_count"]) * 0.35)


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
        grouped.setdefault(row["owner_id"], set()).add(row["source_trace_id"])
    return {owner_id: sorted(source_ids) for owner_id, source_ids in grouped.items()}


def _placeholders(items: list[dict[str, Any]]) -> str:
    return ", ".join("?" for _ in items) or "NULL"


def _placeholders_from_ids(items: dict[str, Any] | list[str]) -> str:
    return ", ".join("?" for _ in items) or "NULL"


def _unique_texts(items: list[str]) -> list[str]:
    seen = set()
    unique = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _inline_text(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean_text(value))


def _evidence_matches_tags(
    source_quote: str,
    owner_title: str,
    matched_normalized_tags: list[str],
) -> bool:
    text = _normalize(" ".join([source_quote, owner_title]))
    return any(tag in text for tag in matched_normalized_tags)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))
