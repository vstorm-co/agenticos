"""The coding agent: Claude Code and Codex run headless in the agent's sandbox (#2092).

The harness is never run. A workspace whose shell plays a detached harness - it
writes a recorded event stream where the command said to, and an exit code when
it is done, and answers the platform's polls from those files - stands in for
the sandbox, so the command line, the polling, the live frames, the parsing, the
booking, the session and the clean-up all run as they would.
"""

import base64
import contextlib
import json
import re
import shlex
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import anyio
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
    WorkspaceUnavailableError,
    WrapperWorkspace,
)

from app.agents.audience import RunAudience
from app.agents.capabilities import get
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.budget import SpendLedger, metered_by
from app.agents.capabilities.coding_agent import CodingAgent, CodingAgentConfig, _task
from app.agents.capabilities.coding_agent._harness import (
    MAX_ANSWER_CHARS,
    MAX_STEPS,
    CodingReport,
    CodingStep,
    Said,
    StepEnded,
    StepStarted,
    claude_report,
    codex_auth_file,
    codex_report,
    invocation,
    live_items,
    rotated_sign_in,
)
from app.agents.capabilities.coding_agent._task import WORK_DIR, session_path, task_files
from app.agents.capabilities.coding_agent._toolset import (
    AUTH_ENV,
    CODEX_HOMES,
    DISCARD_ENV,
    HOME_ENV,
    READ_AUTH,
    SESSIONS_ENV,
    UNREPORTED,
    WRITE_AUTH,
    build_coding_toolset,
)
from app.agents.capabilities.subagents import _journal
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.agents.subagent_events import SubagentEvent
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
    "permission_denials": [{"tool_name": "WebFetch"}, {"tool_name": "TodoWrite"}],
}


def _codex_stream(*, end: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A Codex session as `codex exec --json` prints it."""
    events: list[dict[str, Any]] = [
        {"type": "thread.started", "thread_id": "th-1"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "hm"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Reading."}},
        {
            "type": "item.completed",
            "item": {
                "id": "i1",
                "type": "command_execution",
                "command": "/bin/bash -lc ls",
                "exit_code": 0,
            },
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
    def test_claude_code_read_only_has_no_tool_that_writes_not_even_the_shell(self) -> None:
        """No list of command prefixes keeps a shell read-only - `git log
        --output=<file>` matches `git log` - so a read-only session has none."""
        command = invocation(
            "claude_code",
            "read_only",
            "Find the bug",
            api_key="sk-a",
            model=None,
            session_id=None,
            base_url=None,
        )
        assert command.argv[:2] == ["claude", "-p"]
        assert command.argv[-2:] == ["--", "Find the bug"]
        flags = command.argv[command.argv.index("--permission-mode") :]
        assert flags[:4] == [
            "--permission-mode",
            "plan",
            "--disallowedTools",
            "Edit,MultiEdit,Write,NotebookEdit,Bash",
        ]
        assert "--allowedTools" not in flags
        assert "nobody can approve" in flags[flags.index("--append-system-prompt") + 1].lower()
        assert command.env["ANTHROPIC_API_KEY"] == "sk-a"
        assert "sk-a" not in command.detached_line(task_files("t"))
        assert "sk-a" not in repr(command)

    def test_claude_code_edits_without_its_own_prompts_continuing_the_session(self) -> None:
        command = invocation(
            "claude_code",
            "edit",
            "Apply it",
            api_key="sk-or",
            model="anthropic/claude-sonnet-5.5",
            session_id="s-1",
            base_url="https://openrouter.ai/api",
        )
        assert "--dangerously-skip-permissions" in command.argv
        assert command.argv[-6:] == [
            "--model",
            "anthropic/claude-sonnet-5.5",
            "--resume",
            "s-1",
            "--",
            "Apply it",
        ]
        assert command.env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert command.env["ANTHROPIC_AUTH_TOKEN"] == "sk-or"
        assert command.env["ANTHROPIC_API_KEY"] == ""
        assert command.env["IS_SANDBOX"] == "1"

    def test_codex_edits_bypassing_its_own_sandbox_and_resumes_by_its_thread(self) -> None:
        fresh = invocation(
            "codex",
            "edit",
            "Do it",
            api_key="sk-o",
            model="gpt-5.5-codex",
            session_id=None,
            base_url=None,
        )
        assert fresh.argv[:2] == ["codex", "exec"]
        assert "--dangerously-bypass-approvals-and-sandbox" in fresh.argv
        assert fresh.argv[-4:] == ["-m", "gpt-5.5-codex", "--", "Do it"]
        assert fresh.env == {"CODEX_API_KEY": "sk-o"}

        resumed = invocation(
            "codex", "edit", "Do it", api_key="sk-o", model=None, session_id="th-1", base_url=None
        )
        assert resumed.argv[:4] == ["codex", "exec", "resume", "th-1"]

    @pytest.mark.parametrize("harness", ["claude_code", "codex"])
    def test_a_task_or_a_session_that_looks_like_a_flag_is_never_one(self, harness: str) -> None:
        command = invocation(
            harness,  # type: ignore[arg-type]
            "edit",
            "--help",
            api_key="sk-o",
            model=None,
            session_id="--dangerously-skip-permissions",
            base_url=None,
        )
        assert command.argv[-2:] == ["--", "--help"]
        assert "--resume" not in command.argv and "resume" not in command.argv

    def test_codex_has_no_read_only_mode_to_run(self) -> None:
        """Its read-only mode is a sandbox of its own, which cannot start in a container."""
        with pytest.raises(UserError, match="only with access to change files"):
            invocation(
                "codex", "read_only", "x", api_key="k", model=None, session_id=None, base_url=None
            )

    def test_the_task_is_one_quoted_word_of_a_detached_session(self) -> None:
        command = invocation(
            "codex",
            "edit",
            "it's; rm -rf /",
            api_key="k",
            model=None,
            session_id=None,
            base_url=None,
        )
        files = task_files("a b")
        line = command.detached_line(files)
        words = shlex.split(line)
        assert words[:4] == ["setsid", "nohup", "sh", "-c"]
        # The group's id goes to the platform, never to a file the harness can edit.
        assert words[-3:] == ["&", "echo", "$!"]
        inner = shlex.split(words[4])
        assert "it's; rm -rf /" in inner
        assert inner[-3:] == ["$?", ">", files.status]


class TestReadingClaudeCode:
    def test_a_finished_session_is_its_answer_steps_files_and_spend(self) -> None:
        report, usage = claude_report(
            _claude_stream(result=_CLAUDE_DONE), access="edit", base_url=None
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

    def test_with_neither_the_text_it_wrote_is_the_answer(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Only this."}]}},
            {"type": "result", "subtype": "success"},
        ]
        report, _ = claude_report(events, access="read_only", base_url=None)
        assert report.answer == "Only this."

    def test_a_session_that_errored_is_failed_and_gateway_spend_has_no_provider(self) -> None:
        report, usage = claude_report(
            _claude_stream(result={"subtype": "error_max_turns", "is_error": True}),
            access="edit",
            base_url="https://openrouter.ai/api",
        )
        assert report.outcome == "failed"
        assert usage.provider is None

    def test_a_session_with_no_result_stopped_before_it_finished(self) -> None:
        report, usage = claude_report(_claude_stream(), access="edit", base_url=None)
        assert report.outcome == "failed"
        assert "stopped before it finished" in report.answer
        assert len(report.steps) == 4
        assert usage.by_model == {}

    def test_an_empty_answer_says_so_and_a_long_one_is_cut(self) -> None:
        silent, _ = claude_report(
            [{"type": "result", "subtype": "success"}], access="read_only", base_url=None
        )
        assert silent.answer == "(Claude Code sent no answer.)"

        long = "x" * (MAX_ANSWER_CHARS + 5)
        cut, _ = claude_report(
            [{"type": "result", "subtype": "success", "result": long}],
            access="read_only",
            base_url=None,
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
        report, _ = claude_report(events, access="read_only", base_url=None)
        assert len(report.steps) == MAX_STEPS
        assert report.steps[0].title == "p4"
        assert report.steps[-1].title.endswith("…")
        assert len(report.steps[-1].title) == 300

    def test_a_tool_with_nothing_to_name_it_by_is_named_for_itself(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "input": "x"}]}},
            {"type": "result", "subtype": "success", "result": "ok"},
        ]
        report, _ = claude_report(events, access="read_only", base_url=None)
        assert [(step.kind, step.title) for step in report.steps] == [("other", "tool")]


class TestReadingCodex:
    def test_a_finished_turn_is_its_last_message_steps_files_and_spend(self) -> None:
        report, usage = codex_report(_codex_stream(end=None), access="edit", model="gpt-5.5-codex")

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
            [turn, turn, {"type": "turn.completed"}], access="read_only", model=None
        )
        assert usage.by_model["codex"].input_tokens == 10
        assert report.answer == "(Codex sent no answer.)"

    def test_a_failed_turn_is_the_error_it_gave(self) -> None:
        report, _ = codex_report(
            _codex_stream(end={"type": "turn.failed", "error": {"message": "quota exceeded"}}),
            access="edit",
            model=None,
        )
        assert (report.outcome, report.answer) == ("failed", "quota exceeded")

        bare, _ = codex_report([{"type": "error"}], access="read_only", model=None)
        assert bare.answer == "Codex stopped with an error."

    def test_a_session_that_never_finished_a_turn_stopped_before_it_finished(self) -> None:
        report, _ = codex_report(
            [{"type": "thread.started", "thread_id": "th-2"}], access="read_only", model=None
        )
        assert report.outcome == "failed"
        assert report.session_id == "th-2"

    def test_lines_that_are_not_events_are_skipped(self) -> None:
        assert _task._Reader().take(b'npm warn\n{"type": "x"}\n[1, 2]\n') == [{"type": "x"}]

    def test_an_event_keeps_no_string_past_its_ceiling(self) -> None:
        """A task runs for up to an hour in the worker's memory, and a harness
        repeats every file it read inside its events."""
        output = "x" * (_task.MAX_STRING_CHARS + 10)
        line = json.dumps({"type": "tool", "result": [{"text": output}], "tokens": 7})
        (event,) = _task._Reader().take(line.encode() + b"\n")
        assert len(event["result"][0]["text"]) == _task.MAX_STRING_CHARS
        assert event["tokens"] == 7

    def test_a_long_task_keeps_only_the_outline_of_its_later_events(self, monkeypatch) -> None:
        """Bounded lines still add up over an hour: past the budget an event is kept
        with its strings cut short, so the report still reads kinds, paths and
        usage, while every event still reaches the person whole."""
        monkeypatch.setattr(_task, "MAX_RETAINED_BYTES", 1500)
        reader = _task._Reader()
        output = "x" * 1000
        line = json.dumps({"type": "user", "content": output, "usage": {"input_tokens": 7}})
        first, second = reader.take(f"{line}\n{line}\n".encode())

        assert first["content"] == second["content"] == output
        kept_whole, outlined = reader.events
        assert kept_whole["content"] == output
        assert len(outlined["content"]) == _task.OUTLINE_CHARS
        assert outlined["usage"] == {"input_tokens": 7}

    def test_a_line_past_its_ceiling_is_dropped_whole(self, monkeypatch) -> None:
        monkeypatch.setattr(_task, "MAX_LINE_BYTES", 16)
        reader = _task._Reader()
        assert reader.take(b'{"type": "a"}\n{"type": "huge", "x": "') == [{"type": "a"}]
        assert reader.pending == b"" and reader.skipping
        assert reader.take(b'yyyy"}\n{"type": "b"}\n') == [{"type": "b"}]
        assert not reader.skipping


_TASK_FILE = re.compile(r"\.agenticos/coding-agent/[0-9a-f]+\.(?:jsonl|err|exit)")
GROUP = 4242


class _Shell(WrapperWorkspace):
    """A sandbox playing a detached harness that prints a recorded stream.

    Starting it writes the events and stderr where the line says, and - unless it
    `hangs` - the exit code, and prints its process group; a poll answers with the
    bytes past its offset, base64, and - once the group is gone - the exit code,
    as the real one-line poll does. A harness that `hangs` keeps its group alive
    whatever its exit-code file says.
    """

    def __init__(
        self,
        *,
        events: str = "",
        stderr: str = "",
        exit_code: int = 0,
        raises: Exception | None = None,
        hangs: bool = False,
        auth_after: str = "",
        auth_raises: Exception | None = None,
        fails_resumed: bool = False,
    ) -> None:
        super().__init__(document_workspace())
        self.events, self.stderr, self.exit_code, self.raises = events, stderr, exit_code, raises
        self.hangs, self.fails_resumed = hangs, fails_resumed
        self.auth_after, self.auth_raises = auth_after, auth_raises
        self.commands: list[tuple[str, Mapping[str, str] | None, float | None]] = []
        self.stopped = 0

    @property
    def started(self) -> list[str]:
        """The harness lines started, in order."""
        return [command for command, _, _ in self.commands if command.startswith("setsid")]

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
        if command.startswith("setsid"):
            return await self._start(command)
        if "tail -c +" in command:
            return await self._poll(command)
        if f"pkill -TERM -g {GROUP}" in command:
            self.stopped += 1
        elif command.startswith("rm -f "):
            for path in shlex.split(command)[2:]:
                with contextlib.suppress(FileNotFoundError):
                    await self.remove(path)
        return CommandResult(exit_code=0, stdout="", stderr="")

    async def _start(self, command: str) -> CommandResult:
        if self.raises is not None:
            raise self.raises
        paths = {path.rsplit(".", 1)[1]: path for path in _TASK_FILE.findall(command)}
        resumed = "--resume" in command or " resume " in command
        events = "" if resumed and self.fails_resumed else self.events
        await self.write_bytes(paths["jsonl"], events.encode())
        await self.write_bytes(paths["err"], self.stderr.encode())
        if not self.hangs:
            code = 1 if resumed and self.fails_resumed else self.exit_code
            await self.write_bytes(paths["exit"], f"{code}\n".encode())
        return CommandResult(exit_code=0, stdout=f"{GROUP}\n", stderr="")

    async def _poll(self, command: str) -> CommandResult:
        assert f"pgrep -g {GROUP}" in command
        offset = int(command.split("tail -c +", 1)[1].split(" ", 1)[0]) - 1
        events, status = (
            next(path for path in _TASK_FILE.findall(command) if path.endswith(ext))
            for ext in (".jsonl", ".exit")
        )
        data = await self._bytes(events)
        chunk = data[offset : offset + _task.CHUNK_BYTES]
        state = "running" if self.hangs else f"exited:{(await self._bytes(status)).decode()}"
        return CommandResult(
            exit_code=0, stdout=f"{base64.b64encode(chunk).decode()}\n{state}\n", stderr=""
        )

    async def _bytes(self, path: str) -> bytes:
        try:
            return await self.read_bytes(path)
        except FileNotFoundError:
            return b""


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Polls back to back: a test waits on nothing but its own events."""
    monkeypatch.setattr(_task, "POLL_SECONDS", 0)


# The conversation a test's run answers in, and the person it runs for.
THREAD = uuid4()
RUNNER = uuid4()


def _ctx(
    workspace: Workspace | None,
    *,
    retry: int = 0,
    frames: list[SubagentEvent] | None = None,
    audience: RunAudience | None = None,
) -> RunContext[AgentDeps]:
    async def sink(frame: SubagentEvent) -> None:
        if frames is not None:
            frames.append(frame)

    ctx = RunContext(
        deps=AgentDeps(
            organization_id=uuid4(),
            user_id=str(RUNNER),
            conversation_id=THREAD,
            subagent_events=sink,
            # The person asking - not merely who the run is billed to.
            audience=audience or RunAudience(user_id=RUNNER),
        ),
        model=TestModel(),
        usage=RunUsage(),
        retry=retry,
        max_retries=1,
        tool_call_id="call-1",
    )
    if workspace is not None:
        ctx.workspace = workspace
    return ctx


def _tools(harness: Any = "claude_code", **overrides: Any) -> Any:
    options: dict[str, Any] = {
        "harness": harness,
        "access": "edit",
        "model": None,
        "base_url": None,
        "api_key": "sk-test",
        "timeout_seconds": 600,
    } | overrides
    return build_coding_toolset(**options).tools


async def _call(
    workspace: Workspace | None,
    task: str = "Fix it",
    *,
    frames: list[SubagentEvent] | None = None,
    fresh_session: bool = False,
    conversation_id: UUID | None = THREAD,
    **kwargs: Any,
) -> str:
    ctx = _ctx(workspace, frames=frames)
    ctx.deps.conversation_id = conversation_id
    return await _tools(**kwargs)["run_coding_agent"].function(
        ctx, task=task, fresh_session=fresh_session
    )


_SPENDING = [
    {
        "type": "assistant",
        "message": {
            "id": "m1",
            "model": "claude-sonnet-5-5",
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5},
            "content": [{"type": "text", "text": "Looking."}],
        },
    },
    # The same message again, for its next block: counted once.
    {
        "type": "assistant",
        "message": {
            "id": "m1",
            "model": "claude-sonnet-5-5",
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5},
            "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}],
        },
    },
    {
        "type": "assistant",
        "message": {
            "id": "m2",
            "model": "claude-sonnet-5-5",
            "usage": {"input_tokens": 1, "cache_creation_input_tokens": 4, "output_tokens": 7},
            "content": [{"type": "text", "text": "Still going."}],
        },
    },
    {"type": "assistant", "message": {"id": "m3", "content": []}},
]


class TestSpendOfATaskThatDidNotFinish:
    def test_an_unfinished_session_is_booked_from_its_messages(self) -> None:
        report, usage = claude_report(_SPENDING, access="edit", base_url=None)
        assert report.outcome == "failed"
        (spent,) = usage.by_model.values()
        assert (spent.input_tokens, spent.cache_read_tokens, spent.cache_write_tokens) == (
            105,
            90,
            4,
        )
        assert spent.output_tokens == 12

    @pytest.mark.security
    async def test_a_task_stopped_mid_way_still_books_what_it_spent(self) -> None:
        """Booked only on finishing, a task stopped late each time walked past
        the budget."""

        class _StoppedAfterAStep(_Shell):
            polls = 0

            async def _poll(self, command: str) -> CommandResult:
                self.polls += 1
                if self.polls > 1:
                    raise anyio.get_cancelled_exc_class()
                return await super()._poll(command)

        shell = _StoppedAfterAStep(events=_lines(_SPENDING), hangs=True)
        ledger = SpendLedger()
        with metered_by(ledger), pytest.raises(anyio.get_cancelled_exc_class()):
            await _call(shell)
        assert [entry.model_name for entry in ledger.entries] == ["claude-sonnet-5-5"]
        assert ledger.input_tokens == 105
        assert shell.stopped == 1

        # Codex's finished turns, the same way.
        codex = _StoppedAfterAStep(events=_lines(_codex_stream(end=None)), hangs=True)
        ledger = SpendLedger()
        with metered_by(ledger), pytest.raises(anyio.get_cancelled_exc_class()):
            await _call(codex, harness="codex")
        assert ledger.input_tokens > 0

    async def test_a_sandbox_lost_mid_task_still_books_what_it_spent(self) -> None:
        class _LostAfterAStep(_Shell):
            polls = 0

            async def _poll(self, command: str) -> CommandResult:
                self.polls += 1
                if self.polls > 1:
                    raise WorkspaceUnavailableError("gone")
                return await super()._poll(command)

        shell = _LostAfterAStep(events=_lines(_SPENDING), hangs=True)
        ledger = SpendLedger()
        with metered_by(ledger):
            answer = await _call(shell)
        assert answer == "Claude Code could not run in this sandbox (WorkspaceUnavailableError)."
        assert ledger.input_tokens == 105


class TestRunningATask:
    async def test_a_task_runs_detached_books_its_spend_keeps_its_session_and_tidies_up(
        self,
    ) -> None:
        shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        ledger = SpendLedger()
        with metered_by(ledger):
            raw = await _call(shell, access="read_only")

        report = CodingReport.model_validate_json(raw)
        # The console tells a report from a sentence by its kind, a default.
        assert json.loads(raw)["kind"] == "coding_agent"
        assert report.answer == "Fixed the off-by-one in app.py."
        assert report.access == "read_only"
        ((line, env, timeout),) = [
            command for command in shell.commands if command[0].startswith("setsid")
        ]
        assert "--permission-mode plan" in line and f"{WORK_DIR}/" in line
        assert env is not None and env["ANTHROPIC_API_KEY"] == "sk-test"
        assert timeout == 60
        assert [entry.model_name for entry in ledger.entries] == ["claude-sonnet-5-5"]
        assert await shell.read_bytes(session_path("claude_code", THREAD)) == b"s-1"
        assert [entry.name for entry in await shell.list_dir(WORK_DIR)] == [
            f"claude_code-{THREAD}.session"
        ]
        assert shell.stopped == 0

    async def test_the_next_task_continues_the_conversations_session(self) -> None:
        shell = _Shell(events=_lines(_codex_stream(end=None)))
        await shell.make_dir(WORK_DIR)
        await shell.write_bytes(session_path("codex", THREAD), b"th-1\n")
        raw = await _call(shell, "Apply it", harness="codex")
        assert CodingReport.model_validate_json(raw).files_changed == ["app.py"]
        assert shlex.split(shlex.split(shell.started[0])[4])[:4] == [
            "codex",
            "exec",
            "resume",
            "th-1",
        ]

    async def test_another_conversation_in_the_same_sandbox_starts_its_own(self) -> None:
        """A project's sandbox is shared by several chats, and several people: one
        must never continue another's session, hidden context and all."""
        shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        await shell.make_dir(WORK_DIR)
        await shell.write_bytes(session_path("claude_code", uuid4()), b"theirs")
        await _call(shell)
        assert "--resume" not in shell.started[0]

    async def test_a_run_in_no_conversation_neither_continues_nor_keeps_one(self) -> None:
        shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        await shell.make_dir(WORK_DIR)
        await _call(shell, conversation_id=None)
        assert "--resume" not in shell.started[0]
        assert not any(entry.name.endswith(".session") for entry in await shell.list_dir(WORK_DIR))

    async def test_a_fresh_session_ignores_the_one_kept(self) -> None:
        shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        await shell.make_dir(WORK_DIR)
        await shell.write_bytes(session_path("claude_code", THREAD), b"old")
        await _call(shell, fresh_session=True)
        assert "--resume" not in shell.started[0]

    async def test_a_session_the_sandbox_lost_starts_over_once(self) -> None:
        shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)), fails_resumed=True)
        await shell.make_dir(WORK_DIR)
        await shell.write_bytes(session_path("claude_code", THREAD), b"gone")
        report = CodingReport.model_validate_json(await _call(shell))
        assert report.outcome == "completed"
        assert ["--resume" in line for line in shell.started] == [True, False]

    async def test_each_step_streams_to_its_own_panel_as_it_lands(self) -> None:
        frames: list[SubagentEvent] = []
        shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        await _call(shell, "Fix it", frames=frames)

        kinds = [frame.kind for frame in frames]
        assert kinds[0] == "subagent_start" and kinds[-1] == "subagent_complete"
        start = frames[0]
        assert start.kind == "subagent_start"
        assert (start.task_id, start.subagent, start.harness, start.prompt) == (
            "call-1",
            "Claude Code",
            "claude_code",
            "Fix it",
        )
        calls = [(f.tool_name, f.title) for f in frames if f.kind == "subagent_tool_call"]
        assert calls == [
            ("read", "app.py"),
            ("command", "pytest -q"),
            ("edit", "app.py"),
            ("other", "dig"),
        ]
        results = {f.tool_call_id: f.ok for f in frames if f.kind == "subagent_tool_result"}
        # t3 and t5 were never answered: they close with the panel, as failed.
        assert results == {"t1": True, "t2": False, "t3": False, "t5": False}
        assert any(f.kind == "subagent_text_delta" and f.delta == "Looking.\n\n" for f in frames)
        assert frames[-1].kind == "subagent_complete" and frames[-1].status == "completed"

    async def test_a_long_stream_is_read_in_chunks_and_a_split_line_is_joined(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_task, "CHUNK_BYTES", 7)
        frames: list[SubagentEvent] = []
        # No newline after the last event: it is read once the harness has exited.
        shell = _Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        report = CodingReport.model_validate_json(await _call(shell, frames=frames))
        assert report.outcome == "completed" and len(report.steps) == 4

    async def test_a_task_past_its_time_is_stopped_and_says_so(self) -> None:
        frames: list[SubagentEvent] = []
        shell = _Shell(events=_lines(_claude_stream()), hangs=True)
        report = CodingReport.model_validate_json(
            await _call(shell, frames=frames, timeout_seconds=0)
        )
        assert report.outcome == "timed_out"
        assert "stopped after 0 minutes" in report.answer
        assert len(report.steps) == 4
        assert shell.stopped == 1
        assert frames[-1].kind == "subagent_complete" and frames[-1].status == "failed"

    @pytest.mark.security
    async def test_an_exit_code_written_early_does_not_end_a_running_task(self) -> None:
        """The exit-code file is in the workspace the harness edits. A task that
        writes it while still running is still watched, and still stopped."""

        class _Forging(_Shell):
            async def _start(self, command: str) -> CommandResult:
                started = await super()._start(command)
                status = next(
                    path for path in _TASK_FILE.findall(command) if path.endswith(".exit")
                )
                await self.write_bytes(status, b"0\n")
                return started

        shell = _Forging(events=_lines(_claude_stream()), hangs=True)
        report = CodingReport.model_validate_json(await _call(shell, timeout_seconds=0))
        assert report.outcome == "timed_out"
        assert shell.stopped == 1

    async def test_a_task_gone_without_an_exit_code_is_over(self) -> None:
        class _Killed(_Shell):
            async def _start(self, command: str) -> CommandResult:
                started = await super()._start(command)
                status = next(
                    path for path in _TASK_FILE.findall(command) if path.endswith(".exit")
                )
                await self.remove(status)
                return started

        shell = _Killed(events=_lines(_claude_stream()))
        report = CodingReport.model_validate_json(await _call(shell))
        assert report.outcome == "failed"
        assert shell.stopped == 0

    async def test_a_start_that_names_no_process_is_not_watched(self) -> None:
        class _Silent(_Shell):
            async def _start(self, command: str) -> CommandResult:
                await super()._start(command)
                return CommandResult(exit_code=0, stdout="1\n", stderr="")

        shell = _Silent(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        report = CodingReport.model_validate_json(await _call(shell))
        assert report.answer == "The sandbox did not say which process the task runs as."
        assert not any("tail -c +" in command for command, _, _ in shell.commands)

    async def test_a_cancelled_run_stops_the_harness_and_closes_its_panel(self) -> None:
        frames: list[SubagentEvent] = []

        class _Cancelled(_Shell):
            async def _poll(self, command: str) -> CommandResult:
                raise anyio.get_cancelled_exc_class()

        shell = _Cancelled(hangs=True)
        with pytest.raises(anyio.get_cancelled_exc_class()):
            await _call(shell, frames=frames)
        assert shell.stopped == 1
        assert frames[-1].kind == "subagent_complete" and frames[-1].status == "cancelled"

    async def test_a_harness_that_printed_nothing_but_errors_says_what(self) -> None:
        shell = _Shell(stderr="Invalid API key\n", exit_code=1)
        report = CodingReport.model_validate_json(await _call(shell))
        assert (report.outcome, report.answer) == ("failed", "Invalid API key")

    async def test_files_already_gone_are_no_failure(self) -> None:
        class _Tidied(_Shell):
            async def run(self, command: Any, **kwargs: Any) -> CommandResult:
                if command.startswith("rm -f "):
                    raise WorkspaceUnavailableError("gone")
                return await super().run(command, **kwargs)

        shell = _Tidied(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        report = CodingReport.model_validate_json(await _call(shell))
        assert report.outcome == "completed"

    async def test_a_runtime_without_the_harness_is_named(self) -> None:
        answer = await _call(_Shell(exit_code=127), harness="codex")
        assert "Codex is not installed" in answer

    async def test_a_sandbox_that_cannot_run_it_is_an_answer(self) -> None:
        frames: list[SubagentEvent] = []
        shell = _Shell(raises=WorkspaceUnavailableError("gone"))
        answer = await _call(shell, frames=frames)
        assert answer == "Claude Code could not run in this sandbox (WorkspaceUnavailableError)."
        assert frames[-1].kind == "subagent_complete" and frames[-1].status == "failed"

    async def test_a_sandbox_the_service_will_not_open_is_an_answer(self) -> None:
        """A runtime still building answers 409, which the sandboxd client raises unmapped."""
        refused = httpx.HTTPStatusError(
            "409 Conflict",
            request=httpx.Request("POST", "http://sandboxd/sessions"),
            response=httpx.Response(409),
        )
        answer = await _call(_Shell(raises=refused))
        assert answer == "Claude Code could not run in this sandbox (HTTPStatusError)."

    async def test_a_poll_that_comes_back_garbled_reads_as_nothing_yet(self) -> None:
        class _Garbled(_Shell):
            polls = 0

            async def _poll(self, command: str) -> CommandResult:
                self.polls += 1
                if self.polls == 1:
                    return CommandResult(exit_code=0, stdout="not base64!\nnot a code", stderr="")
                return await super()._poll(command)

        shell = _Garbled(events=_lines(_claude_stream(result=_CLAUDE_DONE)))
        assert CodingReport.model_validate_json(await _call(shell)).outcome == "completed"

    async def test_a_workspace_whose_files_cannot_be_read_still_reports(self) -> None:
        shell = _Shell(exit_code=0)
        ledger = SpendLedger()
        with metered_by(ledger):
            raw = await _tools()["run_coding_agent"].function(
                _ctx(ShellFailing(shell)), task="Look"
            )
        # The session file cannot be read or written; the task still runs and reports.
        assert CodingReport.model_validate_json(raw).outcome == "failed"
        # It ran, so it may have spent: one unpriced call makes the run's cost
        # a floor rather than a total that reads as complete.
        assert [(entry.model_name, entry.priced) for entry in ledger.entries] == [
            (UNREPORTED, False)
        ]

    async def test_an_agent_with_no_sandbox_is_told_to_say_so(self) -> None:
        answer = await _call(None)
        assert "needs a sandbox with a shell" in answer

    async def test_an_empty_task_or_a_missing_key_asks_again(self) -> None:
        with pytest.raises(ModelRetry, match="Describe the task"):
            await _call(_Shell(), task="  ")
        with pytest.raises(ModelRetry, match="no API key"):
            await _call(_Shell(), api_key=None)


class TestWatchingItWork:
    def test_claude_code_opens_a_step_per_tool_and_closes_it_on_the_result(self) -> None:
        assistant, user = _claude_stream()[1:3]
        assert live_items("claude_code", assistant)[:2] == [
            Said("Looking."),
            StepStarted("t1", CodingStep(kind="read", title="app.py")),
        ]
        assert live_items("claude_code", user) == [
            StepEnded("t2", failed=True),
            StepEnded("t1", failed=False),
            StepEnded("unknown", failed=True),
        ]

    def test_codex_opens_a_command_as_it_starts_and_says_what_it_wrote(self) -> None:
        started = {
            "type": "item.started",
            "item": {
                "id": "i1",
                "type": "command_execution",
                "command": "/bin/bash -lc 'pytest -q'",
            },
        }
        assert live_items("codex", started) == [
            StepStarted("i1", CodingStep(kind="command", title="pytest -q"))
        ]
        said = {
            "type": "item.completed",
            "item": {"id": "i2", "type": "agent_message", "text": "Done."},
        }
        assert live_items("codex", said) == [Said("Done.")]
        edit = {
            "type": "item.completed",
            "item": {"id": "i3", "type": "file_change", "changes": [{"path": "a.py"}]},
        }
        assert live_items("codex", edit) == [
            StepStarted("i3", CodingStep(kind="edit", title="a.py")),
            StepEnded("i3", failed=False),
        ]

    def test_what_says_nothing_shows_nothing(self) -> None:
        assert live_items("codex", {"type": "turn.completed"}) == []
        assert (
            live_items(
                "codex", {"type": "item.started", "item": {"id": "i", "type": "agent_message"}}
            )
            == []
        )
        assert (
            live_items(
                "codex", {"type": "item.completed", "item": {"id": "i", "type": "reasoning"}}
            )
            == []
        )
        assert (
            live_items("codex", {"type": "item.completed", "item": {"type": "agent_message"}}) == []
        )

    def test_a_command_codex_wraps_reads_as_the_command(self) -> None:
        report, _ = codex_report(_codex_stream(end=None), access="edit", model=None)
        assert report.steps[0].title == "ls"
        unbalanced = {
            "type": "item.started",
            "item": {"id": "i", "type": "command_execution", "command": "echo 'open"},
        }
        assert live_items("codex", unbalanced) == [
            StepStarted("i", CodingStep(kind="command", title="echo 'open"))
        ]

    def test_claude_codes_thinking_is_not_a_step(self) -> None:
        thinking = {"type": "assistant", "message": {"content": [{"type": "thinking"}]}}
        assert live_items("claude_code", thinking) == []

    async def test_a_codex_command_opened_as_it_started_is_not_opened_twice(self) -> None:
        frames: list[SubagentEvent] = []
        item = {"id": "c1", "type": "command_execution", "command": "pytest", "exit_code": 0}
        events = [
            {"type": "thread.started", "thread_id": "th-9"},
            {"type": "item.started", "item": item},
            {"type": "item.completed", "item": item},
            {"type": "turn.completed", "usage": {}},
        ]
        await _call(_Shell(events=_lines(events)), harness="codex", frames=frames)
        calls = [frame for frame in frames if frame.kind == "subagent_tool_call"]
        results = [frame for frame in frames if frame.kind == "subagent_tool_result"]
        assert [(c.tool_call_id, c.title) for c in calls] == [("c1", "pytest")]
        assert [(r.tool_call_id, r.ok) for r in results] == [("c1", True)]

    async def test_a_task_handed_on_by_a_delegate_streams_inside_its_panel(self) -> None:
        frames: list[SubagentEvent] = []
        # Only the four fields `acting_delegate` reads; a whole `Delegation` is a
        # running delegation's bookkeeping, none of which this is about.
        enclosing = SimpleNamespace(name="tech-lead", public_id="task-9", agent_id=None, depth=0)
        token = _journal._CURRENT.set(enclosing)  # ty: ignore[invalid-argument-type]
        try:
            await _call(_Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE))), frames=frames)
        finally:
            _journal._CURRENT.reset(token)
        start = frames[0]
        assert start.kind == "subagent_start"
        assert (start.depth, start.parent_task_id) == (1, "task-9")
        assert {frame.depth for frame in frames} == {1}

    async def test_a_surface_that_cannot_show_it_hears_nothing(self) -> None:
        ctx = _ctx(_Shell(events=_lines(_claude_stream(result=_CLAUDE_DONE))))
        ctx.deps.subagent_events = None
        raw = await _tools()["run_coding_agent"].function(ctx, task="Fix it")
        assert CodingReport.model_validate_json(raw).outcome == "completed"


class TestConfiguringIt:
    def test_an_endpoint_left_from_claude_code_goes_with_codex(self) -> None:
        """The field is hidden once Codex is chosen, so a value left in it is dropped."""
        config = CodingAgentConfig(harness="codex", base_url="https://openrouter.ai/api")
        assert config.base_url is None
        schema = CodingAgentConfig.model_json_schema()["properties"]["base_url"]
        assert schema["x-visible-when"] == {"field": "harness", "equals": ["claude_code"]}

    def test_codex_is_refused_read_only_and_the_builder_never_offers_it(self) -> None:
        with pytest.raises(ValidationError, match="Codex can only run with access"):
            CodingAgentConfig(harness="codex", access="read_only")
        when = CodingAgentConfig.model_json_schema()["properties"]["access"]["x-enum-when"]
        assert when["choices"] == {"claude_code": ["edit", "read_only"], "codex": ["edit"]}

    def test_its_one_tool_is_the_capability_and_has_no_settings_of_its_own(self) -> None:
        definition = get("coding_agent")
        assert [tool.id for tool in definition.tools] == ["run_coding_agent"]
        assert definition.tool_settings is False

    def test_the_instructions_say_which_harness_and_what_it_may_do(self) -> None:
        editing = CodingAgent(harness="codex").get_instructions()
        reading = CodingAgent(harness="claude_code", access="read_only").get_instructions()
        assert "Codex" in editing and "edits files" in editing
        assert "Claude Code" in reading and "changing nothing" in reading

    def test_the_builder_reads_the_key_the_endpoint_and_the_time_limit(self) -> None:
        definition = get("coding_agent")
        binding = CapabilityBinding(
            capability_id="coding_agent",
            config={
                "base_url": "https://openrouter.ai/api/",
                "timeout_minutes": 5,
                "access": "read_only",
            },
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
        assert (built.base_url, built.timeout_seconds, built.api_key, built.access) == (
            "https://openrouter.ai/api",
            300,
            "sk-or-gateway",
            "read_only",
        )
        toolset = built.get_toolset()
        assert isinstance(toolset, FunctionToolset)
        assert set(toolset.tools) == {"run_coding_agent"}
        assert built.get_toolset() is built.get_toolset()

    def test_a_binding_with_no_secret_builds_without_a_key(self) -> None:
        definition = get("coding_agent")
        binding = CapabilityBinding(capability_id="coding_agent")
        built = definition.builder(
            CapabilityBuildContext(binding=binding, config=None, resources={}, secret=None)
        )
        assert isinstance(built, CodingAgent) and built.api_key is None

    @pytest.mark.parametrize("shared", [True, False, None])
    def test_the_builder_says_whether_others_work_in_the_sandbox(self, shared: bool | None) -> None:
        definition = get("coding_agent")
        binding = CapabilityBinding(capability_id="coding_agent")
        built = definition.builder(
            CapabilityBuildContext(
                binding=binding,
                config=None,
                resources={} if shared is None else {"workspace_shared": shared},
                secret=None,
            )
        )
        assert isinstance(built, CodingAgent) and built.shared_sandbox is (shared is True)


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
            "edit",
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
                "claude_code", "edit", "x", api_key=None, model=None, session_id=None, base_url=None
            )

    def test_codex_on_a_sign_in_carries_no_key(self) -> None:
        command = invocation(
            "codex", "edit", "x", api_key=None, model=None, session_id=None, base_url=None
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

    def __init__(self, *, gone: bool = False, visible: bool = True) -> None:
        self.gone = gone
        self.visible = visible
        self.asked_for: list[UUID] = []
        self.saved: list[OpenAICodexCredentials] = []

    async def visible_to(self, user_id: UUID) -> bool:
        self.asked_for.append(user_id)
        return self.visible

    async def load(self) -> OpenAICodexCredentials:
        if self.gone:
            raise BadRequestError(
                message="The ChatGPT sign-in this model runs on is no longer in the vault"
            )
        return SIGNED_IN

    async def swap(self, previous: OpenAICodexCredentials, rotated: OpenAICodexCredentials) -> bool:
        assert previous == SIGNED_IN
        self.saved.append(rotated)
        return True


class TestCodexOnASignIn:
    async def _run(self, shell: _Shell, store: _Store, **overrides: Any) -> str:
        options: dict[str, Any] = {"api_key": None, "sign_in": lambda _org: store} | overrides
        return await _tools("codex", **options)["run_coding_agent"].function(
            _ctx(shell), task="Look"
        )

    async def test_the_sign_in_is_written_for_the_task_and_what_codex_rotated_is_kept(self) -> None:
        rotated = json.loads(codex_auth_file(SIGNED_IN))
        rotated["tokens"]["refresh_token"] = "rt-2"
        shell = _Shell(events=_lines(_codex_stream(end=None)), auth_after=json.dumps(rotated))
        store = _Store()

        report = CodingReport.model_validate_json(await self._run(shell, store))

        assert report.outcome == "completed"
        written, started, read = (
            shell.commands[0],
            next(command for command in shell.commands if command[0].startswith("setsid")),
            shell.commands[-1],
        )
        assert written[0] == WRITE_AUTH and written[1] is not None
        assert json.loads(written[1][AUTH_ENV])["tokens"]["refresh_token"] == "rt-1"
        assert "CODEX_API_KEY" not in (started[1] or {})
        assert read[0] == READ_AUTH
        # One Codex home per task: the sign-in, the run and the read-back all in
        # it, never the sandbox user's shared ~/.codex - and the sessions it
        # resumes in one the conversation keeps.
        home = written[1][HOME_ENV]
        assert (
            home.startswith(f"{CODEX_HOMES}/{THREAD}/")
            and home != f"{CODEX_HOMES}/{THREAD}/sessions"
        )
        assert written[1][SESSIONS_ENV] == f"{CODEX_HOMES}/{THREAD}/sessions"
        assert read[1] == {HOME_ENV: home}
        assert started[1] is not None and started[1][HOME_ENV] == home
        assert store.asked_for == [RUNNER]
        assert [saved.refresh_token for saved in store.saved] == ["rt-2"]

    async def test_a_sign_in_the_runner_may_not_see_is_never_handed_over(self) -> None:
        """Whatever Codex runs can read the tokens it is given, so running the
        agent must not reach a sign-in its runner could not have chosen."""
        shell = _Shell(events=_lines(_codex_stream(end=None)))
        answer = await self._run(shell, _Store(visible=False))
        assert "only for somebody who may see that sign-in" in answer
        assert shell.commands == []

    @pytest.mark.security
    async def test_a_run_for_nobody_actually_asking_gets_no_sign_in(self) -> None:
        """A visitor on a public page, or whoever holds an API key, runs billed to
        the publisher or the key's issuer - whose own sign-in that is. The audience
        names nobody for them, and nobody's sign-in is written."""
        ctx = _ctx(_Shell(), audience=RunAudience())
        store = _Store()
        answer = await _tools("codex", api_key=None, sign_in=lambda _org: store)[
            "run_coding_agent"
        ].function(ctx, task="Look")
        assert "only for somebody who may see that sign-in" in answer
        assert store.asked_for == []

    async def test_two_tasks_in_one_conversation_never_share_a_sign_in(self) -> None:
        """Two turns of one shared project chat can run at once, on different
        sign-ins; one `auth.json` between them let either save the other's
        rotated tokens into its own secret."""
        shell = _Shell(
            events=_lines(_codex_stream(end=None)), auth_after=codex_auth_file(SIGNED_IN)
        )
        await self._run(shell, _Store())
        await self._run(shell, _Store())
        homes = [env[HOME_ENV] for command, env, _ in shell.commands if command == WRITE_AUTH]
        sessions = {
            env[SESSIONS_ENV] for command, env, _ in shell.commands if command == WRITE_AUTH
        }
        assert len(set(homes)) == 2
        assert sessions == {f"{CODEX_HOMES}/{THREAD}/sessions"}

    async def test_a_run_in_no_conversation_gets_a_codex_home_of_its_own(self) -> None:
        shell = _Shell(
            events=_lines(_codex_stream(end=None)), auth_after=codex_auth_file(SIGNED_IN)
        )
        ctx = _ctx(shell)
        ctx.deps.conversation_id = None
        await _tools("codex", api_key=None, sign_in=lambda _org: _Store())[
            "run_coding_agent"
        ].function(ctx, task="Look")
        home = shell.commands[0][1][HOME_ENV]
        assert home.startswith(f"{CODEX_HOMES}/") and str(THREAD) not in home
        # Nothing will resume its sessions, so they go with the home.
        read = shell.commands[-1]
        assert read[0] == READ_AUTH
        assert read[1] == {HOME_ENV: home, DISCARD_ENV: home.rsplit("/", 1)[0]}

    async def test_a_sign_in_that_was_not_rotated_is_left_alone(self) -> None:
        store = _Store()
        shell = _Shell(
            events=_lines(_codex_stream(end=None)), auth_after=codex_auth_file(SIGNED_IN)
        )
        await self._run(shell, store)
        assert store.saved == []

    @pytest.mark.security
    async def test_a_shared_sandbox_never_gets_a_persons_sign_in(self) -> None:
        """Another person's task runs as the same user in a project's container and
        could read the tokens wherever they were written."""
        shell = _Shell()
        answer = await self._run(shell, _Store(), shared_sandbox=True)
        assert "only in a sandbox nobody else's tasks share" in answer
        assert shell.commands == []

    @pytest.mark.security
    async def test_a_group_chat_never_gets_a_persons_sign_in(self) -> None:
        """Everybody in a Slack or Telegram room runs in its conversation's
        container, whatever scope the sandbox has - shared all the same."""
        store = _Store()
        ctx = _ctx(_Shell(), audience=RunAudience(user_id=RUNNER, room_key="room:slack:C1"))
        answer = await _tools("codex", api_key=None, sign_in=lambda _org: store)[
            "run_coding_agent"
        ].function(ctx, task="Look")
        assert "only in a sandbox nobody else's tasks share" in answer
        assert store.asked_for == []

    async def test_a_sign_in_removed_from_the_vault_is_an_answer(self) -> None:
        answer = await self._run(_Shell(), _Store(gone=True))
        assert "no longer in the vault" in answer

    async def test_a_sandbox_that_cannot_take_the_sign_in_is_an_answer(self) -> None:
        shell = _Shell(auth_raises=WorkspaceUnavailableError("gone"))
        answer = await self._run(shell, _Store())
        assert answer == "Codex could not run in this sandbox (WorkspaceUnavailableError)."
        # The write may have landed before the failure came back, so its home is
        # still taken back out.
        assert [command for command, _, _ in shell.commands] == [WRITE_AUTH, READ_AUTH]

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
            "run_coding_agent"
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
        answer = await _tools(harness, **overrides)["run_coding_agent"].function(
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
