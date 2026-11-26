"""Memory evals preserve the same dated human evidence as the runtime reader."""

import asyncio
import unittest
from datetime import datetime

from context_cases import ContextPacket, load_context_cases
from context_run import ReplayReader, candidate
from pydantic import BaseModel


class RecordingReader(ReplayReader):
    def __init__(self) -> None:
        self.material: object = None

    async def read[Result: BaseModel](
        self, *, stage: str, instructions: str, material: object, output_type: type[Result]
    ) -> Result:
        self.material = material
        return output_type.model_validate({"claims": []})


class ContextReplayTests(unittest.TestCase):
    def test_memory_replay_keeps_source_time_and_authenticated_answer_identity(self) -> None:
        case = next(
            row
            for row in load_context_cases()
            if "case:memory-authenticated-question-preference" in row.tags
        )
        packet = ContextPacket.model_validate_json(case.input)
        reader = RecordingReader()
        asyncio.run(candidate(reader, packet, component="memory", variant="after"))
        self.assertIsInstance(reader.material, dict)
        assert isinstance(reader.material, dict)
        self.assertEqual(reader.material["as_of"], packet.as_of.isoformat())
        conversation = reader.material["conversation"]
        answers = [turn for turn in conversation if turn["kind"] == "authenticated_answer"]
        self.assertEqual(len(answers), 1)
        self.assertTrue(answers[0]["source_id"].startswith("receipt:"))
        self.assertIsNotNone(datetime.fromisoformat(answers[0]["occurred_at"]).tzinfo)
        self.assertIn("ISO dates", answers[0]["text"])
