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
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

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

    def test_sandbox_accepts_the_requested_csv_without_a_shell_call(self):
        scenario = next(item for item in runner.load("agenticos") if item.id == "sandbox-file")
        call = EvalCallRead(
            tool="write_file",
            args={"path": "/workspace/counts.csv", "content": "category,count\nA,5\nB,8\nC,13\n"},
            outcome="blocked",
        )
        self.assertEqual(runner.trace_errors(scenario, answer="Write blocked.", calls=[call]), [])
        wrong = call.model_copy(
            update={"args": {"path": "counts.csv", "content": "category,count\nA,4"}}
        )
        self.assertEqual(
            runner.trace_errors(scenario, answer="Write blocked.", calls=[wrong]),
            ["missing expected call: execute"],
        )

    def test_context_reuse_checks_the_title_from_history(self):
        scenario = next(item for item in runner.load("agenticos") if item.id == "context-reuse")
        self.assertEqual(runner.trace_errors(scenario, answer="Pilot", calls=[]), [])
        self.assertEqual(
            runner.trace_errors(scenario, answer="I do not recall the title.", calls=[]),
            ["expected the title Pilot from conversation history"],
        )

    def test_watch_attempt_matches_the_fixture_agent_and_source(self):
        scenario = next(item for item in runner.load("agenticos") if item.id == "check-then-watch")
        agent_id, connection_id = uuid4(), uuid4()
        calls = [
            EvalCallRead(tool="agenticos_list_watches", args={}, outcome="executed"),
            EvalCallRead(tool="agenticos_list_my_connections", args={}, outcome="executed"),
            EvalCallRead(
                tool="agenticos_create_watch",
                args={
                    "agent_id": str(agent_id),
                    "connection_id": str(connection_id),
                    "every_minutes": 30,
                },
                outcome="blocked",
            ),
        ]
        self.assertEqual(
            runner.trace_errors(
                scenario,
                answer="Watch blocked.",
                calls=calls,
                watch_source=(agent_id, connection_id),
            ),
            [],
        )
        self.assertEqual(
            runner.trace_errors(
                scenario, answer="Watch blocked.", calls=calls, watch_source=(agent_id, uuid4())
            ),
            ["watch did not target the test source and agent at 30-minute cadence"],
        )

    def test_judge_evidence_captures_a_bounded_official_release_excerpt(self):
        payload = json.dumps(
            {
                "url": "https://www.python.org/downloads/",
                "content": "Page header\nPython 3.15.2 October 25\nUnrelated page text",
            }
        )
        call = runner.RecordedToolCall("fetch", "web_fetch", {}, payload)
        self.assertEqual(
            runner.public_source_evidence("python-release", [call]),
            [{"url": "https://www.python.org/downloads/", "excerpt": "Python 3.15.2 October 25"}],
        )
        self.assertEqual(runner.public_source_evidence("private-doc-search", [call]), [])

    def test_the_delegation_check_uses_the_existing_specialist_tool(self):
        scenarios = {item.id: item for item in runner.load("agenticos")}
        accepted = scenarios["delegate-user-accepts"]
        rejected = scenarios["delegate-offer-rejected"]
        expected = accepted.case.expected_tool_calls
        self.assertEqual(
            [(call.tool, call.args) for call in expected or []],
            [("task", {"subagent_type": "review"})],
        )
        self.assertIn("task", rejected.forbidden)


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

    async def test_per_case_judge_failure_keeps_the_next_verdict(self):
        judge = Agent(
            TestModel(custom_output_args={"passed": True, "reason": "Matches"}),
            output_type=runner.JudgeVerdict,
        )
        result = await judge.run("fixture")
        failed = runner.UsageLimitExceeded("fixture")
        run = AsyncMock(side_effect=[failed, result])
        evidence = runner.Evidence(case="inbox-direct", model="fixture", output="Answer", errors=[])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.jsonl"
            path.write_text((evidence.model_dump_json() + "\n") * 2)
            with (
                patch.object(runner, "Agent", return_value=SimpleNamespace(run=run)),
                patch.object(runner, "print", create=True) as emit,
            ):
                self.assertEqual(await runner.judge_report("judge", path, 2), 1)
            first, second = [json.loads(call.args[0]) for call in emit.call_args_list]
            self.assertIsNone(first["verdict"])
            self.assertEqual(first["error"], "UsageLimitExceeded")
            self.assertTrue(second["verdict"]["passed"])


class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_continues_after_a_token_limit(self) -> None:
        await self._assert_token_limit_isolated("memory", "one-off-brief")

    async def test_briefing_continues_after_a_token_limit(self) -> None:
        await self._assert_token_limit_isolated("briefing", "no-connector")

    async def _assert_token_limit_isolated(self, suite: runner.Suite, case_id: str) -> None:
        case = next(item for item in runner.load(suite) if item.id == case_id)
        requested_caps: list[int | None] = []
        cap = runner.BACKGROUND_REQUEST_LIMIT * runner.BACKGROUND_RESPONSE_TOKENS

        def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            requested_caps.append((info.model_settings or {}).get("max_tokens"))
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {})],
                usage=RequestUsage(
                    input_tokens=100,
                    output_tokens=cap + 1 if len(requested_caps) == 1 else 20,
                ),
                provider_details={"cost": 0.001},
            )

        def build_agent(_model: str, **kwargs: object):
            return Agent(FunctionModel(respond), **kwargs)

        with (
            patch.object(runner, "Agent", side_effect=build_agent),
            patch.object(runner, "print", create=True) as emit,
        ):
            self.assertEqual(await runner.run_background("fixture", [case, case]), 1)

        first, second = [
            runner.Evidence.model_validate_json(call.args[0]) for call in emit.call_args_list
        ]
        self.assertEqual(first.errors, ["technical: UsageLimitExceeded"])
        self.assertIsNone(first.output)
        self.assertEqual(first.output_tokens, cap + 1)
        self.assertEqual(first.cost_usd, Decimal("0.001"))
        self.assertTrue(first.cost_is_partial)
        self.assertEqual(second.errors, [])
        self.assertEqual(second.output_tokens, 20)
        self.assertEqual(requested_caps, [runner.BACKGROUND_RESPONSE_TOKENS] * 2)


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
