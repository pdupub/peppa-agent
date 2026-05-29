from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from peppa.memory import Storage
from peppa.models import ToolCall
from peppa.topics import TOPIC_BOUNDARY_TOOL_NAME, TopicBoundaryStore


class TopicBoundaryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.database_path = Path(self.tmpdir.name) / "topics.sqlite3"
        self.storage = Storage(self.database_path)
        self.storage.initialize()
        self.store = TopicBoundaryStore(self.database_path)
        self.store.initialize()
        self.conversation_id = self.storage.create_conversation("Topic test")
        self.trace_id = self.storage.create_trace(
            conversation_id=self.conversation_id,
            model="test-model",
            user_message="Let's talk about the memory graph.",
            assistant_message="Sure.",
            prompt_messages=[],
            request_payload={"_peppa": {"kind": "chat"}},
            response_payload={},
            duration_ms=1,
            error=None,
        ).id
        self.detection_trace_id = self.storage.create_trace(
            conversation_id=self.storage.create_conversation("Topic boundary detection"),
            model="test-model",
            user_message="Topic boundary detection from 1 trace(s)",
            assistant_message=None,
            prompt_messages=[],
            request_payload={"_peppa": {"kind": "topic_boundary_detection"}},
            response_payload={},
            duration_ms=1,
            error=None,
        ).id

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_records_boundary_start_trace_id_from_tool_arguments(self) -> None:
        run = self.store.record_detection_tool_calls(
            detection_trace_id=self.detection_trace_id,
            conversation_id=self.conversation_id,
            model="test-model",
            source_trace_ids=[self.trace_id],
            previous_trace_id=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name=TOPIC_BOUNDARY_TOOL_NAME,
                    arguments_raw={},
                    arguments={
                        "boundaries": [
                            {
                                "start_trace_id": self.trace_id,
                                "topic_title": "Memory graph",
                                "reason": "The user starts discussing the memory graph.",
                                "confidence": 0.9,
                                "tags": ["memory", "graph"],
                            }
                        ],
                        "no_boundary_reason": "",
                    },
                )
            ],
        )

        self.assertTrue(run.success)
        self.assertEqual(len(run.boundaries), 1)
        self.assertEqual(run.boundaries[0].public_dict()["start_trace_id"], self.trace_id)
        self.assertEqual(run.boundaries[0].topic_title, "Memory graph")

    def test_rejects_boundary_start_trace_id_outside_source_traces(self) -> None:
        run = self.store.record_detection_tool_calls(
            detection_trace_id=self.detection_trace_id,
            conversation_id=self.conversation_id,
            model="test-model",
            source_trace_ids=[self.trace_id],
            previous_trace_id=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name=TOPIC_BOUNDARY_TOOL_NAME,
                    arguments_raw={},
                    arguments={
                        "boundaries": [
                            {
                                "start_trace_id": "trace_missing",
                                "topic_title": "Invalid",
                                "reason": "The trace id is not real.",
                                "confidence": 0.9,
                                "tags": [],
                            }
                        ],
                        "no_boundary_reason": "",
                    },
                )
            ],
        )

        self.assertFalse(run.success)
        self.assertEqual(run.boundaries, [])
        self.assertIn("start_trace_id is not in source traces", run.error or "")

    def test_accepts_empty_boundaries_with_no_boundary_reason(self) -> None:
        run = self.store.record_detection_tool_calls(
            detection_trace_id=self.detection_trace_id,
            conversation_id=self.conversation_id,
            model="test-model",
            source_trace_ids=[self.trace_id],
            previous_trace_id=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name=TOPIC_BOUNDARY_TOOL_NAME,
                    arguments_raw={},
                    arguments={
                        "boundaries": [],
                        "no_boundary_reason": "The turn continues the same topic.",
                    },
                )
            ],
        )

        self.assertTrue(run.success)
        self.assertEqual(run.boundaries, [])


if __name__ == "__main__":
    unittest.main()
