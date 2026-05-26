from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from peppa.memory.graph import MemoryGraphStore


class MemoryGraphStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.database_path = Path(self.tmpdir.name) / "memory.sqlite3"
        self.store = MemoryGraphStore(self.database_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_duplicate_node_appends_summary_and_exact_edge_keeps_original_summary(self) -> None:
        self._record(
            nodes=[
                self._node("node_1", "concept", "Peppa", "Original node summary.", ["alpha"]),
                self._node("node_2", "project", "Memory", "Memory project.", []),
            ],
            edges=[
                self._edge("node_1", "node_2", "related_to", "Original edge summary.", ["edge-old"])
            ],
        )
        self._record(
            nodes=[
                self._node("node_1", "concept", " peppa ", "New node summary.", ["beta"]),
                self._node("node_2", "project", "Memory", "Memory project update.", []),
            ],
            edges=[
                self._edge("node_1", "node_2", "related_to", "New edge summary.", ["edge-new"])
            ],
        )

        graph = self.store.get_memory_graph()
        peppa = self._only(node for node in graph["nodes"] if node["title"].strip().lower() == "peppa")
        self.assertEqual(peppa["summary"], "Original node summary.\n\nNew node summary.")
        self.assertEqual({tag["name"] for tag in peppa["tags"]}, {"alpha", "beta"})

        edge = self._only(graph["edges"])
        self.assertEqual(edge["summary"], "Original edge summary.")
        self.assertEqual({tag["name"] for tag in edge["tags"]}, {"edge-old", "edge-new"})

    def test_tag_merge_redirects_future_observations_to_target_tag(self) -> None:
        self._record(
            nodes=[self._node("node_1", "concept", "Peppa", "Original.", ["alpha", "beta"])],
            edges=[],
        )
        graph = self.store.get_memory_graph()
        tags_by_name = {tag["name"]: tag for tag in graph["tags"]}

        self.assertTrue(self.store.merge_tags(tags_by_name["beta"]["id"], tags_by_name["alpha"]["id"]))
        self._record(
            nodes=[self._node("node_1", "concept", "Peppa", "Follow up.", ["beta"])],
            edges=[],
        )

        graph = self.store.get_memory_graph()
        self.assertEqual([tag["name"] for tag in graph["tags"]], ["alpha"])
        peppa = self._only(graph["nodes"])
        self.assertEqual({tag["name"] for tag in peppa["tags"]}, {"alpha"})

    def test_node_merge_redirects_edges_and_future_node_identity_to_target(self) -> None:
        self._record(
            nodes=[
                self._node("source", "person", "Alicia", "Source summary.", ["source-tag"]),
                self._node("target", "person", "Alice", "Target summary.", ["target-tag"]),
                self._node("project", "project", "Memory", "Project.", []),
            ],
            edges=[
                self._edge("source", "project", "works_on", "Source edge.", ["source-edge"]),
                self._edge("target", "project", "works_on", "Target edge.", ["target-edge"]),
            ],
        )
        graph = self.store.get_memory_graph()
        nodes_by_title = {node["title"]: node for node in graph["nodes"]}

        self.assertTrue(self.store.merge_nodes(nodes_by_title["Alicia"]["id"], nodes_by_title["Alice"]["id"]))
        self._record(
            nodes=[
                self._node("source", "person", "Alicia", "Future source summary.", ["future-tag"]),
                self._node("project", "project", "Memory", "Project update.", []),
            ],
            edges=[self._edge("source", "project", "works_on", "Future edge.", ["future-edge"])],
        )

        graph = self.store.get_memory_graph()
        titles = {node["title"] for node in graph["nodes"]}
        self.assertIn("Alice", titles)
        self.assertNotIn("Alicia", titles)

        alice = self._only(node for node in graph["nodes"] if node["title"] == "Alice")
        self.assertEqual(
            alice["summary"],
            "Target summary.\n\nSource summary.\n\nFuture source summary.",
        )
        self.assertEqual(
            {tag["name"] for tag in alice["tags"]},
            {"source-tag", "target-tag", "future-tag"},
        )

        works_on_edges = [edge for edge in graph["edges"] if edge["relation_type"] == "works_on"]
        self.assertEqual(len(works_on_edges), 1)
        self.assertEqual(
            {tag["name"] for tag in works_on_edges[0]["tags"]},
            {"source-edge", "target-edge", "future-edge"},
        )

    def _record(self, *, nodes: list[dict[str, object]], edges: list[dict[str, object]]) -> None:
        self.store.record_memory_graph_update(
            extraction_trace_id="trace_extraction",
            model="test-model",
            tool_call_id=None,
            source_trace_ids=["trace_1"],
            arguments={
                "segments": [],
                "memory_graph": {
                    "tags": [],
                    "nodes": nodes,
                    "edges": edges,
                },
                "document_suggestions": [],
            },
        )

    @staticmethod
    def _node(
        ref: str,
        node_type: str,
        title: str,
        summary: str,
        tags: list[str],
    ) -> dict[str, object]:
        return {
            "ref": ref,
            "type": node_type,
            "title": title,
            "summary": summary,
            "tags": tags,
            "source_trace_id": "trace_1",
            "source_quote": "quote",
            "confidence": 0.7,
        }

    @staticmethod
    def _edge(
        source_ref: str,
        target_ref: str,
        relation_type: str,
        summary: str,
        tags: list[str],
    ) -> dict[str, object]:
        return {
            "source_ref": source_ref,
            "target_ref": target_ref,
            "relation_type": relation_type,
            "summary": summary,
            "tags": tags,
            "source_trace_id": "trace_1",
            "source_quote": "quote",
            "confidence": 0.7,
        }

    @staticmethod
    def _only(items):
        items = list(items)
        if len(items) != 1:
            raise AssertionError(f"Expected exactly one item, got {len(items)}")
        return items[0]


if __name__ == "__main__":
    unittest.main()
