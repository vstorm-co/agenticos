"""Run with the backend's virtual environment: python -m unittest discover -s evals/personal."""

import inspect
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
from starlette.applications import Starlette

from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.eval_run import EvalCallRead
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._tools import platform_tools


class TraceTests(unittest.TestCase):
    def test_vendor_query_requires_a_typed_filter_and_correct_page(self) -> None:
        scenario = next(item for item in runner.load("agenticos") if item.id == "table-query-exact")
        expected = (scenario.case.expected_tool_calls or [])[0]
        column = uuid4()
        args = {
            **(expected.args or {}),
            "query": {
                "limit": 5,
                "filters": [{"column_id": str(column), "op": "eq", "value": "Pending"}],
            },
        }
        correct = EvalCallRead(tool=expected.tool, args=args, outcome="executed")
        self.assertEqual(
            runner.trace_errors(
                scenario, answer="Five, with more.", calls=[correct], table_status_column=column
            ),
            [],
        )
        for bad_query in (
            {"limit": 5},
            {**args["query"], "limit": 50},
            {"limit": 5, "filters": ["Pending"]},
        ):
            wrong = correct.model_copy(update={"args": {**args, "query": bad_query}})
            self.assertEqual(
                runner.trace_errors(
                    scenario, answer="Five.", calls=[wrong], table_status_column=column
                ),
                ["vendor query did not filter Status = Pending with a five-record page"],
            )

    def test_authored_platform_tools_and_argument_names_exist(self) -> None:
        api = PlatformApi(Starlette(), token=lambda: None, on_refusal=lambda reason: reason)
        tools = {f"agenticos_{tool.name}": tool.function for tool in platform_tools(api)}
        for scenario in runner.load("agenticos"):
            for tool_name in scenario.forbidden:
                if tool_name.startswith("agenticos_"):
                    self.assertIn(tool_name, tools, scenario.id)
            for expected in scenario.case.expected_tool_calls or []:
                if expected.tool.startswith("agenticos_"):
                    self.assertIn(expected.tool, tools, scenario.id)
                    self.assertLessEqual(
                        set(expected.args or {}),
                        inspect.signature(tools[expected.tool]).parameters.keys(),
                        scenario.id,
                    )

    def test_trace_checks_typed_arguments(self) -> None:
        case = next(
            item for item in runner.load("agenticos") if item.id == "activity-seven-day-spend"
        )
        call = EvalCallRead(tool="agenticos_get_spend", args={"days": 7}, outcome="executed")
        self.assertEqual(runner.trace_errors(case, answer="Spent $0.02.", calls=[call]), [])
        wrong = call.model_copy(update={"args": {"days": 30}})
        self.assertEqual(
            runner.trace_errors(case, answer="Spent $0.02.", calls=[wrong]),
            ["missing expected call: agenticos_get_spend"],
        )

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
        for title in ("Pilot", "**Pilot**", "`Pilot`", "Pilot."):
            self.assertEqual(runner.trace_errors(scenario, answer=title, calls=[]), [])
        self.assertEqual(
            runner.trace_errors(scenario, answer="I do not recall the title.", calls=[]),
            ["expected the title Pilot from conversation history"],
        )

    def test_channel_replay_checks_attribution_without_internal_ids(self) -> None:
        scenario = next(item for item in runner.load("agenticos") if item.id == "slack-room-recall")
        self.assertEqual(
            runner.trace_errors(scenario, answer="Mira asked, then Teo.", calls=[]), []
        )
        self.assertEqual(
            runner.trace_errors(scenario, answer="Mira (eval-197bed8a-...) and Teo.", calls=[]),
            ["internal channel user ID appeared in a channel answer"],
        )

    def test_new_connection_enforces_delegation_and_tool_budget(self) -> None:
        scenario = next(item for item in runner.load("agenticos") if item.id == "new-connection")
        watch = EvalCallRead(tool="agenticos_list_watches", args={}, outcome="executed")
        task = EvalCallRead(tool="task", args={}, outcome="executed")
        self.assertEqual(
            runner.trace_errors(scenario, answer="A watch can work.", calls=[watch]), []
        )
        self.assertEqual(
            runner.trace_errors(scenario, answer="A watch can work.", calls=[watch] * 6 + [task]),
            ["forbidden call: task", "watch proposal exceeded six tool calls"],
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


class GreetingPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = {item.id: item for item in runner.load("agenticos")}
        self.boards = EvalCallRead(tool="agenticos_list_task_boards", args={}, outcome="executed")

    def test_first_greeting_reads_but_never_provisions(self) -> None:
        case = self.cases["natural-hello"]
        self.assertEqual(
            runner.trace_errors(
                case, answer="Cześć! Mogę utworzyć tablicę zadań?", calls=[self.boards]
            ),
            [],
        )
        self.assertIn(
            "first private greeting needs one successful board lookup",
            runner.trace_errors(case, answer="Cześć!", calls=[]),
        )
        self.assertIn(
            "first private greeting needs one successful board lookup",
            runner.trace_errors(case, answer="Cześć!", calls=[self.boards, self.boards]),
        )
        write = EvalCallRead(tool="agenticos_ensure_task_board", args={}, outcome="blocked")
        self.assertTrue(runner.trace_errors(case, answer="Cześć!", calls=[self.boards, write]))
        unrelated = EvalCallRead(tool="agenticos_create_skill", args={}, outcome="blocked")
        self.assertIn(
            "greeting attempted an unrelated operation",
            runner.trace_errors(case, answer="Cześć!", calls=[self.boards, unrelated]),
        )

    def test_conversation_language_does_not_authorize_greeting_preference_writes(self) -> None:
        for tool in ("set_my_language", "update_my_profile", "remember"):
            with self.subTest(tool=tool):
                call = EvalCallRead(tool=f"agenticos_{tool}", args={}, outcome="blocked")
                self.assertIn(
                    "greeting attempted an unrelated operation",
                    runner.trace_errors(
                        self.cases["natural-hello"], answer="Cześć!", calls=[self.boards, call]
                    ),
                )

    def test_empty_and_populated_boards_require_the_exact_private_reader(self) -> None:
        from greeting_fixture import TABLE_ID

        tasks = EvalCallRead(
            tool="agenticos_list_tasks", args={"table_id": str(TABLE_ID)}, outcome="executed"
        )
        for key, answer in [
            ("hello-empty-board", "Cześć! Lista jest pusta. Zbierzemy zadania?"),
            ("hello-priorities", "Cześć! ORION ma najbliższy termin."),
        ]:
            self.assertEqual(
                runner.trace_errors(self.cases[key], answer=answer, calls=[self.boards, tasks]), []
            )
            wrong = tasks.model_copy(update={"args": {"table_id": str(uuid4())}})
            self.assertIn(
                "greeting must read only the selected private board once",
                runner.trace_errors(self.cases[key], answer=answer, calls=[self.boards, wrong]),
            )
        self.assertIn(
            "greeting priorities are not grounded in observed tasks",
            runner.trace_errors(
                self.cases["hello-priorities"],
                answer="Masz ważną naradę.",
                calls=[self.boards, tasks],
            ),
        )

    def test_no_tools_constraints_and_repeat_shared_greetings_stay_quiet(self) -> None:
        for key in runner.NO_TOOL_GREETINGS:
            self.assertEqual(runner.trace_errors(self.cases[key], answer="Cześć!", calls=[]), [])
            self.assertIn(
                "this greeting must not call tools",
                runner.trace_errors(self.cases[key], answer="Cześć!", calls=[self.boards]),
            )

    def test_proposals_need_a_named_platform_record_and_no_draft_tool(self) -> None:
        research = self.cases["research-working-table-offer"]
        self.assertIn(
            "missing structured working table proposal",
            runner.trace_errors(
                research, answer="Add the next result to an existing spreadsheet table.", calls=[]
            ),
        )
        for key in ("research-working-table-offer", "news-routine-offer"):
            with self.subTest(case=key):
                errors = runner.trace_errors(
                    self.cases[key],
                    answer="AgenticOS Table. Routine weekdays at 9:00 to Inbox; shall I prepare it?",
                    calls=[EvalCallRead(tool="propose_setup", args={}, outcome="blocked")],
                )
                self.assertTrue(errors)

    def test_research_and_news_need_a_concrete_proposal_without_activation(self) -> None:
        self.assertEqual(
            runner.trace_errors(
                self.cases["research-working-table-offer"],
                answer="Najniższa podana cena to 8. Proponuję AgenticOS Table wyników i źródeł; utworzyć ją?",
                calls=[],
            ),
            [],
        )
        self.assertEqual(
            runner.trace_errors(
                self.cases["news-routine-offer"],
                answer="Poprawka usuwa awarię parsera. Proponuję rutynę w dni robocze o 9:00 do Inbox; czy ją przygotować?",
                calls=[],
            ),
            [],
        )
        write = EvalCallRead(tool="agenticos_create_routine", args={}, outcome="blocked")
        self.assertTrue(
            runner.trace_errors(
                self.cases["news-routine-offer"],
                answer="Rutyna codziennie do Inbox.",
                calls=[write],
            )
        )
        self.assertIn(
            "routine proposal needs a cadence and destination",
            runner.trace_errors(
                self.cases["news-routine-offer"], answer="Można to zautomatyzować.", calls=[]
            ),
        )


class GreetingFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_all_three_states_and_restores_the_real_service(self) -> None:
        from greeting_fixture import TABLE_ID, greeting_task_reads

        from app.services.tasks import TaskService

        ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
        service = TaskService(AsyncMock())
        real_boards = TaskService.boards
        for state, count in [("absent", 0), ("empty", 1), ("priorities", 1)]:
            with greeting_task_reads(ctx, state):
                boards = await service.boards(ctx)
                self.assertEqual(len(boards), count)
                if boards:
                    self.assertEqual(boards[0].scope_kind, "private")
                    self.assertEqual(boards[0].scope_id, ctx.user_id)
                    tasks = await service.list_tasks(ctx, TABLE_ID, skip=0, limit=1)
                    self.assertEqual(len(tasks.items), 1 if state == "priorities" else 0)
                    self.assertEqual(tasks.has_more, state == "priorities")
        self.assertIs(TaskService.boards, real_boards)

    async def test_other_tenant_user_and_table_reads_fall_through(self) -> None:
        from greeting_fixture import TABLE_ID, greeting_task_reads

        from app.services.tasks import TaskService

        ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
        service = TaskService(AsyncMock())
        boards = AsyncMock(return_value=[])
        tasks = AsyncMock()
        with (
            patch.object(TaskService, "boards", boards),
            patch.object(TaskService, "list_tasks", tasks),
            greeting_task_reads(ctx, "priorities"),
        ):
            for other in [
                AuthContext(user_id=uuid4(), organization_id=ctx.organization_id, role=ctx.role),
                AuthContext(user_id=ctx.user_id, organization_id=uuid4(), role=ctx.role),
            ]:
                await service.boards(other)
                await service.list_tasks(other, TABLE_ID)
            await service.list_tasks(ctx, uuid4())
        self.assertEqual(boards.await_count, 2)
        self.assertEqual(tasks.await_count, 3)


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


class BackgroundOutputTests(unittest.TestCase):
    def test_memory_accepts_both_inflections_but_requires_the_full_schedule(self) -> None:
        case = next(item for item in runner.load("memory") if item.id == "working-hours")
        quote = case.case.input
        for statement in (
            quote,
            "Stały grafik to wtorek\N{EN DASH}sobota, 10:00\N{EN DASH}18:00, Warszawa.",
        ):
            with self.subTest(statement=statement):
                found = runner.extraction._Extraction(
                    claims=[runner.extraction._Extracted(statement=statement, evidence=quote)]
                )
                self.assertEqual(runner.memory_errors(case, found), [])
        wrong = runner.extraction._Extraction(
            claims=[
                runner.extraction._Extracted(
                    statement="Grafik to wtorek\N{EN DASH}sobota, 10:00\N{EN DASH}17:00, Warszawa.",
                    evidence=quote,
                )
            ]
        )
        self.assertEqual(
            runner.memory_errors(case, wrong), ["missing expected claim or duplicate claims"]
        )

    def test_briefing_compares_schedule_occurrences(self) -> None:
        self.assertTrue(runner.same_test_schedule("0 6 * * MON-FRI", "0 6 * * 1-5"))
        self.assertFalse(runner.same_test_schedule("0 6 * * *", "0 6 * * 1-5"))
        self.assertFalse(runner.same_test_schedule("0 7 * * 1-5", "0 6 * * 1-5"))


class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_uses_a_resolved_model_without_replacing_its_transport(self) -> None:
        case = next(item for item in runner.load("briefing") if item.id == "no-connector")
        seen = []

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen.extend(messages)
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"repeats": [], "profile": None})],
                provider_details={"cost": 0.001},
            )

        model = FunctionModel(respond)
        with patch.object(runner, "print", create=True) as emit:
            self.assertEqual(
                await runner.run_background(model, [case], model_label="Resolved QA profile"), 0
            )
        row = runner.Evidence.model_validate_json(emit.call_args.args[0])
        self.assertEqual(row.model, "Resolved QA profile")
        self.assertEqual(row.errors, [])
        self.assertTrue(seen)

    async def test_memory_retries_a_quote_joined_across_turns(self) -> None:
        case = next(item for item in runner.load("memory") if item.id == "chosen-oncall")
        quote = case.case.input
        quotes = iter([f"{case.case.history[0].content} {quote}", quote])

        def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"claims": [{"statement": quote, "evidence": next(quotes)}]},
                    )
                ]
            )

        def build_agent(_model: str, **kwargs: object):
            return Agent(FunctionModel(respond), **kwargs)

        with (
            patch.object(runner, "Agent", side_effect=build_agent),
            patch.object(runner, "print", create=True) as emit,
        ):
            self.assertEqual(await runner.run_background("fixture", [case]), 0)
        row = runner.Evidence.model_validate_json(emit.call_args.args[0])
        assert isinstance(row.output, dict)
        self.assertEqual(
            row.output["claims"],
            [
                {
                    "statement": quote,
                    "evidence": quote,
                    "subject": None,
                    "kind": "fact",
                    "profile": False,
                    "episode": None,
                },
            ],
        )

    async def test_briefing_preserves_valid_routine_without_a_retry(self) -> None:
        case = next(item for item in runner.load("briefing") if item.id == "curated-hours")
        scheduled = runner.nightly.RepeatedRequest(
            intent="review-staged-pages",
            evidence=[1, 3, 4],
            title="Staging digest",
            why="3 requests",
            prompt="Read Notion website staging changes",
            required_services=["Notion"],
            cron="0 6 * * 1-5",
            as_agent=False,
        ).model_dump(mode="json")
        candidate_outputs = iter(
            [{"repeats": [scheduled, {**scheduled, "as_agent": True, "cron": None}]}]
        )

        def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, next(candidate_outputs))]
            )

        def build_agent(_model: str, **kwargs: object):
            return Agent(FunctionModel(respond), **kwargs)

        with (
            patch.object(runner, "Agent", side_effect=build_agent),
            patch.object(runner, "print", create=True),
        ):
            self.assertEqual(await runner.run_background("fixture", [case]), 0)

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
    async def test_a_recorded_sandbox_failure_keeps_the_next_case(self) -> None:
        version_id, run_id, next_run_id, conversation_id = (uuid4() for _ in range(4))
        ctx = AuthContext(organization_id=uuid4(), user_id=uuid4(), role=OrgRoleName.OWNER)
        cases = {item.id: item for item in runner.load("agenticos")}
        failed_run = SimpleNamespace(
            id=run_id,
            status="failed",
            conversation_id=conversation_id,
            agent_version_id=version_id,
            error="Sandbox denied the read",
            input_tokens=120,
            output_tokens=20,
            cost_usd=Decimal("0.003"),
            cost_is_partial=False,
        )
        healthy_run = SimpleNamespace(**vars(failed_run))
        healthy_run.id = next_run_id
        healthy_run.status = "completed"
        error = runner.RunFailedError(details={"run_id": str(run_id)})

        @asynccontextmanager
        async def session():
            yield object()

        with (
            patch.object(runner, "get_db_context", session),
            patch.object(runner, "open_eval_conversation", AsyncMock(return_value=conversation_id)),
            patch.object(
                runner.AgentRunnerService,
                "execute",
                AsyncMock(side_effect=[error, ("Cześć!", healthy_run)]),
            ) as execute,
            patch.object(runner.agent_run_repo, "get_run", AsyncMock(return_value=failed_run)),
            patch.object(
                runner.intercepted_tool_call_repo, "list_for_run", AsyncMock(return_value=[])
            ),
            patch.object(runner, "print", create=True) as emit,
        ):
            status = await runner.evaluate_agenticos(
                ctx,
                uuid4(),
                version_id,
                uuid4(),
                "fixture",
                Decimal("0.05"),
                [cases["sandbox-policy-by-connection"], cases["hello-no-tools"]],
            )
        self.assertEqual(status, 1)
        first, next_row = [
            runner.Evidence.model_validate_json(call.args[0]) for call in emit.call_args_list
        ]
        self.assertEqual(first.errors, ["technical: Sandbox denied the read"])
        self.assertEqual(first.attempt, run_id)
        self.assertEqual(first.cost_usd, Decimal("0.003"))
        self.assertEqual(next_row.errors, [])
        self.assertEqual(execute.await_args_list[1].kwargs["run_limit_usd"], Decimal("0.047"))

    async def test_refuses_to_use_a_non_eval_environment(self):
        with (
            patch.dict(runner.os.environ, {"AGENTICOS_PERSONAL_EVAL": "0"}),
            self.assertRaisesRegex(SystemExit, "explicitly isolated test database"),
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
                    agent_version_id=version_id,
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

        args = Namespace(
            organization_id=uuid4(),
            user_id=uuid4(),
            model_profile=None,
            max_usd=None,
            candidate_agent=None,
            candidate_without_browser=False,
        )
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


class NativeCandidateTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_preflight_preserves_publication_and_never_installs(self) -> None:
        source, agent_id, org, user, profile_id = (uuid4() for _ in range(5))
        original = runner.AgentSpec(
            name="Customized", instructions="Keep my policy", model_profile_id=uuid4()
        )
        original_json = original.model_dump(mode="json")
        agent = SimpleNamespace(id=agent_id, current_version_id=source)
        args = Namespace(
            organization_id=org,
            user_id=user,
            candidate_agent=agent_id,
            candidate_without_browser=False,
            model_profile=profile_id,
            max_usd=None,
        )
        ctx = AuthContext(user_id=user, organization_id=org, role=OrgRoleName.OWNER)

        @asynccontextmanager
        async def session():
            yield AsyncMock()

        @asynccontextmanager
        async def serve():
            yield

        with (
            patch.dict(runner.os.environ, {"AGENTICOS_PERSONAL_EVAL": "1"}),
            patch.object(runner, "get_db_context", session),
            patch.object(runner, "job_context", AsyncMock(return_value=ctx)),
            patch.object(runner.agent_repo, "get", AsyncMock(return_value=agent)),
            patch.object(runner.agent_repo, "get_shipped_starter", AsyncMock()) as managed,
            patch.object(
                runner.agent_repo,
                "get_version",
                AsyncMock(return_value=SimpleNamespace(id=source, spec=original_json)),
            ),
            patch.object(
                runner.credential_repo,
                "get_profile",
                AsyncMock(return_value=SimpleNamespace(provider="openrouter", model="fixture")),
            ),
            patch.object(
                runner.AgentRegistryService, "get_candidate_spec", AsyncMock()
            ) as validate,
            patch.object(runner.ShippedAgentService, "review_update", AsyncMock()) as review,
            patch.object(runner.AgentRegistryService, "save_draft", AsyncMock()) as save,
            patch.object(runner.AgentRegistryService, "publish_spec", AsyncMock()) as publish,
            patch.object(runner, "evaluate_agenticos", AsyncMock(return_value=0)) as evaluate,
            patch.object(runner, "serve_eval_mcp", serve),
        ):
            self.assertEqual(await runner.run_agenticos(args, []), 0)
            evaluate.assert_not_awaited()
            candidate = validate.await_args.args[-1]
            self.assertIsInstance(candidate, runner.UnpublishedCandidate)
            self.assertNotEqual(candidate.spec.instructions, original.instructions)
            self.assertEqual(
                candidate.spec.model_dump(exclude={"instructions"}),
                original.model_dump(exclude={"instructions"}),
            )
            self.assertEqual(original.model_dump(mode="json"), original_json)
            args.max_usd = Decimal("0.25")
            self.assertEqual(await runner.run_agenticos(args, []), 0)
            self.assertEqual(evaluate.await_args.args[3], profile_id)
            self.assertIsInstance(
                evaluate.await_args.kwargs["candidate"], runner.UnpublishedCandidate
            )
            validate.side_effect = RuntimeError("candidate access refused")
            with self.assertRaisesRegex(RuntimeError, "access refused"):
                await runner.run_agenticos(args, [])
            self.assertEqual(evaluate.await_count, 1)
            managed.assert_not_awaited()
            review.assert_not_awaited()
            save.assert_not_awaited()
            publish.assert_not_awaited()

    async def test_candidate_receipt_has_source_and_hash_without_published_credit(self) -> None:
        ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
        source, agent_id, run_id, profile_id, chat_id = (uuid4() for _ in range(5))
        candidate = runner.UnpublishedCandidate(
            spec=runner.AgentSpec(name="Fixture", instructions="Candidate policy")
        )
        run = SimpleNamespace(
            id=run_id,
            agent_version_id=None,
            status="completed",
            input_tokens=10,
            output_tokens=5,
            cost_usd=Decimal("0.001"),
            cost_is_partial=False,
        )
        case = next(item for item in runner.load("agenticos") if item.id == "hello-no-tools")

        @asynccontextmanager
        async def session():
            yield AsyncMock()

        with (
            patch.object(runner, "get_db_context", session),
            patch.object(runner, "open_eval_conversation", AsyncMock(return_value=chat_id)),
            patch.object(
                runner.AgentRunnerService, "execute", AsyncMock(return_value=("Cześć!", run))
            ) as execute,
            patch.object(
                runner.intercepted_tool_call_repo, "list_for_run", AsyncMock(return_value=[])
            ),
            patch.object(runner, "print", create=True) as emit,
        ):
            self.assertEqual(
                await runner.evaluate_agenticos(
                    ctx,
                    agent_id,
                    source,
                    profile_id,
                    "fixture",
                    Decimal("0.25"),
                    [case],
                    candidate=candidate,
                ),
                0,
            )
            kwargs = execute.await_args.kwargs
            self.assertIs(kwargs["candidate"], candidate)
            self.assertIsNone(kwargs["version_id"])
            self.assertIsInstance(kwargs["isolation"], runner.RunIsolation)
            self.assertEqual(kwargs["run_limit_usd"], Decimal("0.25"))
            receipt = runner.Evidence.model_validate_json(emit.call_args.args[0])
            self.assertIsNone(receipt.agent_version)
            self.assertEqual(receipt.source_agent_version, source)
            self.assertEqual(
                receipt.candidate_instructions_hash,
                runner.fingerprint(candidate.spec, "instructions"),
            )
            run.agent_version_id = source
            self.assertEqual(
                await runner.evaluate_agenticos(
                    ctx,
                    agent_id,
                    source,
                    profile_id,
                    "fixture",
                    Decimal("0.25"),
                    [case],
                    candidate=candidate,
                ),
                1,
            )
            receipt = runner.Evidence.model_validate_json(emit.call_args.args[0])
            self.assertEqual(
                receipt.errors, ["technical: unexpected candidate version attribution"]
            )
            run.status = "failed"
            run.agent_version_id = None
            run.conversation_id = chat_id
            run.error = "Synthetic provider refusal"
            execute.side_effect = runner.RunFailedError(details={"run_id": str(run_id)})
            with patch.object(runner.agent_run_repo, "get_run", AsyncMock(return_value=run)):
                self.assertEqual(
                    await runner.evaluate_agenticos(
                        ctx,
                        agent_id,
                        source,
                        profile_id,
                        "fixture",
                        Decimal("0.25"),
                        [case],
                        candidate=candidate,
                    ),
                    1,
                )
            receipt = runner.Evidence.model_validate_json(emit.call_args.args[0])
            self.assertEqual(receipt.errors, ["technical: Synthetic provider refusal"])
            self.assertIsNone(receipt.agent_version)
            self.assertEqual(receipt.cost_usd, Decimal("0.001"))
