"""The extended packets remain portable, scoped synthetic regression fixtures."""

import json
import tempfile
import unittest
from pathlib import Path

from context_cases import ContextPacket, load_context_cases

from app.services.dataset_files import parse


class ContextCasesTests(unittest.TestCase):
    def test_corpus_survives_the_production_import_export_contract(self) -> None:
        cases = load_context_cases()
        self.assertEqual(len(cases), 51)
        exported = "".join(case.model_dump_json() + "\n" for case in cases)
        self.assertEqual(parse(exported.encode(), "jsonl"), cases)
        self.assertNotIn("dev@vstorm.co", exported)
        self.assertNotIn("agenticos.vstorm.co/chat", exported)
        self.assertGreaterEqual(sum("holdout" in case.tags for case in cases), 12)
        self.assertEqual(sum("memory" in case.tags for case in cases), 11)

    def test_fixture_exercises_sources_the_old_window_and_clip_drop(self) -> None:
        cases = {
            next(tag.removeprefix("case:") for tag in case.tags if tag.startswith("case:")): case
            for case in load_context_cases()
        }
        noisy = ContextPacket.model_validate_json(cases["high-volume-keeps-important-topic"].input)
        self.assertGreater(len(noisy.messages), 80)
        self.assertGreater((noisy.as_of - noisy.messages[0].occurred_at).days, 7)
        long = ContextPacket.model_validate_json(cases["important-tail-after-400"].input)
        self.assertNotIn("My actual request", long.messages[0].text[:400])
        self.assertIn("My actual request", long.messages[0].text[400:])
        maintenance = ContextPacket.model_validate_json(
            cases["memory-long-assistant-hides-user"].input
        )
        self.assertGreater(len(maintenance.messages[-1].text), 8000)
        self.assertEqual(maintenance.messages[0].speaker_id, "person-a")
        event = ContextPacket.model_validate_json(cases["new-deadline-without-chat"].input)
        self.assertEqual(event.messages, [])
        self.assertEqual(event.changed_source_ids, ["task-a"])

    def test_human_feedback_and_fresh_state_have_explicit_provenance(self) -> None:
        cases = {
            next(tag.removeprefix("case:") for tag in case.tags if tag.startswith("case:")): case
            for case in load_context_cases()
        }
        answered = ContextPacket.model_validate_json(
            cases["ask-user-answer-is-human-evidence"].input
        )
        self.assertFalse(any("thu 18" in message.text for message in answered.messages))
        receipt = answered.tool_receipts[0]
        self.assertEqual(receipt["answered_by_user_id"], answered.subject_id)
        self.assertEqual(
            receipt["submitted_answers"],
            {"When": ["thu 18"], "Delivery": ["team channel"]},
        )
        removed = ContextPacket.model_validate_json(cases["deleted-routine-is-not-paused"].input)
        self.assertEqual(removed.current_state["routines"], [])
        self.assertTrue(removed.current_state["routines_complete"])
        self.assertEqual(removed.tool_receipts[0]["action"], "delete_routine")
        partial = ContextPacket.model_validate_json(
            cases["partial-resource-page-is-not-absence"].input
        )
        self.assertFalse(partial.current_state["routines_complete"])
        self.assertIsNotNone(partial.current_state["next_cursor"])

    def test_missing_routine_fixture_keeps_the_human_request_and_native_answers(
        self,
    ) -> None:
        case = next(
            case
            for case in load_context_cases()
            if "case:missing-routine-after-assistant-creation-claim" in case.tags
        )
        current = ContextPacket.model_validate_json(case.input)
        self.assertEqual(current.current_state["routines"], [])
        self.assertTrue(current.current_state["routines_complete"])
        self.assertEqual(current.current_state["deleted_resources"], [])
        self.assertEqual(current.messages[0].speaker_id, current.subject_id)
        self.assertEqual(current.messages[-1].role, "assistant")
        self.assertEqual(current.messages[1].id, "answer:setup")
        self.assertEqual(current.tool_receipts[0]["answered_by_user_id"], current.subject_id)
        self.assertEqual(
            current.tool_receipts[0]["submitted_answers"],
            {
                "When": ["mon 08"],
                "Delivery": ["team channel"],
                "Source": ["https://example.com/product/releases"],
            },
        )

    def test_duplicate_ids_and_ambiguous_partitions_are_rejected(self) -> None:
        case = load_context_cases()[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(case.model_dump_json() + "\n" + case.model_dump_json() + "\n")
            with self.assertRaisesRegex(ValueError, "unique case ID"):
                load_context_cases(path)
            invalid = case.model_copy(update={"tags": [*case.tags, "holdout"]})
            path.write_text(invalid.model_dump_json() + "\n")
            with self.assertRaisesRegex(ValueError, "partition"):
                load_context_cases(path)

    def test_duplicate_evidence_identity_is_not_a_second_source(self) -> None:
        case = load_context_cases()[0]
        payload = json.loads(case.input)
        payload["messages"].append(payload["messages"][0])
        duplicate = case.model_copy(update={"input": json.dumps(payload)})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate-source.jsonl"
            path.write_text(duplicate.model_dump_json() + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate source"):
                load_context_cases(path)
