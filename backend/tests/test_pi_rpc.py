"""Native Pi acceptance, settlement, dialog refusal and process ownership."""

from collections import deque
from collections.abc import Awaitable, Callable

import anyio
import pytest

from app.agents.capabilities.coding_agent._acp import AcpError, AgentExited
from app.agents.capabilities.coding_agent._harness import (
    CodingReport,
    LiveItem,
    Said,
    StepEnded,
    StepStarted,
)
from app.agents.capabilities.external_acp._pi import _Record, _Session, inspect_pi, run_pi

pytestmark = pytest.mark.anyio


MODEL = {"id": "configured-model", "name": "Configured model", "provider": "configured-provider"}
STATE = {
    "model": MODEL,
    "sessionId": "native-id",
    "sessionFile": "/private/pi/session.jsonl",
    "isStreaming": False,
    "isCompacting": False,
    "pendingMessageCount": 0,
}


def finished(text: str = "Done", reason: str = "stop") -> dict[str, object]:
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stopReason": reason,
        },
    }


class Pi:
    def __init__(
        self, events: list[dict[str, object]] | None = None, *, fast: bool = False
    ) -> None:
        self.events = (
            events
            if events is not None
            else [finished(), {"type": "agent_settled", "aborted": False}]
        )
        self.fast = fast
        self.messages: deque[dict[str, object]] = deque()
        self.seen: list[dict[str, object]] = []
        self.closed = False
        self.state: dict[str, object] = dict(STATE)
        self.models: object = [MODEL]
        self.disposition = "started"
        self.cancelled: object = False
        self.refuse: str | None = None
        self.mismatch = False
        self.idle = False

    async def send(self, message: dict[str, object]) -> None:
        self.seen.append(message)
        command = message.get("type")
        if command in {"clear_queue", "abort", "extension_ui_response"}:
            return
        data: object = {}
        if command == "get_state":
            data = self.state
        elif command == "get_available_models":
            data = {"models": self.models}
        elif command in {"new_session", "switch_session"}:
            data = {"cancelled": self.cancelled}
        elif command == "prompt":
            data = {"disposition": self.disposition}
            if self.fast:
                self.messages.extend(self.events)
        self.messages.append(
            {
                "type": "response",
                "id": "wrong" if self.mismatch else message.get("id"),
                "command": command,
                "success": command != self.refuse,
                "data": data,
            }
        )
        if command == "prompt" and not self.fast:
            self.messages.extend(self.events)

    async def receive(self) -> dict[str, object]:
        if self.messages:
            return self.messages.popleft()
        if self.idle:
            await anyio.sleep_forever()
        raise AgentExited(1)

    async def close(self) -> None:
        self.closed = True


async def ignore(_items: list[LiveItem]) -> None:
    pass


async def run(
    pi: Pi,
    *,
    model: str | None = None,
    effort: str | None = None,
    remember: Callable[[str], Awaitable[None]] | None = None,
) -> CodingReport:
    return await run_pi(
        pi,
        task="Investigate",
        timeout_seconds=1,
        shown=ignore,
        model=model,
        effort=effort,
        remember=remember,
    )


@pytest.mark.parametrize("fast", [False, True])
async def test_waits_for_settlement_including_events_before_prompt_ack(fast: bool) -> None:
    pi = Pi(
        [
            finished("First"),
            {"type": "agent_end"},
            {"type": "auto_retry_start"},
            finished("Authoritative retry answer"),
            {"type": "agent_settled"},
        ],
        fast=fast,
    )
    remembered: list[str] = []

    async def remember(path: str) -> None:
        remembered.append(path)

    result = await run(pi, remember=remember)
    assert result.outcome == "completed" and result.answer == "Authoritative retry answer"
    assert result.session_id == "native-id" and remembered == ["/private/pi/session.jsonl"]
    assert pi.closed and not any(m["type"] == "abort" for m in pi.seen)
    assert pi.seen[0]["type"] == "new_session"


async def test_streams_text_and_tool_steps_but_final_message_owns_the_answer() -> None:
    pi = Pi(
        [
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "partial"},
            },
            {"type": "tool_execution_start", "toolCallId": "one", "toolName": "bash"},
            {"type": "tool_execution_end", "toolCallId": "one", "isError": True},
            finished("Final"),
            {"type": "agent_settled"},
        ]
    )
    shown: list[LiveItem] = []

    async def show(items: list[LiveItem]) -> None:
        shown.extend(items)

    report = await run_pi(
        pi, task="Work", shown=show, timeout_seconds=1, previous_session="/private/owned-session"
    )
    assert report.answer == "Final" and report.steps[0].failed
    assert [type(item) for item in shown] == [Said, StepStarted, StepEnded]
    assert pi.seen[0]["sessionPath"] == "/private/owned-session"


@pytest.mark.parametrize(
    "reason,aborted",
    [("error", False), ("aborted", True), ("length", False), ("toolUse", False), ("stop", True)],
)
async def test_provider_failure_or_abort_never_becomes_success(reason: str, aborted: bool) -> None:
    pi = Pi([finished("Unreliable", reason), {"type": "agent_settled", "aborted": aborted}])
    result = await run(pi)
    assert result.outcome == "failed" and "Unreliable" not in result.answer
    assert pi.closed


@pytest.mark.parametrize("disposition", ["handled", "queued", "unexpected"])
async def test_acceptance_does_not_promise_work(disposition: str) -> None:
    pi = Pi([])
    pi.disposition = disposition
    with pytest.raises(AcpError, match="did not start"):
        await run(pi)
    assert [m["type"] for m in pi.seen][-2:] == ["clear_queue", "abort"]
    assert pi.closed


@pytest.mark.parametrize("method", ["select", "confirm", "input", "editor"])
@pytest.mark.security
async def test_extension_dialog_is_cancelled_without_invented_approval(method: str) -> None:
    pi = Pi([{"type": "extension_ui_request", "id": "question", "method": method}])
    with pytest.raises(AcpError, match="human input"):
        await run(pi)
    assert {"type": "extension_ui_response", "id": "question", "cancelled": True} in pi.seen
    assert pi.closed


@pytest.mark.parametrize(
    "change",
    [
        {"model": None},
        {"isStreaming": True},
        {"isCompacting": True},
        {"pendingMessageCount": 1},
        {"sessionId": ""},
    ],
)
async def test_invalid_or_busy_state_refuses_before_inference(change: dict[str, object]) -> None:
    pi = Pi()
    pi.state.update(change)
    with pytest.raises(AcpError):
        await run(pi)
    assert not any(m["type"] == "prompt" for m in pi.seen) and pi.closed


@pytest.mark.parametrize("field", ["model", "effort"])
async def test_configuration_overrides_do_not_mutate_cli_defaults(field: str) -> None:
    pi = Pi()
    with pytest.raises(AcpError, match="CLI"):
        await run(pi, **{field: "changed"})
    assert not any(m["type"] == "prompt" for m in pi.seen) and pi.closed


async def test_timeout_and_external_cancellation_clear_queue_then_close() -> None:
    pi = Pi([])
    pi.idle = True
    report = await run_pi(pi, task="Work", timeout_seconds=0, shown=ignore)
    assert report.outcome == "timed_out" and pi.closed
    pi = Pi([])
    pi.idle = True
    with anyio.move_on_after(0.02) as deadline:
        await run(pi)
    assert deadline.cancel_called and pi.closed
    assert [m["type"] for m in pi.seen][-2:] == ["clear_queue", "abort"]


async def test_discovery_uses_native_provider_qualified_ids_without_prompt() -> None:
    pi = Pi()
    catalog = await inspect_pi(pi, timeout_seconds=1)
    assert catalog.configuration_policy == "cli"
    assert catalog.current_model == "configured-provider/configured-model"
    assert catalog.models[0].id == catalog.current_model
    assert not any(m["type"] == "prompt" for m in pi.seen) and pi.closed


@pytest.mark.parametrize("models", [[MODEL, MODEL], [{}], [MODEL] * 129])
async def test_ambiguous_malformed_or_excessive_catalogs_are_refused(models: object) -> None:
    pi = Pi()
    pi.models = models
    with pytest.raises(AcpError):
        await inspect_pi(pi, timeout_seconds=1)
    assert pi.closed


@pytest.mark.parametrize("cancelled", [True, None])
async def test_extension_can_refuse_session_open(cancelled: object) -> None:
    pi = Pi()
    pi.cancelled = cancelled
    with pytest.raises(AcpError, match="refused to open"):
        await run(pi)
    assert not any(m["type"] == "prompt" for m in pi.seen) and pi.closed


@pytest.mark.parametrize("mismatch", [False, True])
async def test_rpc_errors_are_sanitized_and_correlated(mismatch: bool) -> None:
    pi = Pi()
    pi.refuse, pi.mismatch = "get_state", mismatch
    with pytest.raises(AcpError, match="refused or mismatched"):
        await run(pi)
    assert pi.closed


@pytest.mark.parametrize(
    "record",
    [
        {"type": "extension_ui_request", "method": "confirm"},
        {"type": "extension_error"},
        {"type": "message_end", "message": {"role": "assistant"}},
        {"type": "message_end", "message": {"role": "assistant", "content": ["invalid"]}},
        finished("x" * 128001),
        {"type": "tool_execution_start"},
        {"type": "tool_execution_end"},
        {"type": "response", "command": "unexpected"},
    ],
)
async def test_malformed_or_unowned_events_fail_closed(record: dict[str, object]) -> None:
    pi = Pi([record])
    with pytest.raises(AcpError):
        await run(pi)
    assert pi.closed


async def test_event_count_and_invalid_records_are_bounded() -> None:
    pi = Pi()
    session = _Session(pi, ignore, received=16384)
    with pytest.raises(AcpError, match="event limit"):
        await session.receive()
    pi.messages.append({"type": 1})
    with pytest.raises(AcpError, match="unsupported RPC record"):
        await _Session(pi, ignore).receive()
    await _Session(pi, ignore).event(_Record(type="message_end", message={"role": "user"}))


async def test_persistent_sessions_require_an_owned_storage_reference() -> None:
    pi = Pi()
    pi.state["sessionFile"] = None

    async def remember(_path: str) -> None:
        pytest.fail("no storage reference was available")

    with pytest.raises(AcpError, match="persistent session storage"):
        await run(pi, remember=remember)
    assert pi.closed


async def test_miscellaneous_native_events_do_not_invent_updates() -> None:
    pi = Pi()
    session = _Session(pi, ignore)
    pi.messages.append({"type": "extension_ui_request", "id": "notice", "method": "notify"})
    await session.receive()
    await session.event(
        _Record(type="message_update", assistantMessageEvent={"type": "thinking_delta"})
    )
    await session.event(_Record(type="message_end", message="Human dialog message"))
    await session.event(_Record(type="tool_execution_start", toolCallId="one", toolName="Read"))
    assert not session.answer
    assert len(session.active) == 1


async def test_live_pi_answer_reaches_the_waiting_extension_and_native_settlement() -> None:
    from app.agents.runtime_questions import (
        RuntimeAnswer,
        RuntimeQuestionRequest,
        RuntimeQuestionResponse,
    )

    ready = anyio.Event()

    class DialogPi(Pi):
        async def send(self, message: dict[str, object]) -> None:
            await super().send(message)
            if message.get("type") == "extension_ui_response":
                self.messages.extend([finished("Human answered"), {"type": "agent_settled"}])
                ready.set()

        async def receive(self) -> dict[str, object]:
            if not self.messages:
                await ready.wait()
            return await super().receive()

    async def human(request: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
        assert request.questions[0].question == "Which one?"
        return RuntimeQuestionResponse(answers=[RuntimeAnswer(selected=["B"])])

    pi = DialogPi(
        [
            {
                "type": "extension_ui_request",
                "id": "dialog",
                "method": "select",
                "title": "Which one?",
                "options": ["A", "B"],
            }
        ]
    )
    report = await run_pi(pi, task="Ask", timeout_seconds=1, shown=ignore, runtime_questions=human)
    assert report.answer == "Human answered" and report.outcome == "completed"
    assert {"type": "extension_ui_response", "id": "dialog", "value": "B"} in pi.seen
    assert pi.closed


async def test_pi_terminal_event_cancels_a_live_question_before_waiting_for_an_answer() -> None:
    from app.agents.runtime_questions import RuntimeQuestionRequest, RuntimeQuestionResponse

    asking = anyio.Event()
    released = anyio.Event()

    class TerminalPi(Pi):
        async def receive(self) -> dict[str, object]:
            if self.messages and self.messages[0].get("type") == "agent_settled":
                await asking.wait()
            return await super().receive()

    async def human(_request: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
        asking.set()
        try:
            await anyio.sleep_forever()
        finally:
            released.set()

    pi = TerminalPi(
        [
            {
                "type": "extension_ui_request",
                "id": "dialog",
                "method": "confirm",
                "title": "Continue?",
            },
            finished(),
            {"type": "agent_settled"},
        ]
    )
    report = await run_pi(pi, task="Ask", timeout_seconds=1, shown=ignore, runtime_questions=human)
    assert report.outcome == "completed" and released.is_set() and pi.closed
    assert not any(message.get("type") == "extension_ui_response" for message in pi.seen)


@pytest.mark.parametrize("tool", ["run_acp_agent", "inspect_acp_agent"])
async def test_pi_is_selected_by_the_registered_native_protocol_in_the_real_tool_path(
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
) -> None:
    import json

    from app.agents.capabilities.external_acp._capability import ExternalAcp
    from app.services.device_hub import workspace as workspace_module
    from tests.test_coding_agent_acp import _ctx, _local_workspace

    pi = Pi()
    operations: list[str] = []
    remembered: list[str] = []
    launch: dict[str, object] = {}
    cursor = 0

    async def call(
        _session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        nonlocal cursor
        operations.append(op)
        if op == "agent.open":
            launch.update(args)
            return {"id": "pi-process", "protocol": "pi_rpc", "runtime_name": "My Pi"}
        if op == "agent.send":
            message = args["message"]
            assert isinstance(message, dict)
            await pi.send(message)
            return {}
        if op == "agent.poll":
            lines = [json.dumps(message) for message in pi.messages]
            pi.messages.clear()
            cursor += len(lines)
            return {"lines": lines, "cursor": cursor, "exit": None}
        if op == "agent.remember":
            value = args["session_id"]
            assert isinstance(value, str)
            remembered.append(value)
        if op == "agent.close":
            await pi.close()
        return {}

    monkeypatch.setattr(workspace_module._hub, "call", call)
    function = ExternalAcp("my-pi").get_toolset().tools[tool].function
    context = _ctx(_local_workspace(), [])
    result = (
        await function(context, task="Work") if tool == "run_acp_agent" else await function(context)
    )
    report = json.loads(result)
    assert launch["custom_agent_id"] == "my-pi"
    assert launch["accepted_protocols"] == ["acp", "pi_rpc"]
    if tool == "run_acp_agent":
        assert report["answer"] == "Done" and report["runtime_name"] == "My Pi"
        assert remembered == ["/private/pi/session.jsonl"]
    else:
        assert report["current_model"] == "configured-provider/configured-model"
        assert not remembered
    assert operations[-1] == "agent.close" and pi.closed


@pytest.mark.parametrize("protocol", ["msp-unknown", [], None])
async def test_unknown_runtime_protocol_is_refused_and_native_child_closed(
    protocol: object,
) -> None:
    from app.agents.capabilities.coding_agent._acp import DevicePipe
    from tests.test_coding_agent_acp import FakeDevice

    device = FakeDevice([], opened={"id": "process", "protocol": protocol})
    pipe = DevicePipe(device, "custom", custom_agent_id="registered")
    with pytest.raises(AcpError, match="unsupported runtime protocol"):
        await pipe.open()
    assert device.calls[-1][0] == "agent.close"


class _OneShot:
    def __init__(self, *records: dict[str, object]) -> None:
        self.records = list(records)
        self.sent: list[dict[str, object]] = []

    async def receive(self) -> dict[str, object]:
        return self.records.pop(0)

    async def send(self, message: dict[str, object]) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        pass


async def _no_items(_items: list[LiveItem]) -> None:
    return None


async def test_a_bridge_cancellation_stops_only_its_own_platform_call() -> None:
    pipe = _OneShot(
        {"method": "_agenticos/cancel_request", "params": {"id": "t1"}},
        {"method": "_agenticos/cancel_request", "params": "malformed"},
    )
    session = _Session(pipe, _no_items)
    mine, other = anyio.CancelScope(), anyio.CancelScope()
    session.tool_scopes.update({"t1": mine, "t2": other})
    assert (await session.receive()).type == "agenticos_bridge"
    assert mine.cancel_called and not other.cancel_called
    assert (await session.receive()).type == "agenticos_bridge"


async def test_platform_requests_without_an_enabled_bridge_are_refused() -> None:
    session = _Session(
        _OneShot({"id": "t1", "method": "_agenticos/tools/call", "params": {}}), _no_items
    )
    with pytest.raises(AcpError, match="unadmitted"):
        await session.receive()


async def test_a_malformed_platform_request_is_retired_without_dispatch() -> None:
    session = _Session(_OneShot(), _no_items)
    scope = anyio.CancelScope()
    session.tool_scopes["t1"] = scope
    with pytest.raises(AcpError, match="Malformed"):
        await session.answer_tool({"method": "_agenticos/tools/call", "params": []}, "t1", scope)
    assert "t1" in session.retired_tools and "t1" not in session.tool_scopes


async def test_an_unsupported_dialog_without_an_identifier_is_cancelled() -> None:
    pipe = _OneShot()
    session = _Session(pipe, _no_items)
    record = _Record.model_validate({"type": "extension_ui_request", "method": "select"})
    with pytest.raises(AcpError, match="unsupported human-input"):
        await session.answer_dialog(record)
    assert pipe.sent[-1]["cancelled"] is True


async def test_ignoring_live_items_is_a_no_op() -> None:
    from app.agents.capabilities.external_acp import _pi

    assert await _pi._ignore([Said("x")]) is None


async def test_discovery_without_a_selected_model_keeps_the_catalog_order() -> None:
    pi = Pi()
    pi.state = {**STATE, "model": None}
    pi.models = [MODEL, {**MODEL, "id": "second"}]
    catalog = await inspect_pi(pi, timeout_seconds=1)
    assert catalog.current_model is None
    assert [model.id for model in catalog.models] == [
        "configured-provider/configured-model",
        "configured-provider/second",
    ]


async def test_several_pi_task_failures_are_not_reduced_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from app.agents.capabilities.external_acp import _pi

    class Group:
        cancel_scope = MagicMock()

        def start_soon(self, *_args) -> None:
            return None

        async def __aenter__(self):
            raise BaseExceptionGroup("both", [ValueError("one"), KeyError("two")])

        async def __aexit__(self, *_exc) -> None:
            return None

    monkeypatch.setattr(_pi.anyio, "create_task_group", Group)
    with pytest.raises(BaseExceptionGroup):
        await run_pi(Pi(), task="Work", timeout_seconds=1, shown=_no_items)


async def test_a_declined_dialog_without_an_identifier_still_answers_pi() -> None:
    from app.agents.runtime_questions import RuntimeQuestionResponse

    async def declined(_request):
        return RuntimeQuestionResponse(cancelled=True)

    pipe = _OneShot()
    session = _Session(pipe, _no_items, runtime_questions=declined)
    record = _Record.model_validate(
        {"type": "extension_ui_request", "method": "confirm", "title": "Continue?"}
    )
    await session.answer_dialog(record)
    assert pipe.sent[-1]["type"] == "extension_ui_response"
