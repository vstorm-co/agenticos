"""The coding agent on the person's own computer, spoken to over ACP (#2576).

No adapter is started. A scripted agent plays what `claude-agent-acp` was seen to
write on `initialize` and what the protocol says a prompt produces: updates, a
permission request, and a final stop reason. It sits behind the `Pipe` the client
speaks through - and, for the end-to-end cases, behind the device hub's `call`,
so the polling, the cursor and the failures the hub raises all run.
"""

import json
from typing import Any
from uuid import uuid4

import anyio
import pytest
from pydantic_ai._run_context import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import Workspace, WrapperWorkspace

from app.agents.audience import RunAudience
from app.agents.capabilities.coding_agent import CodingAgent, CodingAgentConfig
from app.agents.capabilities.coding_agent import _acp as acp
from app.agents.capabilities.coding_agent._harness import (
    CodingStep,
    Said,
    StepEnded,
    StepStarted,
)
from app.agents.capabilities.coding_agent._toolset import build_coding_toolset
from app.agents.deps import AgentDeps
from app.agents.subagent_events import SubagentEvent
from app.schemas.local_target import LocalTarget
from app.services.device_hub import workspace as workspace_module
from app.services.device_hub.exceptions import DeviceCallFailed, DeviceUnavailable

pytestmark = pytest.mark.anyio

ALLOW = {"optionId": "ok", "name": "Allow", "kind": "allow_once"}
REJECT = {"optionId": "no", "name": "Reject", "kind": "reject_once"}


class ScriptedAgent:
    """An ACP agent that edits a file after being allowed to, and says so."""

    def __init__(self, *, kind: str = "edit", stop: str = "end_turn", fail_on: str | None = None):
        self.kind = kind
        self.stop = stop
        self.fail_on = fail_on
        self.seen: list[dict[str, Any]] = []
        self.out: list[dict[str, Any]] = []
        self.replied: dict[str, Any] | None = None
        self._prompt: Any = None

    def on_message(self, message: dict[str, Any]) -> None:
        self.seen.append(message)
        method = message.get("method")
        if self.fail_on is not None and method == self.fail_on:
            self.out.append(
                {"jsonrpc": "2.0", "id": message["id"], "error": {"code": 1, "message": "nope"}}
            )
        elif method == "initialize":
            self._result(message, {"protocolVersion": 1, "agentCapabilities": {}})
        elif method == "session/new":
            self._result(message, {"sessionId": "s-1"})
        elif method == "session/prompt":
            self._prompt = message["id"]
            self.out += [
                self._update(
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Looking. "},
                    }
                ),
                self._update(
                    {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "t1",
                        "title": "Edit a.py",
                        "kind": self.kind,
                        "status": "pending",
                        "locations": [{"path": "/w/a.py"}],
                    }
                ),
                {
                    "jsonrpc": "2.0",
                    "id": 100,
                    "method": "session/request_permission",
                    "params": {
                        "sessionId": "s-1",
                        "toolCall": {"toolCallId": "t1", "title": "Edit a.py", "kind": self.kind},
                        "options": [ALLOW, REJECT],
                    },
                },
            ]
        elif "result" in message and message.get("id") == 100:
            self.replied = message["result"]
            chosen = message["result"]["outcome"].get("optionId")
            self.out += [
                self._update(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "t1",
                        "status": "completed" if chosen == "ok" else "failed",
                        "content": [{"type": "diff", "path": "/w/b.py", "newText": "x"}],
                    }
                ),
                self._update(
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Done."},
                    }
                ),
                {"jsonrpc": "2.0", "id": self._prompt, "result": {"stopReason": self.stop}},
            ]

    def _result(self, request: dict[str, Any], result: dict[str, Any]) -> None:
        self.out.append({"jsonrpc": "2.0", "id": request["id"], "result": result})

    @staticmethod
    def _update(update: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": "s-1", "update": update},
        }


class ScriptedPipe:
    def __init__(self, agent: ScriptedAgent) -> None:
        self.agent = agent
        self.closed = False

    async def send(self, message: dict[str, Any]) -> None:
        self.agent.on_message(message)

    async def receive(self) -> dict[str, Any]:
        while not self.agent.out:
            await anyio.sleep_forever()
        return self.agent.out.pop(0)

    async def close(self) -> None:
        self.closed = True


async def _run(agent: ScriptedAgent, *, access: Any = "edit", timeout: int = 60, **kwargs: Any):
    shown: list[Any] = []

    async def collect(items: list[Any]) -> None:
        shown.extend(items)

    pipe = ScriptedPipe(agent)
    report = await acp.run_task(
        pipe,
        harness="claude_code",
        access=access,
        root="/w",
        task="Fix the bug",
        timeout_seconds=timeout,
        shown=collect,
        **kwargs,
    )
    return report, shown, pipe


async def test_a_task_runs_as_one_session_and_reports_what_the_agent_did() -> None:
    agent = ScriptedAgent()
    report, shown, pipe = await _run(agent)
    assert [m.get("method") for m in agent.seen if "method" in m] == [
        "initialize",
        "session/new",
        "session/prompt",
    ]
    assert agent.seen[0]["params"]["clientCapabilities"] == {}
    assert agent.seen[1]["params"] == {"cwd": "/w", "mcpServers": []}
    assert agent.seen[2]["params"]["prompt"] == [{"type": "text", "text": "Fix the bug"}]
    assert agent.replied == {"outcome": {"outcome": "selected", "optionId": "ok"}}
    assert report.outcome == "completed"
    assert report.answer == "Done."
    assert report.session_id == "s-1"
    assert report.steps == [CodingStep(kind="edit", title="Edit a.py")]
    assert report.files_changed == ["/w/a.py", "/w/b.py"]
    assert report.refused == []
    assert shown == [
        Said("Looking. "),
        StepStarted("t1", CodingStep(kind="edit", title="Edit a.py")),
        StepEnded("t1", failed=False),
    ]
    assert pipe.closed


async def test_read_only_refuses_a_change_and_says_what_it_refused() -> None:
    agent = ScriptedAgent(kind="execute")
    report, _, _ = await _run(agent, access="read_only")
    assert agent.replied == {"outcome": {"outcome": "selected", "optionId": "no"}}
    assert report.refused == ["Edit a.py"]
    assert report.steps[0].failed
    assert agent.seen[2]["params"]["prompt"][0]["text"].startswith("You are running read-only")


async def test_read_only_still_lets_the_agent_look() -> None:
    agent = ScriptedAgent(kind="read")
    report, _, _ = await _run(agent, access="read_only")
    assert agent.replied == {"outcome": {"outcome": "selected", "optionId": "ok"}}
    assert report.refused == []


def test_a_request_with_no_usable_option_is_cancelled_not_guessed() -> None:
    assert acp.permission_reply("edit", {"toolCall": {"kind": "edit"}, "options": []}) == {
        "outcome": {"outcome": "cancelled"}
    }
    odd = {"toolCall": {"kind": "edit"}, "options": ["x", {"kind": "allow_once"}]}
    assert acp.permission_reply("edit", odd)["outcome"]["outcome"] == "cancelled"
    always = {"options": [{"optionId": "a", "kind": "allow_always"}], "toolCall": {"kind": "edit"}}
    assert acp.permission_reply("edit", always)["outcome"]["optionId"] == "a"


async def test_a_request_the_client_does_not_offer_is_answered_with_an_error() -> None:
    agent = ScriptedAgent()
    collector = acp._Collector()
    conversation = acp.Conversation(
        ScriptedPipe(agent), access="edit", collector=collector, shown=_nothing
    )
    await conversation._handle(
        {"jsonrpc": "2.0", "id": 7, "method": "fs/read_text_file", "params": {"path": "/x"}}
    )
    assert agent.seen[0]["error"]["code"] == -32601
    await conversation._handle({"jsonrpc": "2.0", "method": "$/progress"})
    await conversation._handle(
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": "not an object"}}
    )
    assert len(agent.seen) == 1


async def _nothing(items: list[Any]) -> None:
    return None


async def test_an_error_answer_stops_the_task_with_the_agents_words() -> None:
    with pytest.raises(acp.AcpError, match="nope"):
        await _run(ScriptedAgent(fail_on="session/new"))


async def test_an_error_without_a_message_still_says_something() -> None:
    agent = ScriptedAgent()
    agent.fail_on = "initialize"
    original = agent.on_message

    def bare(message: dict[str, Any]) -> None:
        original(message)
        if agent.out and "error" in agent.out[-1]:
            agent.out[-1]["error"] = "unexpected"

    agent.on_message = bare  # type: ignore[method-assign]
    with pytest.raises(acp.AcpError, match="refused the request"):
        await _run(agent)


async def test_a_session_the_agent_did_not_open_is_an_error() -> None:
    agent = ScriptedAgent()
    original = agent.on_message

    def empty(message: dict[str, Any]) -> None:
        original(message)
        if message.get("method") == "session/new":
            agent.out[-1]["result"] = {}

    agent.on_message = empty  # type: ignore[method-assign]
    with pytest.raises(acp.AcpError, match="did not open a session"):
        await _run(agent)


@pytest.mark.parametrize("stop", ["max_tokens", "refusal", "cancelled"])
async def test_a_stop_other_than_end_of_turn_is_a_failed_task(stop: str) -> None:
    report, _, _ = await _run(ScriptedAgent(stop=stop))
    assert report.outcome == "failed"
    assert report.answer == "Done."


async def test_a_stop_with_nothing_said_names_the_reason() -> None:
    agent = ScriptedAgent(stop="refusal")
    original = agent.on_message

    def quiet(message: dict[str, Any]) -> None:
        original(message)
        agent.out[:] = [
            m
            for m in agent.out
            if m.get("params", {}).get("update", {}).get("sessionUpdate") != "agent_message_chunk"
        ]

    agent.on_message = quiet  # type: ignore[method-assign]
    report, _, _ = await _run(agent)
    assert "refusal" in report.answer


async def test_a_task_past_its_time_is_cancelled_and_reported() -> None:
    agent = ScriptedAgent()
    original = agent.on_message

    def never_finishes(message: dict[str, Any]) -> None:
        if message.get("method") == "session/prompt":
            agent.seen.append(message)
            return
        original(message)

    agent.on_message = never_finishes  # type: ignore[method-assign]
    report, _, pipe = await _run(agent, timeout=0)
    assert report.outcome == "timed_out"
    assert "Hand it a narrower task" in report.answer
    assert agent.seen[-1]["method"] == "session/cancel"
    assert agent.seen[-1]["params"] == {"sessionId": "s-1"}
    assert pipe.closed


def test_a_tool_the_agent_never_ends_and_updates_it_knows_nothing_of_are_handled() -> None:
    collector = acp._Collector()
    assert collector.update({"sessionUpdate": "plan"}) == []
    assert collector.update({"sessionUpdate": "tool_call_update", "toolCallId": "ghost"}) == []
    started = collector.update(
        {"sessionUpdate": "tool_call", "toolCallId": "t", "kind": "mystery", "title": "Do a thing"}
    )
    assert started == [StepStarted("t", CodingStep(kind="other", title="Do a thing"))]
    # The same call announced again is an update, not a second step.
    assert (
        collector.update({"sessionUpdate": "tool_call", "toolCallId": "t", "title": "Renamed"})
        == []
    )
    assert collector.update({"sessionUpdate": "tool_call", "kind": "read"}) == []
    report = collector.report(
        harness="codex", access="edit", outcome="failed", answer="x" * 40_000, session_id=None
    )
    assert report.steps == [CodingStep(kind="other", title="Renamed")]
    assert report.outcome == "failed"
    assert "more characters" in report.answer


class FakeDevice:
    def __init__(self, polls: list[dict[str, Any]], opened: Any = None) -> None:
        self.polls = polls
        self.opened = {"id": "proc"} if opened is None else opened
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def agent_call(self, op: str, args: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        self.calls.append((op, args))
        if op == "agent.open":
            return self.opened
        if op == "agent.poll":
            return self.polls.pop(0)
        return {}


async def test_the_device_pipe_polls_from_its_cursor_and_skips_what_is_not_a_message() -> None:
    device = FakeDevice(
        [
            {"lines": [], "cursor": 0, "exit": None},
            {"lines": ['{"id": 1}', "not json", "[1]", None], "cursor": 4, "exit": None},
        ]
    )
    pipe = acp.DevicePipe(device, "codex")
    await pipe.open()
    await pipe.send({"id": 1})
    assert await pipe.receive() == {"id": 1}
    polls = [args for op, args in device.calls if op == "agent.poll"]
    assert polls == [
        {"id": "proc", "cursor": 0, "wait_ms": acp.POLL_WAIT_MS},
        {"id": "proc", "cursor": 0, "wait_ms": acp.POLL_WAIT_MS},
    ]
    assert device.calls[0] == ("agent.open", {"agent": "codex"})
    assert device.calls[1] == ("agent.send", {"id": "proc", "message": {"id": 1}})
    await pipe.close()
    assert device.calls[-1] == ("agent.close", {"id": "proc"})


async def test_the_device_pipe_reports_an_exit_without_what_the_agent_printed() -> None:
    device = FakeDevice(
        [{"lines": [], "cursor": 0, "exit": 1, "stderr": "ENOENT /Users/me/.npmrc token=abc\n"}]
    )
    pipe = acp.DevicePipe(device, "claude_code")
    await pipe.open()
    with pytest.raises(acp.AgentExited) as exited:
        await pipe.receive()
    assert exited.value.code == 1
    assert "exit code 1" in exited.value.message and "Node.js 22" in exited.value.message
    assert "npmrc" not in exited.value.message and "token" not in exited.value.message


async def test_the_device_pipe_delivers_what_was_written_before_the_exit() -> None:
    device = FakeDevice([{"lines": ['{"a": 1}'], "cursor": 1, "exit": 0, "stderr": ""}])
    pipe = acp.DevicePipe(device, "claude_code")
    await pipe.open()
    assert await pipe.receive() == {"a": 1}


async def test_the_device_pipe_refuses_an_open_with_no_process_and_closes_nothing_unopened() -> (
    None
):
    device = FakeDevice([], opened={})
    pipe = acp.DevicePipe(device, "claude_code")
    with pytest.raises(acp.AcpError, match="did not start"):
        await pipe.open()
    await pipe.close()
    assert [op for op, _ in device.calls] == ["agent.open"]


class Computer:
    """The device hub's side of a computer that runs the scripted agent."""

    def __init__(self, agent: ScriptedAgent, *, unavailable: bool = False) -> None:
        self.agent = agent
        self.unavailable = unavailable
        self.ops: list[str] = []
        self.cursor = 0
        self.lines: list[str] = []

    async def call(
        self, session_id: Any, op: str, args: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        self.ops.append(op)
        if self.unavailable:
            raise DeviceUnavailable(message="Your computer is not connected")
        if op == "agent.open":
            assert args["agent"] == "claude_code" and args["root"] == "/w"
            return {"id": "p1"}
        if op == "agent.send":
            self.agent.on_message(args["message"])
            self.lines += [json.dumps(m) for m in self.agent.out]
            self.agent.out.clear()
            return {}
        if op == "agent.poll":
            lines = self.lines[args["cursor"] :]
            return {"lines": lines, "cursor": args["cursor"] + len(lines), "exit": None}
        if op == "agent.close":
            return {}
        raise DeviceCallFailed(message="refused", details={})


def _ctx(workspace: Any, frames: list[SubagentEvent]) -> RunContext[AgentDeps]:
    async def sink(frame: SubagentEvent) -> None:
        frames.append(frame)

    ctx = RunContext(
        deps=AgentDeps(
            organization_id=uuid4(),
            user_id=str(uuid4()),
            conversation_id=uuid4(),
            subagent_events=sink,
            audience=RunAudience(user_id=uuid4()),
        ),
        model=TestModel(),
        usage=RunUsage(),
        retry=0,
        max_retries=1,
        tool_call_id="call-1",
    )
    if workspace is not None:
        ctx.workspace = workspace
    return ctx


def _local_workspace() -> WrapperWorkspace:
    device = workspace_module.DeviceWorkspace(
        uuid4(), uuid4(), LocalTarget(folder="/w", mode="full_access")
    )
    return WrapperWorkspace(Workspace(device))


async def _local_task(
    monkeypatch: pytest.MonkeyPatch, computer: Computer, workspace: Any, task: str = "Fix it"
) -> tuple[str, list[SubagentEvent]]:
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    monkeypatch.setattr("app.agents.capabilities.coding_agent._acp.POLL_WAIT_MS", 0)
    frames: list[SubagentEvent] = []
    tools = build_coding_toolset(
        harness="claude_code",
        access="edit",
        model=None,
        base_url=None,
        api_key=None,
        timeout_seconds=60,
        runs_on="this_computer",
    ).tools
    answer = await tools["run_coding_agent"].function(_ctx(workspace, frames), task=task)
    return answer, frames


async def test_on_this_computer_the_task_needs_no_key_and_reports_like_any_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = Computer(ScriptedAgent())
    answer, frames = await _local_task(monkeypatch, computer, _local_workspace())
    report = json.loads(answer)
    assert report["kind"] == "coding_agent"
    assert report["outcome"] == "completed"
    assert report["answer"] == "Done."
    assert report["files_changed"] == ["/w/a.py", "/w/b.py"]
    assert computer.ops[0] == "agent.open" and computer.ops[-1] == "agent.close"
    kinds = [type(frame).__name__ for frame in frames]
    assert kinds[0] == "SubagentStarted" and kinds[-1] == "SubagentFinished"
    assert "SubagentToolCall" in kinds and "SubagentToolResult" in kinds
    assert frames[-1].status == "completed"


async def test_a_chat_not_working_on_a_computer_is_told_how_to_fix_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = Computer(ScriptedAgent())
    answer, frames = await _local_task(monkeypatch, computer, None)
    assert "Work on needs to be set to This computer" in answer
    assert computer.ops == [] and frames == []


async def test_an_empty_local_task_asks_for_a_description(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic_ai.exceptions import ModelRetry

    with pytest.raises(ModelRetry, match="Describe the task"):
        await _local_task(monkeypatch, Computer(ScriptedAgent()), _local_workspace(), task="  ")


async def test_a_computer_that_is_gone_ends_the_panel_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_module, "RECONNECT_SECONDS", 0)

    async def gone(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(workspace_module._hub, "wait_for", gone)
    answer, frames = await _local_task(
        monkeypatch, Computer(ScriptedAgent(), unavailable=True), _local_workspace()
    )
    assert answer.startswith("Claude Code could not run on this computer:")
    assert frames[-1].status == "failed"


async def test_an_agent_that_fails_to_start_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    computer = Computer(ScriptedAgent())
    original = computer.call

    async def poll_exits(
        session_id: Any, op: str, args: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        if op == "agent.poll":
            return {"lines": [], "cursor": 0, "exit": 1, "stderr": "Node.js 22 is required"}
        return await original(session_id, op, args, timeout=timeout)

    computer.call = poll_exits  # type: ignore[method-assign]
    answer, _ = await _local_task(monkeypatch, computer, _local_workspace())
    assert "exit code 1" in answer and "Node.js 22 or later" in answer
    assert "is required" not in answer


async def test_a_stopped_local_task_closes_its_panel_and_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = Computer(ScriptedAgent())
    original = computer.call

    async def cancelled(
        session_id: Any, op: str, args: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        if op == "agent.poll":
            raise anyio.get_cancelled_exc_class()()
        return await original(session_id, op, args, timeout=timeout)

    computer.call = cancelled  # type: ignore[method-assign]
    frames: list[SubagentEvent] = []
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    tools = build_coding_toolset(
        harness="claude_code",
        access="edit",
        model=None,
        base_url=None,
        api_key=None,
        timeout_seconds=60,
        runs_on="this_computer",
    ).tools
    with pytest.raises(BaseException) as raised:
        await tools["run_coding_agent"].function(_ctx(_local_workspace(), frames), task="Fix it")
    assert isinstance(raised.value, anyio.get_cancelled_exc_class())
    assert frames[-1].status == "cancelled"
    assert computer.ops[-1] == "agent.close"


def test_the_capability_says_where_the_agent_works() -> None:
    local = CodingAgent(runs_on="this_computer")
    assert "on the person's own computer" in local.get_instructions()
    assert "in your sandbox" in CodingAgent().get_instructions()
    assert local.get_toolset() is local.get_toolset()


def test_running_on_this_computer_is_the_one_case_that_needs_no_key() -> None:
    from app.agents.capabilities import get

    config = CodingAgentConfig(runs_on="this_computer")
    assert config.runs_on == "this_computer"
    assert CodingAgentConfig().runs_on == "sandbox"
    secret = get("coding_agent").secret
    assert secret is not None and secret.optional_when is not None
    assert secret.optional_when.is_met(config)
    assert not secret.optional_when.is_met(CodingAgentConfig())
    # Publish demands a key where the agent runs in the sandbox, and only there.
    assert secret.required_when is not None
    assert secret.required_when.is_met(CodingAgentConfig())
    assert not secret.required_when.is_met(config)


async def test_a_poll_without_a_cursor_keeps_the_last_one() -> None:
    device = FakeDevice(
        [
            {"lines": ['{"a": 1}'], "cursor": 1, "exit": None},
            {"lines": ['{"b": 2}'], "exit": None},
        ]
    )
    pipe = acp.DevicePipe(device, "codex")
    await pipe.open()
    assert await pipe.receive() == {"a": 1}
    assert await pipe.receive() == {"b": 2}
    polls = [args for op, args in device.calls if op == "agent.poll"]
    assert [poll["cursor"] for poll in polls] == [0, 1]


def test_updates_with_odd_shapes_are_read_as_far_as_they_go() -> None:
    collector = acp._Collector()
    assert collector.update({"sessionUpdate": "agent_message_chunk", "content": {"text": 5}}) == []
    assert collector.said == []
    odd = {
        "sessionUpdate": "tool_call",
        "toolCallId": "e",
        "kind": "edit",
        "title": "Edit",
        "locations": ["not an object", {"path": 3}, {"path": "/w/ok.py"}],
        "content": ["text", {"type": "terminal"}, {"type": "diff", "path": "/w/diff.py"}],
    }
    collector.update(odd)
    assert collector.tools["e"].edits == ["/w/ok.py", "/w/diff.py"]


async def test_a_reply_to_another_request_is_not_the_one_waited_for() -> None:
    agent = ScriptedAgent()
    conversation = acp.Conversation(
        ScriptedPipe(agent), access="edit", collector=acp._Collector(), shown=_nothing
    )
    agent.out.append({"jsonrpc": "2.0", "id": 999, "result": {"for": "somebody else"}})
    agent.out.append({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    assert await conversation.request("initialize", {}) == {"ok": True}


async def test_a_pipe_that_cannot_close_does_not_hide_the_report() -> None:
    agent = ScriptedAgent()
    pipe = ScriptedPipe(agent)

    async def refuse() -> None:
        raise OSError("already gone")

    pipe.close = refuse  # type: ignore[method-assign]
    collected: list[Any] = []

    async def collect(items: list[Any]) -> None:
        collected.extend(items)

    report = await acp.run_task(
        pipe,
        harness="claude_code",
        access="edit",
        root="/w",
        task="Fix",
        timeout_seconds=60,
        shown=collect,
    )
    assert report.outcome == "completed"


def test_a_rejection_is_recognised_by_the_option_that_was_chosen() -> None:
    params = {"options": [ALLOW, REJECT, "junk"]}
    assert acp._was_rejected(params, {"outcome": {"outcome": "selected", "optionId": "no"}})
    assert not acp._was_rejected(params, {"outcome": {"outcome": "selected", "optionId": "ok"}})


def test_a_task_on_this_computer_does_not_promise_a_session_it_does_not_keep() -> None:
    local = CodingAgent(runs_on="this_computer")
    assert "Each task starts a new session" in local.get_instructions()
    assert "continue the same session" not in local.get_instructions()
    schema = local.get_toolset().tools["run_coding_agent"].function_schema.json_schema  # type: ignore[attr-defined]
    parameters = {
        name: " ".join(spec["description"].lower().split())
        for name, spec in schema["properties"].items()
    }
    assert "every task starts a new session" in parameters["task"]
    assert "every task is a new session" in parameters["fresh_session"]
    sandbox = CodingAgent().get_toolset().tools["run_coding_agent"].function_schema.json_schema  # type: ignore[attr-defined]
    assert "continuing" in sandbox["properties"]["fresh_session"]["description"].lower()


def test_a_model_is_refused_where_the_agent_uses_its_own_and_a_gateway_is_dropped() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="leave Model empty"):
        CodingAgentConfig(runs_on="this_computer", model="anthropic:claude-opus-5-5")
    config = CodingAgentConfig(runs_on="this_computer", base_url="https://openrouter.ai/api")
    assert config.base_url is None and config.model is None
    assert CodingAgentConfig(model="anthropic:claude-opus-5-5").model is not None
