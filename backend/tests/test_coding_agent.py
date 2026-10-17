"""The coding agent: Claude Code and Codex run headless in the agent's sandbox (#2092).

The harness is never run. A workspace whose shell writes a recorded event stream
where the command said to stands in for the sandbox, so the command line, the
files, the parsing, the booking and the clean-up all run as they would.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import (
    CommandResult,
    Workspace,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
    WrapperWorkspace,
)

from app.agents.capabilities import get
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.budget import SpendLedger, metered_by
from app.agents.capabilities.coding_agent import CodingAgent, CodingAgentConfig
from app.agents.capabilities.coding_agent._harness import (
    MAX_ANSWER_CHARS,
    MAX_STEPS,
    CodingReport,
    claude_report,
    codex_report,
    invocation,
    read_events,
)
from app.agents.capabilities.coding_agent._toolset import LOG_DIR, build_coding_toolset
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_registry import _coding_agent_problems
from tests.workspaces import ShellFailing, document_workspace

pytestmark = pytest.mark.anyio


def _claude_stream(*, result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """A Claude Code session as `--output-format stream-json` prints it."""
    events: list[dict[str, Any]] = [
        {"type": "system", "subtype": "init", "session_id": "s-1", "model": "claude-sonnet-5-5"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Looking."},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "app.py"},
                    },
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "Bash",
                        "input": {"command": "pytest -q"},
                    },
                    {
                        "type": "tool_use",
                        "id": "t3",
                        "name": "Edit",
                        "input": {"file_path": "app.py"},
                    },
                    {"type": "tool_use", "id": "t4", "name": "TodoWrite", "input": {}},
                    {
                        "type": "tool_use",
                        "id": "t5",
                        "name": "Task",
                        "input": {"description": "dig"},
                    },
                    {
                        "type": "tool_use",
                        "id": "t6",
                        "name": "ExitPlanMode",
                        "input": {"plan": "1. Fix app.py"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t2", "is_error": True},
                    {"type": "tool_result", "tool_use_id": "t1", "is_error": False},
                    {"type": "tool_result", "tool_use_id": "unknown", "is_error": True},
                    "not a part",
                ]
            },
        },
    ]
    if result is not None:
        events.append({"type": "result", "session_id": "s-1", **result})
    return events


_CLAUDE_DONE = {
    "subtype": "success",
    "is_error": False,
    "result": "Fixed the off-by-one in app.py.",
    "modelUsage": {
        "claude-sonnet-5-5": {
            "inputTokens": 4,
            "outputTokens": 337,
            "cacheReadInputTokens": 100,
            "cacheCreationInputTokens": 50,
        },
        "broken": "not usage",
    },
    "permission_denials": [{"tool_name": "WebFetch"}, {"tool_name": "ExitPlanMode"}],
}


def _codex_stream(*, end: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A Codex session as `codex exec --json` prints it."""
    events: list[dict[str, Any]] = [
        {"type": "thread.started", "thread_id": "th-1"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "hm"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Reading."}},
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "ls", "exit_code": 0},
        },
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "pytest", "exit_code": 1},
        },
        {
            "type": "item.completed",
            "item": {
                "type": "file_change",
                "status": "completed",
                "changes": [{"path": "app.py", "kind": "update"}, {"path": "app.py"}, "x"],
            },
        },
        {"type": "item.completed", "item": {"type": "file_change", "changes": "none"}},
        {"type": "item.completed", "item": {"type": "web_search", "query": "pydantic"}},
        {
            "type": "item.completed",
            "item": {"type": "mcp_tool_call", "tool": "lookup", "status": "failed"},
        },
        {"type": "item.completed", "item": "not an item"},
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3},
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Done: app.py fixed."},
        },
    ]
    if end is not None:
        events.append(end)
    return events


def _lines(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(event) for event in events)


class TestTheCommand:
    def test_claude_code_plans_in_its_plan_mode_with_the_key_in_the_environment(self) -> None:
        command = invocation(
            "claude_code",
            "plan",
            "Find the bug",
            api_key="sk-a",
            model=None,
            session_id=None,
            base_url=None,
        )
        assert command.argv[:3] == ["claude", "-p", "Find the bug"]
        assert command.argv[6:8] == ["--permission-mode", "plan"]
        assert command.env["ANTHROPIC_API_KEY"] == "sk-a"
        assert "sk-a" not in command.shell_line("log", "err")
        assert "sk-a" not in repr(command)

    def test_claude_code_applies_without_its_own_prompts_continuing_the_session(self) -> None:
        command = invocation(
            "claude_code",
            "apply",
            "Apply it",
            api_key="sk-or",
            model="anthropic/claude-sonnet-5.5",
            session_id="s-1",
            base_url="https://openrouter.ai/api",
        )
        assert "--dangerously-skip-permissions" in command.argv
        assert command.argv[-4:] == ["--model", "anthropic/claude-sonnet-5.5", "--resume", "s-1"]
        assert command.env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert command.env["ANTHROPIC_AUTH_TOKEN"] == "sk-or"
        assert command.env["ANTHROPIC_API_KEY"] == ""
        assert command.env["IS_SANDBOX"] == "1"

    def test_codex_plans_read_only_and_resumes_by_its_thread(self) -> None:
        planned = invocation(
            "codex",
            "plan",
            "Find it",
            api_key="sk-o",
            model="gpt-5.5-codex",
            session_id=None,
            base_url=None,
        )
        assert planned.argv[:2] == ["codex", "exec"]
        assert 'sandbox_mode="read-only"' in planned.argv
        assert planned.argv[-3:] == ["-m", "gpt-5.5-codex", "Find it"]
        assert planned.env == {"CODEX_API_KEY": "sk-o"}

        applied = invocation(
            "codex", "apply", "Do it", api_key="sk-o", model=None, session_id="th-1", base_url=None
        )
        assert applied.argv[:4] == ["codex", "exec", "resume", "th-1"]
        assert "--dangerously-bypass-approvals-and-sandbox" in applied.argv

    def test_the_task_is_one_quoted_word_on_the_shell_line(self) -> None:
        command = invocation(
            "codex",
            "plan",
            "it's; rm -rf /",
            api_key="k",
            model=None,
            session_id=None,
            base_url=None,
        )
        line = command.shell_line("a b.jsonl", "err")
        assert shlex.split(line)[-5:] == ["it's; rm -rf /", ">", "a b.jsonl", "2>", "err"]


class TestReadingClaudeCode:
    def test_a_finished_session_is_its_answer_steps_files_and_spend(self) -> None:
        report, usage = claude_report(
            _claude_stream(result=_CLAUDE_DONE), mode="apply", base_url=None
        )

        assert report.outcome == "completed"
        assert report.answer == "Fixed the off-by-one in app.py."
        assert report.session_id == "s-1"
        assert [(step.kind, step.title, step.failed) for step in report.steps] == [
            ("read", "app.py", False),
            ("command", "pytest -q", True),
            ("edit", "app.py", False),
            ("other", "dig", False),
        ]
        assert report.files_changed == ["app.py"]
        assert report.refused == ["WebFetch"]
        spent = usage.by_model["claude-sonnet-5-5"]
        assert (spent.input_tokens, spent.cache_read_tokens, spent.cache_write_tokens) == (
            154,
            100,
            50,
        )
        assert spent.output_tokens == 337
        assert usage.provider == "anthropic"
        assert list(usage.by_model) == ["claude-sonnet-5-5"]

    def test_a_plan_with_no_closing_text_is_the_plan_it_proposed(self) -> None:
        report, _ = claude_report(
            _claude_stream(result={"subtype": "success", "is_error": False}),
            mode="plan",
            base_url=None,
        )
        assert report.answer == "1. Fix app.py"
        assert report.files_changed == []

    def test_with_neither_the_text_it_wrote_is_the_answer(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Only this."}]}},
            {"type": "result", "subtype": "success"},
        ]
        report, _ = claude_report(events, mode="plan", base_url=None)
        assert report.answer == "Only this."

    def test_a_session_that_errored_is_failed_and_gateway_spend_has_no_provider(self) -> None:
        report, usage = claude_report(
            _claude_stream(result={"subtype": "error_max_turns", "is_error": True}),
            mode="apply",
            base_url="https://openrouter.ai/api",
        )
        assert report.outcome == "failed"
        assert usage.provider is None

    def test_a_session_with_no_result_stopped_before_it_finished(self) -> None:
        report, usage = claude_report(_claude_stream(), mode="apply", base_url=None)
        assert report.outcome == "failed"
        assert "stopped before it finished" in report.answer
        assert len(report.steps) == 4
        assert usage.by_model == {}

    def test_an_empty_answer_says_so_and_a_long_one_is_cut(self) -> None:
        silent, _ = claude_report(
            [{"type": "result", "subtype": "success"}], mode="plan", base_url=None
        )
        assert silent.answer == "(Claude Code sent no answer.)"

        long = "x" * (MAX_ANSWER_CHARS + 5)
        cut, _ = claude_report(
            [{"type": "result", "subtype": "success", "result": long}], mode="plan", base_url=None
        )
        assert cut.answer.endswith("[The answer went on for 5 more characters.]")

    def test_a_long_session_keeps_its_last_steps_and_titles_fit_a_line(self) -> None:
        calls = [
            {"type": "tool_use", "id": f"t{i}", "name": "Grep", "input": {"pattern": f"p{i}"}}
            for i in range(MAX_STEPS + 3)
        ]
        calls.append(
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo " + "y" * 400}}
        )
        events = [
            {"type": "assistant", "message": {"content": calls}},
            {"type": "assistant", "message": "not a message"},
            {"type": "result", "subtype": "success", "result": "ok"},
        ]
        report, _ = claude_report(events, mode="plan", base_url=None)
        assert len(report.steps) == MAX_STEPS
        assert report.steps[0].title == "p4"
        assert report.steps[-1].title.endswith("…")
        assert len(report.steps[-1].title) == 300

    def test_a_tool_with_nothing_to_name_it_by_is_named_for_itself(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "input": "x"}]}},
            {"type": "result", "subtype": "success", "result": "ok"},
        ]
        report, _ = claude_report(events, mode="plan", base_url=None)
        assert [(step.kind, step.title) for step in report.steps] == [("other", "tool")]


class TestReadingCodex:
    def test_a_finished_turn_is_its_last_message_steps_files_and_spend(self) -> None:
        report, usage = codex_report(_codex_stream(end=None), mode="apply", model="gpt-5.5-codex")

        assert report.outcome == "completed"
        assert report.answer == "Done: app.py fixed."
        assert report.session_id == "th-1"
        assert [(step.kind, step.title, step.failed) for step in report.steps] == [
            ("command", "ls", False),
            ("command", "pytest", True),
            ("edit", "app.py", False),
            ("edit", "files", False),
            ("web", "pydantic", False),
            ("other", "lookup", True),
        ]
        assert report.files_changed == ["app.py"]
        spent = usage.by_model["gpt-5.5-codex"]
        assert (spent.input_tokens, spent.cache_read_tokens, spent.output_tokens) == (10, 4, 3)
        assert usage.provider == "openai"

    def test_turns_add_up_and_an_unnamed_model_is_booked_as_codex(self) -> None:
        turn = {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 1}}
        report, usage = codex_report(
            [turn, turn, {"type": "turn.completed"}], mode="plan", model=None
        )
        assert usage.by_model["codex"].input_tokens == 10
        assert report.answer == "(Codex sent no answer.)"

    def test_a_failed_turn_is_the_error_it_gave(self) -> None:
        report, _ = codex_report(
            _codex_stream(end={"type": "turn.failed", "error": {"message": "quota exceeded"}}),
            mode="apply",
            model=None,
        )
        assert (report.outcome, report.answer) == ("failed", "quota exceeded")

        bare, _ = codex_report([{"type": "error"}], mode="plan", model=None)
        assert bare.answer == "Codex stopped with an error."

    def test_a_session_that_never_finished_a_turn_stopped_before_it_finished(self) -> None:
        report, _ = codex_report(
            [{"type": "thread.started", "thread_id": "th-2"}], mode="plan", model=None
        )
        assert report.outcome == "failed"
        assert report.session_id == "th-2"

    def test_lines_that_are_not_events_are_skipped(self) -> None:
        assert read_events('npm warn\n{"type": "x"}\n[1, 2]\n') == [{"type": "x"}]


class _Shell(WrapperWorkspace):
    """A sandbox whose harness prints a recorded stream where it was told to."""

    def __init__(
        self,
        *,
        events: str = "",
        stderr: str = "",
        exit_code: int = 0,
        raises: Exception | None = None,
    ) -> None:
        super().__init__(document_workspace())
        self.events, self.stderr, self.exit_code, self.raises = events, stderr, exit_code, raises
        self.commands: list[tuple[str, Mapping[str, str] | None, float | None]] = []

    async def run(
        self,
        command: Any,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        self.commands.append((command, env, timeout))
        words = shlex.split(command)
        await self.write_bytes(words[words.index(">") + 1], self.events.encode())
        await self.write_bytes(words[words.index("2>") + 1], self.stderr.encode())
        if self.raises is not None:
            raise self.raises
        return CommandResult(exit_code=self.exit_code, stdout="", stderr="")


def _ctx(workspace: Workspace | None, *, retry: int = 0) -> RunContext[AgentDeps]:
    ctx = RunContext(
        deps=AgentDeps(organization_id=uuid4()),
        model=TestModel(),
        usage=RunUsage(),
        retry=retry,
        max_retries=1,
    )
    if workspace is not None:
        ctx.workspace = workspace
    return ctx


def _tools(harness: Any = "claude_code", **overrides: Any) -> Any:
    options: dict[str, Any] = {
        "harness": harness,
        "model": None,
        "base_url": None,
        "api_key": "sk-test",
        "timeout_seconds": 600,
    } | overrides
    return build_coding_toolset(**options).tools


async def _call(tool: str, workspace: Workspace | None, task: str = "Fix it", **kwargs: Any) -> str:
    return await _tools(**kwargs)[tool].function(_ctx(workspace), task=task)


class TestRunningATask:
    async def test_a_plan_runs_the_harness_and_books_its_spend_and_tidies_up(self) -> None:
        shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        ledger = SpendLedger()
        with metered_by(ledger):
            raw = await _call("plan_code_change", shell)

        report = CodingReport.model_validate_json(raw)
        assert report.answer == "Fixed the off-by-one in app.py."
        assert report.mode == "plan"
        ((line, env, timeout),) = shell.commands
        assert "--permission-mode plan" in line and f"{LOG_DIR}/" in line
        assert env is not None and env["ANTHROPIC_API_KEY"] == "sk-test"
        assert timeout == 600
        assert [entry.model_name for entry in ledger.entries] == ["claude-sonnet-5-5"]
        assert [entry.name for entry in await shell.list_dir(LOG_DIR)] == []

    async def test_a_change_continues_the_session_it_is_given(self) -> None:
        shell = _Shell(events=_lines(_codex_stream(end=None)))
        raw = await _tools("codex")["apply_code_change"].function(
            _ctx(shell), task="Apply it", session_id="th-1"
        )
        assert CodingReport.model_validate_json(raw).files_changed == ["app.py"]
        assert shlex.split(shell.commands[0][0])[:4] == ["codex", "exec", "resume", "th-1"]

    async def test_a_task_past_its_time_is_stopped_and_says_so(self) -> None:
        shell = _Shell(events=_lines(_claude_stream()), raises=WorkspaceTimeoutError("slow"))
        report = CodingReport.model_validate_json(await _call("apply_code_change", shell))
        assert report.outcome == "timed_out"
        assert "stopped after 10 minutes" in report.answer
        assert len(report.steps) == 4

    async def test_a_harness_that_printed_nothing_but_errors_says_what(self) -> None:
        shell = _Shell(stderr="Invalid API key\n", exit_code=1)
        report = CodingReport.model_validate_json(await _call("plan_code_change", shell))
        assert (report.outcome, report.answer) == ("failed", "Invalid API key")

    async def test_a_log_already_gone_is_no_failure(self) -> None:
        class _Tidied(_Shell):
            async def remove(self, path: str) -> None:
                raise FileNotFoundError(path)

        shell = _Tidied(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        report = CodingReport.model_validate_json(await _call("plan_code_change", shell))
        assert report.outcome == "completed"

    async def test_a_runtime_without_the_harness_is_named(self) -> None:
        answer = await _call("plan_code_change", _Shell(exit_code=127), harness="codex")
        assert "Codex is not installed" in answer

    async def test_a_sandbox_that_cannot_run_it_is_an_answer(self) -> None:
        shell = _Shell(raises=WorkspaceUnavailableError("gone"))
        answer = await _call("plan_code_change", shell)
        assert answer == "Claude Code could not run in this sandbox (WorkspaceUnavailableError)."

    async def test_a_workspace_whose_files_cannot_be_read_still_reports(self) -> None:
        shell = _Shell(exit_code=0)
        ledger = SpendLedger()
        with metered_by(ledger):
            raw = await _tools()["plan_code_change"].function(
                _ctx(ShellFailing(shell)), task="Look"
            )
        assert CodingReport.model_validate_json(raw).outcome == "failed"
        assert ledger.entries == []

    async def test_an_agent_with_no_sandbox_is_told_to_say_so(self) -> None:
        answer = await _call("plan_code_change", None)
        assert "needs a sandbox with a shell" in answer

    async def test_an_empty_task_or_a_missing_key_asks_again(self) -> None:
        with pytest.raises(ModelRetry, match="Describe the task"):
            await _call("plan_code_change", _Shell(), task="  ")
        with pytest.raises(ModelRetry, match="no API key"):
            await _call("plan_code_change", _Shell(), api_key=None)


class TestConfiguringIt:
    def test_only_claude_code_takes_another_endpoint(self) -> None:
        with pytest.raises(ValidationError, match="Only Claude Code"):
            CodingAgentConfig(harness="codex", base_url="https://openrouter.ai/api")

    def test_the_builder_reads_the_key_the_endpoint_and_the_time_limit(self) -> None:
        definition = get("coding_agent")
        binding = CapabilityBinding(
            capability_id="coding_agent",
            config={"base_url": "https://openrouter.ai/api/", "timeout_minutes": 5},
        )
        built = definition.builder(
            CapabilityBuildContext(
                binding=binding,
                config=definition.validate_config(binding.config),
                resources={},
                secret=ApiKeySecret(api_key="sk-or-gateway"),
            )
        )
        assert isinstance(built, CodingAgent)
        assert (built.base_url, built.timeout_seconds, built.api_key) == (
            "https://openrouter.ai/api",
            300,
            "sk-or-gateway",
        )
        toolset = built.get_toolset()
        assert isinstance(toolset, FunctionToolset)
        assert set(toolset.tools) == {"plan_code_change", "apply_code_change"}
        assert built.get_toolset() is built.get_toolset()

    def test_a_binding_with_no_secret_builds_without_a_key(self) -> None:
        definition = get("coding_agent")
        binding = CapabilityBinding(capability_id="coding_agent")
        built = definition.builder(
            CapabilityBuildContext(binding=binding, config=None, resources={}, secret=None)
        )
        assert isinstance(built, CodingAgent) and built.api_key is None


class TestPublishing:
    @staticmethod
    def _spec(*bindings: dict[str, Any]) -> AgentSpec:
        return AgentSpec.model_validate(
            {"name": "coder", "model_profile_id": str(uuid4()), "capabilities": list(bindings)}
        )

    @pytest.mark.parametrize(
        "sandbox",
        [
            None,
            {"id": "sandbox", "config": {"backend": "state"}},
            {"id": "sandbox", "config": {"backend": "service", "include_execute": False}},
        ],
    )
    def test_a_coding_agent_without_a_shell_is_refused(
        self, sandbox: dict[str, Any] | None
    ) -> None:
        bindings = [{"id": "coding_agent"}] + ([sandbox] if sandbox else [])
        assert _coding_agent_problems(self._spec(*bindings)) != []

    def test_one_on_a_sandbox_connection_with_a_shell_publishes(self) -> None:
        spec = self._spec(
            {"id": "coding_agent"}, {"id": "sandbox", "config": {"backend": "service"}}
        )
        assert _coding_agent_problems(spec) == []

    def test_an_agent_without_one_is_not_asked(self) -> None:
        assert _coding_agent_problems(self._spec({"id": "coding_agent", "enabled": False})) == []
