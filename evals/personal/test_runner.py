"""Run with the backend's virtual environment: python -m unittest discover -s evals/personal."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import run as runner
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.schemas.eval_run import EvalCallRead


class TraceTests(unittest.TestCase):
    def test_tools_use_normalized_arguments_and_record_blocked_attempts(self):
        scenario = next(item for item in runner.load("agenticos") if item.id == "inbox-direct")
        call = EvalCallRead(
            tool="agenticos_list_inbox_items",
            args={"item_id": "f3333ec4-01dd-42d5-a543-af449cc44eda"},
            outcome="replayed",
        )
        attempt = runner.EvalAttemptRead(
            id=uuid4(),
            arm_id=uuid4(),
            attempt=0,
            status="done",
            agent_run_id=None,
            answer="See the linked Inbox card.",
            calls=[call],
            cost_usd=None,
            cost_is_partial=True,
            input_tokens=None,
            output_tokens=None,
            latency_ms=None,
            error=None,
            outcome=None,
            state="ungraded",
            score=None,
        )
        self.assertEqual(runner.trace_errors(scenario, attempt), [])
        attempt.calls = [
            call.model_copy(update={"args": {"item_id": "wrong"}}),
            EvalCallRead(tool="agenticos_list_inbox_cases", args={}, outcome="blocked"),
        ]
        self.assertEqual(
            runner.trace_errors(scenario, attempt),
            [
                "forbidden call: agenticos_list_inbox_cases",
                "missing expected call: agenticos_list_inbox_items",
            ],
        )


class JudgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_judge_skips_failed_traces_and_respects_limit(self):
        def build_agent(_model: str, **kwargs: object):
            return Agent(
                TestModel(custom_output_args={"passed": True, "reason": "Matches"}), **kwargs
            )

        output = runner.Evidence(case="inbox-direct", model="fixture", output="Answer", errors=[])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.jsonl"
            path.write_text(
                "\n".join(
                    [
                        output.model_copy(update={"errors": ["missing tool"]}).model_dump_json(),
                        output.model_dump_json(),
                        output.model_dump_json(),
                    ]
                )
            )
            with (
                patch.object(runner, "Agent", side_effect=build_agent),
                patch.object(runner, "print", create=True) as emit,
            ):
                self.assertEqual(await runner.judge_report("judge", path, 1), 0)
            self.assertEqual(emit.call_count, 1)
            self.assertTrue(json.loads(emit.call_args.args[0])["verdict"]["passed"])
