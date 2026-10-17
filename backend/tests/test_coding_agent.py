"""The coding agent: Claude Code and Codex run headless in the agent's sandbox (#2092).

The harness is never run. A workspace whose shell writes a recorded event stream
where the command said to stands in for the sandbox, so the command line, the
files, the parsing, the booking and the clean-up all run as they would.
"""

from __future__ import annotations

import base64
import json
import shlex
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials
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
    codex_auth_file,
    codex_report,
    invocation,
    read_events,
    rotated_sign_in,
)
from app.agents.capabilities.coding_agent._toolset import (
    AUTH_ENV,
    LOG_DIR,
    READ_AUTH,
    WRITE_AUTH,
    build_coding_toolset,
)
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret, OpenAICodexSecret, SecretKind
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
        auth_after: str = "",
        auth_raises: Exception | None = None,
    ) -> None:
        super().__init__(document_workspace())
        self.events, self.stderr, self.exit_code, self.raises = events, stderr, exit_code, raises
        self.auth_after, self.auth_raises = auth_after, auth_raises
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
        if command in (WRITE_AUTH, READ_AUTH):
            if self.auth_raises is not None:
                raise self.auth_raises
            stdout = self.auth_after if command == READ_AUTH else ""
            return CommandResult(exit_code=0, stdout=stdout, stderr="")
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

    async def test_a_sandbox_the_service_will_not_open_is_an_answer(self) -> None:
        """A runtime still building answers 409, which the sandboxd client raises unmapped."""
        refused = httpx.HTTPStatusError(
            "409 Conflict",
            request=httpx.Request("POST", "http://sandboxd/sessions"),
            response=httpx.Response(409),
        )
        answer = await _call("plan_code_change", _Shell(raises=refused))
        assert answer == "Claude Code could not run in this sandbox (HTTPStatusError)."

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


def _jwt(claims: dict[str, Any]) -> str:
    def part(value: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2ln"


ACCESS = _jwt(
    {
        "iat": 1_760_000_000,
        "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
        "https://api.openai.com/profile": {"email": "kacper@example.com"},
    }
)
SIGNED_IN = OpenAICodexCredentials(access_token=ACCESS, refresh_token="rt-1", account_id="acc-1")


class TestSubscriptions:
    def test_a_claude_subscription_token_goes_where_claude_code_reads_one(self) -> None:
        command = invocation(
            "claude_code",
            "plan",
            "x",
            api_key="sk-ant-oat01-abc",
            model=None,
            session_id=None,
            base_url=None,
        )
        assert command.env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-abc"
        assert "ANTHROPIC_API_KEY" not in command.env

    def test_claude_code_without_any_credential_is_a_mistake(self) -> None:
        with pytest.raises(UserError):
            invocation(
                "claude_code", "plan", "x", api_key=None, model=None, session_id=None, base_url=None
            )

    def test_codex_on_a_sign_in_carries_no_key(self) -> None:
        command = invocation(
            "codex", "plan", "x", api_key=None, model=None, session_id=None, base_url=None
        )
        assert command.env == {}

    def test_a_sign_in_becomes_the_auth_file_the_codex_cli_reads(self) -> None:
        auth = json.loads(codex_auth_file(SIGNED_IN))
        tokens = auth["tokens"]
        assert (tokens["access_token"], tokens["refresh_token"], tokens["account_id"]) == (
            ACCESS,
            "rt-1",
            "acc-1",
        )
        header, body, signature = tokens["id_token"].split(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        assert claims["https://api.openai.com/auth"] == {
            "chatgpt_plan_type": "plus",
            "chatgpt_account_id": "acc-1",
        }
        assert claims["email"] == "kacper@example.com"
        assert auth["last_refresh"] == "2025-10-09T08:53:20Z"
        assert OpenAICodexCredentials.from_codex_cli_auth(auth).refresh_token == "rt-1"

    def test_an_opaque_access_token_still_makes_an_auth_file(self) -> None:
        auth = json.loads(
            codex_auth_file(
                OpenAICodexCredentials(access_token="opaque", refresh_token="r", account_id="a")
            )
        )
        assert auth["tokens"]["account_id"] == "a"
        bad = json.loads(
            codex_auth_file(
                OpenAICodexCredentials(access_token="a.!!!.b", refresh_token="r", account_id="a")
            )
        )
        assert "email" not in bad["tokens"]["id_token"]

    def test_only_tokens_codex_rotated_are_kept(self) -> None:
        same = codex_auth_file(SIGNED_IN)
        assert rotated_sign_in(same, SIGNED_IN) is None
        moved = json.loads(same)
        moved["tokens"] |= {"access_token": "new-access", "refresh_token": "rt-2"}
        rotated = rotated_sign_in(json.dumps(moved), SIGNED_IN)
        assert rotated is not None and rotated.refresh_token == "rt-2"
        for broken in ("", "not json", "[1]", json.dumps({"tokens": {}})):
            assert rotated_sign_in(broken, SIGNED_IN) is None


class _Store:
    """Where a ChatGPT sign-in lives, as the vault would keep it."""

    def __init__(self, *, gone: bool = False) -> None:
        self.gone = gone
        self.saved: list[OpenAICodexCredentials] = []

    async def load(self) -> OpenAICodexCredentials:
        if self.gone:
            raise BadRequestError(
                message="The ChatGPT sign-in this model runs on is no longer in the vault"
            )
        return SIGNED_IN

    async def save(self, credentials: OpenAICodexCredentials) -> None:
        self.saved.append(credentials)


class TestCodexOnASignIn:
    async def _run(self, shell: _Shell, store: _Store, **overrides: Any) -> str:
        options: dict[str, Any] = {"api_key": None, "sign_in": lambda _org: store} | overrides
        return await _tools("codex", **options)["plan_code_change"].function(
            _ctx(shell), task="Look"
        )

    async def test_the_sign_in_is_written_for_the_task_and_what_codex_rotated_is_kept(self) -> None:
        rotated = json.loads(codex_auth_file(SIGNED_IN))
        rotated["tokens"]["refresh_token"] = "rt-2"
        shell = _Shell(events=_lines(_codex_stream(end=None)), auth_after=json.dumps(rotated))
        store = _Store()

        report = CodingReport.model_validate_json(await self._run(shell, store))

        assert report.outcome == "completed"
        written, task, read = shell.commands
        assert written[0] == WRITE_AUTH and written[1] is not None
        assert json.loads(written[1][AUTH_ENV])["tokens"]["refresh_token"] == "rt-1"
        assert "CODEX_API_KEY" not in (task[1] or {})
        assert read[0] == READ_AUTH
        assert [saved.refresh_token for saved in store.saved] == ["rt-2"]

    async def test_a_sign_in_that_was_not_rotated_is_left_alone(self) -> None:
        store = _Store()
        shell = _Shell(
            events=_lines(_codex_stream(end=None)), auth_after=codex_auth_file(SIGNED_IN)
        )
        await self._run(shell, store)
        assert store.saved == []

    async def test_a_sign_in_removed_from_the_vault_is_an_answer(self) -> None:
        answer = await self._run(_Shell(), _Store(gone=True))
        assert "no longer in the vault" in answer

    async def test_a_sandbox_that_cannot_take_the_sign_in_is_an_answer(self) -> None:
        answer = await self._run(_Shell(auth_raises=WorkspaceUnavailableError("gone")), _Store())
        assert answer == "Codex could not run in this sandbox (WorkspaceUnavailableError)."

    async def test_a_sign_in_that_cannot_be_read_back_is_logged_not_fatal(self) -> None:
        class _Unreadable(_Shell):
            async def run(self, command: Any, **kwargs: Any) -> CommandResult:
                if command == READ_AUTH:
                    raise WorkspaceUnavailableError("gone")
                return await super().run(command, **kwargs)

        store = _Store()
        report = CodingReport.model_validate_json(
            await self._run(_Unreadable(events=_lines(_codex_stream(end=None))), store)
        )
        assert report.outcome == "completed" and store.saved == []

    async def test_outside_an_organization_there_is_no_sign_in_to_read(self) -> None:
        ctx = _ctx(_Shell())
        ctx.deps.organization_id = None
        store = _Store()
        answer = await _tools("codex", api_key=None, sign_in=lambda _org: store)[
            "plan_code_change"
        ].function(ctx, task="Look")
        assert "only inside an organization" in answer


class TestCredentialsThatDoNotFit:
    @pytest.mark.parametrize(
        ("harness", "overrides", "says"),
        [
            (
                "claude_code",
                {"api_key": None, "sign_in": lambda _org: _Store()},
                "works only for Codex",
            ),
            ("codex", {"api_key": "sk-ant-oat01-x"}, "works only for Claude Code"),
            (
                "claude_code",
                {"api_key": "sk-ant-oat01-x", "base_url": "https://openrouter.ai/api"},
                "not to a gateway",
            ),
        ],
    )
    async def test_a_mismatch_is_said_before_anything_runs(
        self, harness: Any, overrides: dict[str, Any], says: str
    ) -> None:
        shell = _Shell()
        answer = await _tools(harness, **overrides)["plan_code_change"].function(
            _ctx(shell), task="x"
        )
        assert says in answer
        assert shell.commands == []


class TestChoosingAModel:
    def test_the_model_is_named_as_the_harness_names_it(self) -> None:
        assert CodingAgentConfig(model="anthropic:claude-opus-5-5").model_id == "claude-opus-5-5"
        assert CodingAgentConfig().model_id is None

    def test_a_model_of_the_other_vendor_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="Claude Code runs Claude models"):
            CodingAgentConfig(harness="codex", model="anthropic:claude-opus-5-5")

    def test_the_builder_offers_each_harness_its_own_models(self) -> None:
        when = CodingAgentConfig.model_json_schema()["properties"]["model"]["x-enum-when"]
        assert when["field"] == "harness"
        assert all(model.startswith("anthropic:") for model in when["choices"]["claude_code"])
        assert all(model.startswith("openai:") for model in when["choices"]["codex"])

    def test_every_model_offered_has_a_name(self) -> None:
        schema = CodingAgentConfig.model_json_schema()["properties"]["model"]
        offered = next(branch["enum"] for branch in schema["anyOf"] if "enum" in branch)
        assert set(offered) == set(schema["x-enum-labels"])

    def test_a_chatgpt_sign_in_satisfies_the_key_it_asks_for(self) -> None:
        requirement = get("coding_agent").secret
        assert requirement is not None
        assert requirement.accepts(SecretKind.API_KEY.value)
        assert requirement.accepts(SecretKind.OPENAI_CODEX.value)
        assert not requirement.accepts(SecretKind.AWS_CREDENTIALS.value)

    def test_the_builder_hands_a_sign_in_over_as_where_it_lives(self) -> None:
        definition = get("coding_agent")
        binding = CapabilityBinding(
            capability_id="coding_agent", config={"harness": "codex"}, secret_id=uuid4()
        )
        built = definition.builder(
            CapabilityBuildContext(
                binding=binding,
                config=definition.validate_config(binding.config),
                resources={},
                secret=OpenAICodexSecret(
                    access_token="a" * 20, refresh_token="r" * 20, account_id="acc"
                ),
            )
        )
        assert isinstance(built, CodingAgent)
        assert built.api_key is None and built.sign_in is not None
        assert repr(built.sign_in(uuid4())).startswith("VaultCodexCredentials(")
