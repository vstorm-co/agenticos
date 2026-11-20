"""Run with the backend's virtual environment: python -m unittest discover -s evals/personal."""

import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import asynccontextmanager, redirect_stderr
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import run as runner
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.eval_run import EvalCallRead


class TraceTests(unittest.TestCase):
    def test_tools_use_normalized_arguments_and_record_blocked_attempts(self):
        scenario = next(item for item in runner.load("agenticos") if item.id == "inbox-direct")
        call = EvalCallRead(
            tool="agenticos_list_inbox_items",
            args={"item_id": "f3333ec4-01dd-42d5-a543-af449cc44eda"},
            outcome="executed",
        )
        answer = "See the linked Inbox card."
        self.assertEqual(runner.trace_errors(scenario, answer=answer, calls=[call]), [])
        self.assertEqual(
            runner.trace_errors(
                scenario, answer=answer, calls=[call.model_copy(update={"outcome": "blocked"})]
            ),
            ["missing expected call: agenticos_list_inbox_items"],
        )
        calls = [
            call.model_copy(update={"args": {"item_id": "wrong"}}),
            EvalCallRead(tool="agenticos_list_inbox_cases", args={}, outcome="blocked"),
        ]
        self.assertEqual(
            runner.trace_errors(scenario, answer=answer, calls=calls),
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


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuses_to_use_a_non_eval_environment(self):
        with (
            patch.dict(runner.os.environ, {"AGENTICOS_PERSONAL_EVAL": "0"}),
            self.assertRaisesRegex(SystemExit, "isolated personal eval Compose stack"),
        ):
            await runner.run_agenticos(runner.argparse.Namespace(), [])

    async def test_pins_publication_and_runs_only_with_a_budget(self):
        version_id, profile_id, run_id, conversation_id = (uuid4() for _ in range(4))
        spec = runner.AgentSpec(name="Fixture", model_profile_id=profile_id)
        version = SimpleNamespace(id=version_id, spec=spec.model_dump(mode="json"))
        agent = SimpleNamespace(id=uuid4(), current_version_id=version.id)
        profile = SimpleNamespace(provider="openrouter", model="fixture")
        execute = AsyncMock(
            return_value=(
                "Cześć!",
                SimpleNamespace(
                    id=run_id,
                    status="completed",
                    input_tokens=60,
                    output_tokens=4,
                    cost_usd=Decimal("0.0001"),
                    cost_is_partial=True,
                ),
            )
        )

        @asynccontextmanager
        async def session():
            yield object()

        args = Namespace(organization_id=uuid4(), user_id=uuid4(), model_profile=None, max_usd=None)
        scenario = next(item for item in runner.load("agenticos") if item.id == "natural-hello")
        ctx = AuthContext(
            organization_id=args.organization_id,
            user_id=args.user_id,
            role=OrgRoleName.OWNER,
            subject_is_publisher_fallback=True,
        )
        mcp_started = False

        @asynccontextmanager
        async def serve():
            nonlocal mcp_started
            mcp_started = True
            yield

        with (
            patch.dict(runner.os.environ, {"AGENTICOS_PERSONAL_EVAL": "1"}),
            patch.object(runner, "get_db_context", session),
            patch.object(runner, "job_context", AsyncMock(return_value=ctx)),
            patch.object(runner, "serve_eval_mcp", serve),
            patch.object(
                runner.ConversationService,
                "create_conversation",
                AsyncMock(return_value=SimpleNamespace(id=conversation_id)),
            ) as create_conversation,
            patch.object(runner.agent_repo, "get_shipped_starter", AsyncMock(return_value=agent)),
            patch.object(runner.agent_repo, "get_version", AsyncMock(return_value=version)),
            patch.object(runner.credential_repo, "get_profile", AsyncMock(return_value=profile)),
            patch.object(runner.AgentRunnerService, "execute", execute),
            patch.object(
                runner.ShippedAgentService,
                "review_update",
                AsyncMock(return_value=SimpleNamespace(changes=[])),
            ) as review,
            patch.object(
                runner.intercepted_tool_call_repo, "list_for_run", AsyncMock(return_value=[])
            ),
            redirect_stderr(StringIO()) as plan,
        ):
            self.assertEqual(await runner.run_agenticos(args, [scenario]), 0)
            execute.assert_not_awaited()
            self.assertIn(f"Published version {version_id}", plan.getvalue())
            self.assertIn("preflight, no model calls", plan.getvalue())
            self.assertFalse(mcp_started)

            review.return_value = SimpleNamespace(changes=[SimpleNamespace(version="published")])
            with self.assertRaisesRegex(SystemExit, "published AgenticOS differs from the code"):
                await runner.run_agenticos(args, [scenario])
            execute.assert_not_awaited()

            review.return_value = SimpleNamespace(changes=[])
            args.max_usd = Decimal("0.10")
            with patch.object(runner, "print", create=True) as emit:
                self.assertEqual(await runner.run_agenticos(args, [scenario, scenario]), 1)
            emit.assert_called_once()
            self.assertIn("[1/2] natural-hello · running", plan.getvalue())
            self.assertIn("1/2 completed", plan.getvalue())
            self.assertIn("costs incomplete", plan.getvalue())
            execute.assert_awaited_once()
            call = execute.await_args
            assert call is not None
            self.assertTrue(mcp_started)
            self.assertFalse(call.args[0].subject_is_publisher_fallback)
            self.assertEqual(call.args[0].user_id, ctx.user_id)
            self.assertEqual(call.args[2], scenario.case.input)
            self.assertEqual(len(call.kwargs["message_history"]), len(scenario.case.history))
            self.assertEqual(call.kwargs["surface"], runner.RunSurface.WEB)
            self.assertEqual(call.kwargs["conversation_id"], conversation_id)
            self.assertTrue(call.kwargs["acts_for_sender"])
            create_call = create_conversation.await_args
            assert create_call is not None
            conversation = create_call.args[0]
            self.assertEqual(conversation.organization_id, ctx.organization_id)
            self.assertEqual(conversation.user_id, ctx.user_id)
            self.assertEqual(call.kwargs["version_id"], version_id)
            self.assertEqual(call.kwargs["model_profile_id"], profile_id)
            self.assertEqual(call.kwargs["run_limit_usd"], Decimal("0.10"))
            self.assertIsInstance(call.kwargs["isolation"], runner.RunIsolation)
            row = runner.Evidence.model_validate_json(emit.call_args.args[0])
            self.assertEqual(row.attempt, run_id)
            self.assertTrue(row.cost_is_partial)
