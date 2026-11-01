"""The monitor: watch a command's output in the run's workspace and hear about it (#2576).

No shell is run. A scripted workspace answers the three commands the manager sends
(start, read, stop) and records them, so the detached start line, the incremental
read, the filter, the batching, the exit and the cleanup all run as they would.
"""

import base64
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.workspaces import CommandResult, WorkspaceError

from app.agents.capabilities.monitor import MONITOR_CAPABILITY_ID, Monitor
from app.agents.capabilities.monitor import _manager as manager_module
from app.agents.capabilities.monitor._capability import describe
from app.agents.capabilities.monitor._manager import (
    BATCH_LINES,
    MAX_WATCHES,
    MonitorManager,
    Update,
    compile_match,
)
from app.agents.capabilities.monitor._toolset import NEEDS_SHELL, build_toolset

pytestmark = pytest.mark.anyio


class Shell:
    """A workspace whose shell answers by what the command is."""

    attached = True

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.started = "4242\n"
        self.start_code = 0
        self.log = b""
        self.state = "running"
        self.fail: type[Exception] | None = None
        self.garbage: str | None = None

    async def run(self, command: str, *, shell: bool, timeout: float) -> CommandResult:
        self.commands.append(command)
        if self.fail is not None:
            raise self.fail("shell failed")
        if "nohup sh -c" in command:
            return CommandResult(exit_code=self.start_code, stdout=self.started, stderr="")
        if "tail -c +" in command:
            offset = int(command.split("tail -c +", 1)[1].split(" ", 1)[0]) - 1
            assert command.index("kill -0") < command.index("tail -c +")
            chunk = base64.b64encode(self.log[offset:]).decode()
            body = self.garbage if self.garbage is not None else chunk
            return CommandResult(exit_code=0, stdout=f"{body}\n\n{self.state}\n", stderr="")
        return CommandResult(exit_code=0, stdout="", stderr="")


def ctx(shell: Shell | None) -> Any:
    return SimpleNamespace(
        workspace=shell if shell is not None else SimpleNamespace(attached=False)
    )


async def started(shell: Shell, manager: MonitorManager, **kwargs: Any):
    return await manager.start(
        shell, "npm run test:watch", kwargs.get("label"), kwargs.get("match")
    )


async def test_a_watch_starts_detached_with_its_output_in_a_file_of_its_own() -> None:
    shell, manager = Shell(), MonitorManager()
    watch = await started(shell, manager, label="tests", match="fail")
    assert watch.pid == "4242" and watch.label == "tests"
    line = shell.commands[0]
    assert "nohup sh -c" in line and "/dev/null" in line and "echo $!" in line
    assert f"/tmp/agenticos-monitor-{manager._run}/{watch.id}.log" in line  # noqa: S108
    assert "npm run test:watch" in line
    assert manager.running == [watch] and manager.watches == [watch]


async def test_a_command_that_is_empty_too_long_or_one_too_many_is_refused() -> None:
    shell, manager = Shell(), MonitorManager()
    with pytest.raises(ValueError, match="characters"):
        await manager.start(shell, "  ", None, None)
    with pytest.raises(ValueError, match="characters"):
        await manager.start(shell, "x" * (manager_module.MAX_COMMAND_CHARS + 1), None, None)
    for _ in range(MAX_WATCHES):
        await started(shell, manager)
    with pytest.raises(ValueError, match="At most"):
        await started(shell, manager)


@pytest.mark.parametrize(("stdout", "code"), [("", 0), ("not a pid\n", 0), ("4242\n", 1)])
async def test_a_start_the_shell_did_not_confirm_is_an_error(stdout: str, code: int) -> None:
    shell = Shell()
    shell.started, shell.start_code = stdout, code
    with pytest.raises(WorkspaceError, match="could not be started"):
        await started(shell, MonitorManager())


async def test_only_matching_whole_lines_are_reported_and_a_partial_line_waits() -> None:
    shell, manager = Shell(), MonitorManager()
    watch = await started(shell, manager, match="error|FAIL")
    shell.log = b"ok 1\nerror: boom\n\nFAIL x\nerr"
    [update] = await manager.collect(shell)
    assert update.lines == ["error: boom", "FAIL x"] and not update.finished
    assert watch.offset == len(shell.log) and watch.pending == b"err"
    assert await manager.collect(shell) == []
    shell.log += b"or: late\n"
    [again] = await manager.collect(shell)
    assert again.lines == ["error: late"]
    assert list(watch.recent) == ["error: boom", "FAIL x", "error: late"]
    assert watch.reported == 3


async def test_an_exit_reports_the_last_partial_line_and_the_code_and_ends_the_watch() -> None:
    shell, manager = Shell(), MonitorManager()
    watch = await started(shell, manager)
    shell.log, shell.state = b"done\nlast words", "2"
    [update] = await manager.collect(shell)
    assert update.lines == ["done", "last words"] and update.finished and update.exit_code == 2
    assert not watch.running and manager.running == []
    assert await manager.collect(shell) == []


async def test_an_exit_with_nothing_new_is_still_reported_and_a_strange_code_is_unknown() -> None:
    shell, manager = Shell(), MonitorManager()
    watch = await started(shell, manager)
    shell.state = "gone"
    [update] = await manager.collect(shell)
    assert update.lines == [] and update.finished and watch.exit_code is None


async def test_a_long_burst_is_batched_and_the_rest_counted() -> None:
    shell, manager = Shell(), MonitorManager()
    await started(shell, manager)
    shell.log = b"".join(f"line {i}\n".encode() for i in range(BATCH_LINES + 7))
    [update] = await manager.collect(shell)
    assert len(update.lines) == BATCH_LINES and update.skipped == 7


async def test_a_read_that_is_not_base64_reads_nothing_and_a_long_line_is_cut() -> None:
    shell, manager = Shell(), MonitorManager()
    watch = await started(shell, manager)
    shell.garbage = "***not base64***"
    assert await manager.collect(shell) == []
    assert watch.offset == 0
    shell.garbage = None
    shell.log = b"x" * 2000 + b"\n"
    [update] = await manager.collect(shell)
    assert len(update.lines[0]) == manager_module.MAX_LINE_CHARS


def test_a_match_that_is_not_a_regex_is_taken_as_text() -> None:
    assert compile_match(None) is None and compile_match("") is None
    assert compile_match("a|b").search("b")
    literal = compile_match("error(")
    assert literal is not None and literal.search("an error( here")


async def test_a_workspace_that_fails_a_read_or_a_stop_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    shell, manager = Shell(), MonitorManager()
    await started(shell, manager)
    shell.fail = WorkspaceError
    assert await manager.collect(shell) == []
    assert "could not be read" in caplog.text
    [watch] = manager.running
    assert await manager.stop(shell, watch.id) is watch
    assert "could not be stopped" in caplog.text and not watch.running


async def test_stopping_kills_the_watch_and_what_it_started_and_unknown_ids_are_nothing() -> None:
    shell, manager = Shell(), MonitorManager()
    first, second = await started(shell, manager), await started(shell, manager)
    assert await manager.stop(shell, "nope") is None
    assert await manager.stop(shell, first.id) is first
    assert "killtree 4242" in shell.commands[-1] and "pgrep -P" in shell.commands[-1]
    sent = len(shell.commands)
    assert await manager.stop(shell, first.id) is first
    assert len(shell.commands) == sent
    await manager.stop_all(shell)
    assert not second.running and manager.running == []


def test_the_note_the_model_reads_names_the_watch_the_lines_and_the_exit() -> None:
    lines = Update("tests", "npm test", ["a", "b"], 3, False, None)
    assert describe(lines) == (
        "[monitor:tests] 2 new line(s) from `npm test`:\na\nb\n(+3 more matching lines)"
    )
    assert describe(Update("t", "c", ["x"], 0, True, 0)).endswith("`c` exited with code 0.")
    assert (
        describe(Update("t", "c", [], 0, True, None))
        == "[monitor:t] `c` exited with an unknown code."
    )
    assert describe(Update("t", "c", [], 0, False, None)) == ""


async def test_the_tools_start_list_and_stop_through_the_runs_workspace() -> None:
    shell, manager = Shell(), MonitorManager()
    tools = build_toolset(manager).tools
    run = ctx(shell)
    started_json = json.loads(
        await tools["start_monitor"].function(run, "tail -f app.log", "log", "ERROR")
    )
    assert started_json["running"] and started_json["label"] == "log"
    shell.log = b"ERROR one\nfine\n"
    await manager.collect(shell)
    listed = json.loads(await tools["list_monitors"].function(run))
    assert listed[0]["recent"] == ["ERROR one"] and listed[0]["matched_lines"] == 1
    assert await tools["stop_monitor"].function(run, started_json["monitor_id"]) == "Stopped log."
    assert await tools["stop_monitor"].function(run, "x") == "No watch has the id x."


async def test_the_tools_say_so_without_a_shell_and_report_what_they_cannot_start() -> None:
    tools = build_toolset(MonitorManager()).tools
    nothing = ctx(None)
    assert await tools["start_monitor"].function(nothing, "ls") == NEEDS_SHELL
    assert await tools["stop_monitor"].function(nothing, "id") == NEEDS_SHELL
    shell = Shell()
    assert "characters" in await tools["start_monitor"].function(ctx(shell), "")
    shell.started = ""
    assert "could not start" in await tools["start_monitor"].function(ctx(shell), "ls")


def request(*parts: Any) -> ModelRequestContext:
    return ModelRequestContext(
        model=TestModel(),
        messages=list(parts),
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )


async def test_new_output_rides_the_tail_of_the_next_request_without_touching_history() -> None:
    shell = Shell()
    monitor: Monitor[Any] = Monitor()
    await started(shell, monitor.manager, match="boom")
    shell.log = b"boom 1\n"
    history = request(ModelRequest(parts=[UserPromptPart(content="go")]))
    changed = await monitor.before_model_request(ctx(shell), history)
    tail = changed.messages[-1]
    assert isinstance(tail, ModelRequest) and len(tail.parts) == 2
    assert "boom 1" in str(tail.parts[-1].content)
    assert len(history.messages[-1].parts) == 1
    again = await monitor.before_model_request(ctx(shell), history)
    assert again is history


async def test_no_note_is_made_when_nothing_runs_there_is_no_shell_or_the_tail_is_a_response() -> (
    None
):
    monitor: Monitor[Any] = Monitor()
    plain = request(ModelRequest(parts=[UserPromptPart(content="go")]))
    assert await monitor.before_model_request(ctx(Shell()), plain) is plain
    shell = Shell()
    await started(shell, monitor.manager)
    assert await monitor.before_model_request(ctx(None), plain) is plain
    resumed = request(ModelResponse(parts=[TextPart(content="half")]))
    assert await monitor.before_model_request(ctx(shell), resumed) is resumed
    empty = request()
    assert await monitor.before_model_request(ctx(shell), empty) is empty


async def test_the_run_ends_by_stopping_every_watch_even_when_it_failed() -> None:
    shell = Shell()
    monitor: Monitor[Any] = Monitor()
    await started(shell, monitor.manager)

    async def fails() -> Any:
        raise RuntimeError("the run broke")

    with pytest.raises(RuntimeError):
        await monitor.wrap_run(ctx(shell), handler=fails)
    assert monitor.manager.running == []
    assert any("killtree 4242" in command for command in shell.commands)

    async def fine() -> str:
        return "answer"

    sent = len(shell.commands)
    assert await monitor.wrap_run(ctx(shell), handler=fine) == "answer"
    assert await monitor.wrap_run(ctx(None), handler=fine) == "answer"
    assert len(shell.commands) == sent


def test_the_capability_tells_the_agent_what_it_can_do_and_builds_its_tools_once() -> None:
    monitor: Monitor[Any] = Monitor()
    assert "start_monitor" in monitor.get_instructions()
    assert monitor.get_toolset() is monitor.get_toolset()
    assert set(monitor.get_toolset().tools) == {"start_monitor", "list_monitors", "stop_monitor"}  # type: ignore[attr-defined]
    assert MONITOR_CAPABILITY_ID == "monitor"


def test_listing_the_watches_never_waits_for_a_person_but_starting_and_stopping_do() -> None:
    from app.agents.capabilities import get

    tools = {tool.id: tool for tool in get("monitor").tools}  # type: ignore[union-attr]
    assert tools["list_monitors"].side_effecting is False
    assert tools["start_monitor"].side_effecting is None
    assert tools["stop_monitor"].side_effecting is None
    assert get("monitor").side_effecting  # type: ignore[union-attr]
