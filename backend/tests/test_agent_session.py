"""Tests for the chat WebSocket session's agent-only contract.

The template's general assistant used to answer any frame that named no agent.
It is gone: the factory is the only way to get a runnable agent, so a frame
without an `agent_id` is refused before anything is persisted. These pin the
refusal - the transcript must not collect messages nothing will answer.

`TestForwardingToolEvents` is here for a different reason: this module is not in
the coverage gate, and the one field it reads off a Pydantic AI event was renamed
under it. Nothing noticed until every tool call in web chat answered "❌ Error:
'FunctionToolResultEvent' object has no attribute 'result'".

`TestForwardingDelegationFrames` is here for the third reason: the delegation
frames are a *contract with the client*, and both halves of it fail silently. A
wire name chosen here instead of taken from the frame's own `kind` leaves the
client switching on a case nothing sends, and a `Decimal` serialised the way
Pydantic serialises one in JSON mode reaches a chat that formats cost as a number
and renders `NaN`.

`TestStoppingATurnMidDelegation` is here for the fourth, and it is the reason this
module runs a real agent at all. Delegation puts work in an `asyncio.Task` the
parent run does not await, and **this** is where a turn is cancelled: `stop` and
`shutdown` both cancel `_turn_task`. A background delegation cancelled correctly
in isolation says nothing about one cancelled under this teardown, where the
cancellation arrives from outside, travels through `Agent.iter`, and every
finalizer that has to run - the library's task cancellation, this platform's
accounting sweep - runs while a `CancelledError` is already propagating.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import anyio
import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai.tools import DeferredToolRequests

from app.agents.capabilities import CapabilityBinding, build
from app.agents.capabilities.budget import SpendEntry, SpendLedger
from app.agents.capabilities.subagents import Delegation
from app.agents.deps import AgentDeps
from app.agents.subagent_events import (
    SubagentFinished,
    SubagentStarted,
    SubagentTextDelta,
    SubagentToolCall,
)
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    DelegationOutcome,
    ResolvedSubagent,
    SubagentRuntime,
)
from app.db.models.agent_run import RunStatus
from app.services.agent_session import AgentSession

pytestmark = pytest.mark.anyio


def _session() -> AgentSession:
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    user = MagicMock()
    organization = MagicMock()
    return AgentSession(websocket, user, organization)


def _sent_events(session: AgentSession) -> list[tuple[str, dict]]:
    return [
        (call.args[0]["type"], call.args[0]["data"])
        for call in session.websocket.send_json.call_args_list
    ]


class TestFramesWithoutAnAgent:
    async def test_a_frame_naming_no_agent_is_refused_before_anything_is_persisted(self):
        """There is no assistant to fall back to, and a message nothing will
        answer does not belong in the transcript."""
        session = _session()

        with patch("app.services.agent_session.persist_user_turn", new=AsyncMock()) as persist:
            await session.process_message({"message": "hello"})

        events = _sent_events(session)
        assert len(events) == 1
        event_type, data = events[0]
        assert event_type == "error"
        assert "Pick an agent" in data["message"]
        persist.assert_not_called()

    async def test_a_frame_naming_something_that_is_not_an_agent_id_is_refused(self):
        """Ignoring a malformed id would silently run something the user never
        picked; refusing it names the problem."""
        session = _session()

        with patch("app.services.agent_session.persist_user_turn", new=AsyncMock()) as persist:
            await session.process_message({"message": "hello", "agent_id": "not-a-uuid"})

        events = _sent_events(session)
        assert len(events) == 1
        event_type, data = events[0]
        assert event_type == "error"
        assert "not a valid agent id" in data["message"]
        persist.assert_not_called()

    async def test_an_empty_frame_is_still_refused_as_empty(self):
        """The emptiness check stays first: a blank frame is a client bug, not
        a missing agent."""
        session = _session()

        await session.process_message({"message": ""})

        events = _sent_events(session)
        assert events == [("error", {"message": "Empty message"})]


class TestForwardingToolEvents:
    """What a tool call looks like on the wire, read off real event objects.

    Constructed from `pydantic_ai.messages` rather than mocked, deliberately: a
    `MagicMock` answers to `.result`, `.part` and anything else, so a test built on
    one would have kept passing through exactly the rename that broke this.
    """

    async def test_a_tool_result_is_forwarded_with_its_content(self):
        from pydantic_ai.messages import (
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            ToolCallPart,
            ToolReturnPart,
        )

        session = _session()
        collected: list[dict] = []

        async def _events():
            yield FunctionToolCallEvent(
                part=ToolCallPart(
                    tool_name="write_file", args={"path": "/a.txt"}, tool_call_id="t1"
                )
            )
            yield FunctionToolResultEvent(
                part=ToolReturnPart(
                    tool_name="write_file", content="wrote /a.txt", tool_call_id="t1"
                )
            )

        await session._stream_tool_events(_events(), collected)

        assert [event for event in _sent_events(session) if event[0] == "tool_result"] == [
            ("tool_result", {"tool_call_id": "t1", "content": "wrote /a.txt"})
        ]

    async def test_the_result_is_kept_on_the_call_it_belongs_to(self):
        """The transcript persists one row per call, so a result that did not find
        its call is a tool call recorded as never having returned."""
        from pydantic_ai.messages import (
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            ToolCallPart,
            ToolReturnPart,
        )

        session = _session()
        collected: list[dict] = []

        async def _events():
            yield FunctionToolCallEvent(
                part=ToolCallPart(tool_name="ls", args={}, tool_call_id="t1")
            )
            yield FunctionToolResultEvent(
                part=ToolReturnPart(tool_name="ls", content=["/a.txt"], tool_call_id="t1")
            )

        await session._stream_tool_events(_events(), collected)

        assert collected == [
            {"tool_call_id": "t1", "tool_name": "ls", "args": {}, "result": "['/a.txt']"}
        ]

    async def test_a_retry_is_reported_rather_than_swallowed(self):
        """A tool that raised sends a `RetryPromptPart` down the same stream. It
        carries `content` too, and a card that never resolved would spin forever."""
        from pydantic_ai.messages import FunctionToolResultEvent, RetryPromptPart

        session = _session()

        async def _events():
            yield FunctionToolResultEvent(
                part=RetryPromptPart(content="path must be absolute", tool_call_id="t9")
            )

        await session._stream_tool_events(_events(), [])

        [(_type, data)] = [event for event in _sent_events(session) if event[0] == "tool_result"]
        assert data == {"tool_call_id": "t9", "content": "path must be absolute"}


class TestForwardingDelegationFrames:
    """What the client hears while a specialist is working."""

    async def test_a_frame_is_sent_under_the_name_the_union_gave_it(self):
        """The wire `type` is the frame's own `kind`. A name chosen in the session
        instead would leave the client switching on a case nothing sends, and a
        delegation would simply never appear - no error anywhere."""
        session = _session()

        await session._subagent_event(
            SubagentStarted(
                task_id="task-1",
                subagent="researcher",
                depth=0,
                mode="sync",
                prompt="find three papers",
            )
        )

        assert _sent_events(session) == [
            (
                "subagent_start",
                {
                    "kind": "subagent_start",
                    "task_id": "task-1",
                    "subagent": "researcher",
                    "depth": 0,
                    "mode": "sync",
                    "prompt": "find three papers",
                },
            )
        ]

    async def test_every_kind_reaches_the_client_under_its_own_type(self):
        """Six literals, and the client has a branch per literal. One of them
        dropped here is one panel that never opens, never fills or never closes."""
        session = _session()
        frames = [
            SubagentTextDelta(task_id="t", subagent="researcher", depth=0, delta="found "),
            SubagentToolCall(
                task_id="t",
                subagent="researcher",
                depth=0,
                tool_name="search_documents",
                tool_call_id="c1",
            ),
        ]

        for frame in frames:
            await session._subagent_event(frame)

        assert [event_type for event_type, _data in _sent_events(session)] == [
            "subagent_text_delta",
            "subagent_tool_call",
        ]

    async def test_what_a_delegation_cost_arrives_as_a_number(self):
        """A `Decimal` serialises to a *string* in JSON mode, and the chat formats
        cost as a number - the panel would have rendered `NaN` for every finished
        delegation. The turn's own cost is already a number on this wire; a
        delegation's share of it is the same quantity."""
        session = _session()
        run_id = uuid4()

        await session._subagent_event(
            SubagentFinished(
                task_id="t",
                subagent="researcher",
                depth=0,
                status="completed",
                run_id=run_id,
                cost_usd=Decimal("0.0042"),
                input_tokens=1200,
                output_tokens=340,
            )
        )

        [(event_type, data)] = _sent_events(session)
        assert event_type == "subagent_complete"
        assert data["cost_usd"] == 0.0042
        assert isinstance(data["cost_usd"], float)
        assert data["run_id"] == str(run_id)

    async def test_a_delegation_that_recorded_no_cost_reports_none_rather_than_zero(self):
        """Nothing measured and nothing spent are different things to draw."""
        session = _session()

        await session._subagent_event(
            SubagentFinished(
                task_id="t",
                subagent="researcher",
                depth=0,
                status="failed",
                error="the provider refused",
            )
        )

        [(_event_type, data)] = _sent_events(session)
        assert data["cost_usd"] is None
        assert data["error"] == "the provider refused"

    async def test_a_frame_arriving_after_the_tab_closed_does_not_take_the_run_down(self):
        """A background delegation outlives the answer it was started for, so its
        last frames can land on a socket that has gone. `send_event` reports that
        rather than raising; a raise here would surface as a crashed turn task."""
        session = _session()
        session.websocket.send_json = AsyncMock(side_effect=RuntimeError("socket is closed"))

        await session._subagent_event(
            SubagentFinished(task_id="t", subagent="researcher", depth=0, status="completed")
        )


_DELEGATE_REQUEST = SpendEntry(
    model_name="test", input_tokens=7, output_tokens=3, cost_usd=Decimal("2.00"), priced=True
)
"""What the delegate's one model request costs, before the parent is stopped.

Two dollars, and the number is the point: a cancelled run that spent it and
recorded zero is the hole cancellation opens, and nothing about it looks like an
error.
"""

_CONVERSATION = "11111111-1111-1111-1111-111111111111"


def _delegating_parent() -> FunctionModel:
    """A parent that delegates in the background, then never answers.

    Both halves of `FunctionModel` because the chat *iterates* its run and streams
    each node - which is exactly why the cancellation has to be tested here: a
    surface that awaited an answer instead would unwind through a different path.
    """

    def delegated(messages: list[ModelMessage]) -> bool:
        return any(
            isinstance(part, ToolReturnPart) for message in messages for part in message.parts
        )

    def call_task() -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "task",
                    {"description": "find the price", "subagent_type": "researcher"},
                    tool_call_id="call-1",
                )
            ]
        )

    async def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not delegated(messages):
            return call_task()
        await anyio.sleep(30)
        return ModelResponse(parts=[TextPart("too late")])

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        if not delegated(messages):
            yield {
                0: DeltaToolCall(
                    name="task",
                    json_args='{"description": "find the price", "subagent_type": "researcher"}',
                    tool_call_id="call-1",
                )
            }
        else:
            await anyio.sleep(30)
            yield "too late"

    return FunctionModel(respond, stream_function=stream)


def _spending_delegate(ledger: SpendLedger, spent: asyncio.Event) -> ResolvedSubagent:
    """A specialist that bills the run's shared ledger and then works on forever.

    The billing stands in for the budget guard, which is what records a real
    request. It happens *before* the sleep, and `spent` is what a test waits on
    rather than a delay: the assertion is about what a cancelled run reports
    having spent, so the money has to be on the ledger before the stop arrives.
    """

    async def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        ledger.entries.append(_DELEGATE_REQUEST)
        spent.set()
        await anyio.sleep(30)
        return ModelResponse(parts=[TextPart("too late")])

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        ledger.entries.append(_DELEGATE_REQUEST)
        spent.set()
        await anyio.sleep(30)
        yield "too late"

    def build_it() -> PydanticAgent[Any, Any]:
        return PydanticAgent(
            FunctionModel(respond, stream_function=stream),
            system_prompt="You research.",
            output_type=[str, DeferredToolRequests],
        )

    return ResolvedSubagent(
        name="researcher",
        description="Researches a topic.",
        build=build_it,
        agent_id=uuid4(),
        agent_version_id=uuid4(),
    )


class _Turn:
    """One prepared chat turn, assembled around a real agent that delegates.

    Everything the runner would have resolved from the database is supplied here;
    what is real is the part under test - the agent, the delegation capability, the
    run's shared ledger, and the cancellation path from `stop` to the run row.
    """

    def __init__(self) -> None:
        self.ledger = SpendLedger()
        self.spent = asyncio.Event()
        self.outcomes: list[DelegationOutcome] = []
        self.finished: list[tuple[RunStatus, Decimal, int, int]] = []
        self.runtime = SubagentRuntime(
            subagents=(_spending_delegate(self.ledger, self.spent),),
            record=self._record,
            depth_remaining=1,
            ledger=self.ledger,
        )
        capabilities = build(
            [CapabilityBinding(capability_id="subagents", config={"mode": "async"})],
            resources={SUBAGENT_RUNTIME_RESOURCE: self.runtime},
        )
        (delegation,) = capabilities
        assert isinstance(delegation, Delegation)
        self.delegation = delegation
        self.prepared = self._prepared(
            PydanticAgent(
                _delegating_parent(),
                system_prompt="You orchestrate.",
                output_type=[str, DeferredToolRequests],
                capabilities=capabilities,
            )
        )

    async def _record(self, outcome: DelegationOutcome) -> UUID | None:
        self.outcomes.append(outcome)
        return uuid4()

    async def _finish(self, prepared: Any, **kwargs: Any) -> MagicMock:
        """Stand in for the runner's terminal write, recording what it would write.

        The row's numbers are `prepared.built.ledger` read at this moment, so
        capturing them here is capturing the row: that `finish` writes exactly
        these is `tests/test_agent_runner.py::TestRunAccounting`'s job, and
        repeating it would be a second copy of one assertion. What is *not*
        established anywhere else is that this is reached at all when the turn is
        cancelled, with the delegate's spend already on the ledger.
        """
        ledger = prepared.built.ledger
        self.finished.append(
            (kwargs["status"], ledger.total_usd, ledger.input_tokens, ledger.output_tokens)
        )
        return MagicMock()

    def _prepared(self, agent: PydanticAgent[Any, Any]) -> MagicMock:
        prepared = MagicMock()
        prepared.run = MagicMock(id=uuid4(), agent_version_id=uuid4())
        prepared.agent = MagicMock(id=uuid4())
        prepared.deps = AgentDeps(organization_id=uuid4(), run_id=uuid4())
        prepared.workspace = None
        prepared.spec.budget = None
        prepared.approvals.parked = {}
        prepared.approvals.requested = []
        prepared.built.agent = agent
        prepared.built.ledger = self.ledger
        prepared.built.model_label = "gpt-4.1"
        # Real `None` rather than a mock: Pydantic AI reads this per request.
        prepared.built.usage_limits = None
        return prepared

    @contextmanager
    def patched(self) -> Iterator[None]:
        """Everything between the frame and the agent that needs a database."""
        with (
            patch("app.services.agent_session.persist_user_turn", new=AsyncMock()) as persist,
            patch("app.services.agent_session.get_db_context") as db_context,
            patch("app.services.agent_chat.member_repo") as members,
            patch("app.services.agent_chat.AgentRunnerService") as runner_cls,
        ):
            persist.return_value = (_CONVERSATION, False)
            db_context.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(commit=AsyncMock())
            )
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            members.get = AsyncMock(return_value=MagicMock())
            runner_cls.return_value.prepare = AsyncMock(return_value=self.prepared)
            runner_cls.return_value.finish = self._finish
            yield

    async def in_flight(self) -> None:
        """Wait until the delegate has made a request of its own and is still working.

        The delegate's own model sets this, which is the only signal that means
        what the tests need it to: the background task exists, it has reached the
        model, and the money is on the ledger - so a stop arriving now is a stop
        arriving mid-delegation rather than a race with one.
        """
        with anyio.fail_after(5):
            await self.spent.wait()


class TestStoppingATurnMidDelegation:
    """`stop` while a background delegation is running, through the real teardown.

    One scenario, four assertions, because the failures are independent: a leaked
    task keeps spending against a closed session, a missing terminal frame leaves
    the client's spinner running forever, an unrecorded delegation loses its cost,
    and a run row written as if nothing was spent is a bill nobody can explain.
    """

    async def test_a_stopped_turn_leaves_nothing_running_and_still_books_what_it_spent(self):
        turn = _Turn()
        session = _session()
        alive_before = len(asyncio.all_tasks())

        with turn.patched():
            await session.handle_frame({"message": "price this up", "agent_id": str(uuid4())})
            await turn.in_flight()
            assert turn.delegation.journal.in_flight() == 1

            await session.handle_frame({"type": "stop"})

        # Nothing survives the stop: not the delegate's task, not the turn's.
        assert turn.delegation.journal.tasks.list_active_tasks() == []
        assert len(asyncio.all_tasks()) == alive_before
        assert session._turn_task is None

        # The client is told the turn is over, or its composer never comes back.
        assert _sent_events(session)[-1] == (
            "complete",
            {"conversation_id": _CONVERSATION, "stopped": True},
        )

        # The delegation's share is attributed, and the run row carries it. A
        # cancelled run that spent two dollars and recorded zero is the whole
        # reason this test exists.
        (outcome,) = turn.outcomes
        assert outcome.status == "cancelled"
        assert outcome.cost_usd == _DELEGATE_REQUEST.cost_usd
        assert turn.finished == [
            (RunStatus.CANCELLED, _DELEGATE_REQUEST.cost_usd, 7, 3),
        ]

    async def test_the_panel_a_delegation_opened_is_closed_on_the_way_out(self):
        """The frames a client draws with, on the path that produces none of the
        usual ones. A `subagent_start` with no `subagent_complete` is a panel that
        narrates a specialist still working on a turn that ended minutes ago."""
        turn = _Turn()
        session = _session()

        with turn.patched():
            await session.handle_frame({"message": "price this up", "agent_id": str(uuid4())})
            await turn.in_flight()
            await session.handle_frame({"type": "stop"})

        delegation_frames = [
            (event_type, data)
            for event_type, data in _sent_events(session)
            if event_type.startswith("subagent_")
        ]
        assert [event_type for event_type, _ in delegation_frames] == [
            "subagent_start",
            "subagent_complete",
        ]
        opened, closed = (data for _type, data in delegation_frames)
        assert opened["mode"] == "async"
        assert closed["status"] == "cancelled"
        assert closed["cost_usd"] == float(_DELEGATE_REQUEST.cost_usd)

    async def test_shutting_the_socket_down_cancels_the_same_way(self):
        """`shutdown` is the other caller, and it runs when nobody is watching -
        a closed tab, a redeploy. It goes through the same cancellation, so a
        delegation cannot be left running by the path with no client to notice."""
        turn = _Turn()
        session = _session()

        with turn.patched():
            await session.handle_frame({"message": "price this up", "agent_id": str(uuid4())})
            await turn.in_flight()
            await session.shutdown()

        assert turn.delegation.journal.tasks.list_active_tasks() == []
        assert [outcome.status for outcome in turn.outcomes] == ["cancelled"]
        assert [status for status, *_ in turn.finished] == [RunStatus.CANCELLED]
