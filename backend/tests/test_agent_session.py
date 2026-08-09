"""Tests for the chat WebSocket session - every frame it sends, and every frame
it accepts.

`app/services/agent_session.py` decides the whole dashboard chat wire format, and
it is now in the coverage gate and under strict `ty` (#165). It had been in
neither, which is why the file it shares that format with - `use-chat.ts` - has
twice been left switching on a name the backend had changed. So these tests are
written against the *frames*: what reaches `websocket.send_json`, in what order,
with which keys. A test that executes the translation without reading its output
is what let a third of this module go unmeasured while looking tested.

The template's general assistant used to answer any frame that named no agent.
It is gone: the factory is the only way to get a runnable agent, so a frame
without an `agent_id` is refused before anything is persisted. These pin the
refusal - the transcript must not collect messages nothing will answer.

`TestForwardingToolEvents` is here for a different reason: the one field it reads
off a Pydantic AI event was renamed under it while this module was ungated.
Nothing noticed until every tool call in web chat answered "❌ Error:
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
import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import anyio
import pytest
from fastapi import WebSocketDisconnect
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import (
    BinaryContent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelResponse,
    OutputToolCallEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai.tools import DeferredToolRequests
from subagents_pydantic_ai import TaskStatus

from app.agents.capabilities import CapabilityBinding, build
from app.agents.capabilities.budget import BudgetExceeded, BudgetScope, SpendEntry, SpendLedger
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
from app.core.exceptions import AuthorizationError, BadRequestError
from app.db.models.agent_run import RunStatus
from app.services.agent import PersistedPrompt
from app.services.agent_chat import ChatTurn, OpenedRun
from app.services.agent_runner import ParkedApproval, PreparedRun
from app.services.agent_session import AgentSession
from app.services.chat_timeline import TurnTimeline
from app.services.usage_report import UsageReport

pytestmark = pytest.mark.anyio

_CONVERSATION = "11111111-1111-1111-1111-111111111111"


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


def _frame_types(session: AgentSession) -> list[str]:
    return [event_type for event_type, _data in _sent_events(session)]


def _message(text: str = "how many are open?", **extra: Any) -> dict[str, Any]:
    """A bare frame naming an agent - what a client sends to start a turn."""
    return {"message": text, "agent_id": str(uuid4()), **extra}


def _finished_turn(
    *,
    output: str = "Two are open.",
    parked: tuple[ParkedApproval, ...] = (),
    usage: UsageReport | None = None,
) -> ChatTurn:
    return ChatTurn(
        output=output,
        model_label="gpt-4.1",
        agent_id=uuid4(),
        agent_version_id=uuid4(),
        run_id=uuid4(),
        parked=parked,
        usage=usage,
    )


@contextmanager
def _chat(
    run: AsyncMock,
    *,
    conversation: str | None = _CONVERSATION,
    newly_created: bool = False,
    message_id: str | None = "saved-1",
    prompt_message_id: UUID | None = None,
) -> Iterator[SimpleNamespace]:
    """The session's collaborators, stubbed at the seam this module owns.

    `ChatAgentRunner.run` is `agent_chat.py`'s contract - gated there, and driven
    for real by `TestStoppingATurnMidDelegation` below. What is under test here is
    the *frames* this session puts on the wire for a turn that ended a particular
    way, so the runner is where the stub goes and `run` is how a test says how the
    turn ended.

    Yields the two persistence stubs, for the tests that read what this module
    hands them rather than what it puts on the wire.
    """
    prompt = AsyncMock(
        return_value=PersistedPrompt(
            conversation_id=conversation,
            newly_created=newly_created,
            message_id=prompt_message_id,
        )
    )
    answer = AsyncMock(return_value=message_id)
    with (
        patch("app.services.agent_session.persist_user_turn", new=prompt),
        patch("app.services.agent_session.persist_assistant_turn", new=answer),
        patch("app.services.agent_session.get_db_context") as db_context,
        patch("app.services.agent_session.ChatAgentRunner") as runner_cls,
    ):
        db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)
        runner_cls.return_value.run = run
        yield SimpleNamespace(prompt=prompt, answer=answer, runner=runner_cls.return_value)


def _next_frame(session: AgentSession) -> asyncio.Event:
    """An event set when the session next writes to the socket.

    A turn running as a background task has to be *waited* for rather than slept
    past, and this is the only signal that means "the frames up to here are out".
    """
    sent = asyncio.Event()

    async def record(*_args: Any, **_kwargs: Any) -> None:
        sent.set()

    session.websocket.send_json.side_effect = record
    return sent


async def _wait(event: asyncio.Event) -> None:
    """Wait, with a bound - so a broken test fails rather than hanging the suite."""
    with anyio.fail_after(5):
        await event.wait()


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


class TestControlFrames:
    """What `handle_frame` does with each `type` a client can send.

    Only a *bare* frame is a message. Everything with a `type` is protocol, and
    the wrong answer to an unknown one is to run it as a prompt.
    """

    async def test_a_control_frame_nothing_recognises_starts_no_turn(self):
        """A named frame is a client saying something about itself. Answering it
        out loud would put a piece of protocol in the transcript."""
        session = _session()

        await session.handle_frame({"type": "ping", "message": "hello"})

        assert _sent_events(session) == []
        assert session._turn_task is None

    async def test_stopping_when_no_turn_is_running_says_nothing(self):
        """The composer's stop button races the turn's last frame, so a `stop`
        routinely arrives after the turn is over. A second terminal frame then
        would end the *next* turn on the client the moment it started."""
        session = _session()

        await session.handle_frame({"type": "stop"})

        assert _sent_events(session) == []

    async def test_a_message_arriving_while_a_turn_is_in_flight_is_ignored(self):
        """Two turns on one socket interleave their deltas into one message and
        race the in-memory history the next turn's `message_history` is built
        from. The second frame is dropped rather than queued: the client's
        composer is disabled while a turn runs, so a second bare frame is a bug
        somewhere rather than something a user did."""
        session = _session()
        running = asyncio.Event()
        release = asyncio.Event()

        async def blocks_until_released(**_kwargs: Any) -> ChatTurn:
            running.set()
            await release.wait()
            return _finished_turn()

        with _chat(AsyncMock(side_effect=blocks_until_released)):
            await session.handle_frame(_message("first"))
            turn_task = session._turn_task
            assert turn_task is not None
            await _wait(running)

            await session.handle_frame(_message("second"))
            release.set()
            await turn_task

        assert _frame_types(session) == ["user_prompt", "message_saved", "complete"]
        assert _sent_events(session)[0] == ("user_prompt", {"content": "first"})

    async def test_a_message_arriving_after_the_previous_turn_ended_starts_a_new_one(self):
        """The slot is freed by a done callback, which runs a loop iteration after
        the task ended - so a frame can arrive with `_turn_task` still holding a
        finished task. Reading `done()` rather than the slot is what keeps that
        from looking like a turn in flight."""
        session = _session()

        with _chat(AsyncMock(return_value=_finished_turn())):
            await session.handle_frame(_message("first"))
            first = session._turn_task
            assert first is not None
            await first
            # Put it back: awaiting it here ran the callback, which is the one
            # thing a client's frame cannot wait for.
            session._turn_task = first

            await session.handle_frame(_message("second"))
            second = session._turn_task
            assert second is not None and second is not first
            await second

        assert [
            data["content"] for event, data in _sent_events(session) if event == "user_prompt"
        ] == [
            "first",
            "second",
        ]


class TestATurnThatFinished:
    """The frames a completed turn puts on the wire, and their order.

    Order is part of the contract: `conversation_created` carries the id the
    `complete` frame's usage is filed under, and `tool_approval_required` has to
    arrive while the turn is still on screen.
    """

    async def test_a_turn_that_started_a_conversation_announces_it_first(self):
        session = _session()

        with _chat(AsyncMock(return_value=_finished_turn()), newly_created=True):
            await session.process_message(_message())

        assert _frame_types(session) == [
            "conversation_created",
            "user_prompt",
            "message_saved",
            "complete",
        ]
        assert _sent_events(session)[0] == (
            "conversation_created",
            {"conversation_id": _CONVERSATION},
        )
        assert _sent_events(session)[2] == (
            "message_saved",
            {"message_id": "saved-1", "conversation_id": _CONVERSATION},
        )

    async def test_both_halves_of_the_turn_are_filed_under_the_run_that_produced_them(self):
        """`messages.run_id` is what makes a run's transcript readable from run
        history rather than only from the conversation. The answer carries it
        directly; the question is handed to the runner, which links it as soon as
        it has opened a run - the prompt is written before there is one."""
        session = _session()
        turn = _finished_turn()
        prompt_message_id = uuid4()

        with _chat(AsyncMock(return_value=turn), prompt_message_id=prompt_message_id) as chat:
            await session.process_message(_message())

        assert chat.answer.await_args.kwargs["run_id"] == turn.run_id
        assert chat.runner.run.await_args.kwargs["prompt_message_id"] == prompt_message_id

    async def test_a_turn_in_an_existing_conversation_does_not_announce_one(self):
        """The client creates a thread in its sidebar on this frame, so a second
        one for a conversation it is already in would duplicate the entry."""
        session = _session()

        with _chat(AsyncMock(return_value=_finished_turn())):
            await session.process_message(_message())

        assert "conversation_created" not in _frame_types(session)

    async def test_what_the_turn_cost_arrives_on_the_frame_that_ends_it(self):
        """Its own event would be one the client could receive *after* `complete`
        and draw against the next turn. Every number is a JSON number: the chat
        draws a bar from them, and `Decimal` serialises as a string."""
        session = _session()
        report = UsageReport(
            input_tokens=1200,
            output_tokens=340,
            cost_usd=Decimal("0.0042"),
            period_spend_usd=Decimal("5.00"),
            budget_usd=Decimal("20.00"),
        )

        with _chat(AsyncMock(return_value=_finished_turn(usage=report))):
            await session.process_message(_message())

        assert _sent_events(session)[-1] == (
            "complete",
            {
                "conversation_id": _CONVERSATION,
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 340,
                    "cost_usd": 0.0042,
                    "budget_percent": 25,
                    "agent_budget_percent": None,
                    "sandbox": None,
                },
            },
        )

    async def test_a_turn_nobody_could_measure_reports_no_usage_rather_than_zero(self):
        """Assembling the report is not allowed to lose an answer, so it can come
        back `None`. Nothing measured and nothing spent are different things to
        draw, and the strip leaves the previous turn's number alone for `None`."""
        session = _session()

        with _chat(AsyncMock(return_value=_finished_turn(usage=None))):
            await session.process_message(_message())

        assert _sent_events(session)[-1] == (
            "complete",
            {"conversation_id": _CONVERSATION, "usage": None},
        )

    async def test_a_turn_whose_conversation_was_never_persisted_still_ends(self):
        """`persist_user_turn` logs and swallows a write failure, deliberately - a
        lost row must not lose an answer somebody is waiting for. There is then
        nothing to save the assistant message against, but the client still has to
        be told the turn is over or its composer never comes back.

        The frame list is what pins it: `persist_assistant_turn` is stubbed to
        answer with an id, so a write attempted against no conversation would show
        up here as a `message_saved` pointing at `null`."""
        session = _session()

        with _chat(AsyncMock(return_value=_finished_turn()), conversation=None):
            await session.process_message(_message())

        assert _frame_types(session) == ["user_prompt", "complete"]
        assert _sent_events(session)[-1] == ("complete", {"conversation_id": None, "usage": None})

    async def test_an_assistant_message_that_did_not_save_is_not_announced_as_saved(self):
        """`message_saved` is what swaps the client's temporary id for the real
        one. Sending it without an id would leave the message unratable and
        unreloadable, pointing at `null`."""
        session = _session()

        with _chat(AsyncMock(return_value=_finished_turn()), message_id=None):
            await session.process_message(_message())

        assert _frame_types(session) == ["user_prompt", "complete"]

    async def test_the_turn_is_remembered_for_the_next_one(self):
        """In-memory history is what the next turn's `message_history` is built
        from, and it is appended only after a complete run."""
        session = _session()

        with _chat(AsyncMock(return_value=_finished_turn(output="Two are open."))):
            await session.process_message(_message("how many are open?"))

        assert session.conversation_history == [
            {"role": "user", "content": "how many are open?"},
            {"role": "assistant", "content": "Two are open."},
        ]

    async def test_a_parked_call_is_put_in_front_of_whoever_is_looking(self):
        """The approvals queue and the email carry the same rows; this frame is the
        shortcut for somebody already on the tab. It arrives *before* `complete` so
        the panel is drawn while the turn is still on screen, and `allow_edit` is
        false on purpose: the arguments were recorded on the row the approver is
        deciding about, so letting the chat rewrite them would approve something
        other than what was asked."""
        session = _session()
        approval_id = uuid4()
        parked = (
            ParkedApproval(
                approval_id=approval_id,
                tool_call_id="call-1",
                tool_name="send_email",
                tool_args={"to": "ops@example.com"},
            ),
        )
        turn = _finished_turn(parked=parked)

        with _chat(AsyncMock(return_value=turn)):
            await session.process_message(_message())

        assert _frame_types(session) == [
            "user_prompt",
            "message_saved",
            "tool_approval_required",
            "complete",
        ]
        assert _sent_events(session)[2] == (
            "tool_approval_required",
            {
                "run_id": str(turn.run_id),
                "action_requests": [
                    {
                        "id": str(approval_id),
                        "tool_call_id": "call-1",
                        "tool_name": "send_email",
                        "args": {"to": "ops@example.com"},
                    }
                ],
                "review_configs": [{"tool_name": "send_email", "allow_edit": False}],
            },
        )


class TestATurnThatDidNotFinish:
    """Every way a turn can end without an answer.

    `error` is the frame that clears the client's processing state, so a refusal
    that sent nothing would leave a spinner running until the tab is reloaded.
    There is deliberately no `complete` after it: that frame means the turn
    produced something.
    """

    async def test_a_conversation_belonging_to_another_organization_is_refused(self):
        """The socket authenticated against one organization; resuming a thread
        from another would read one org's history while billing a second."""
        session = _session()
        refusal = AuthorizationError(
            message="Conversation belongs to a different organization",
            details={"conversation_id": _CONVERSATION},
        )

        with patch(
            "app.services.agent_session.persist_user_turn", new=AsyncMock(side_effect=refusal)
        ):
            await session.process_message(_message(conversation_id=_CONVERSATION))

        assert _sent_events(session) == [
            ("error", {"message": "Conversation belongs to a different organization"})
        ]

    async def test_a_refused_run_is_reported_and_not_answered_by_anything_else(self):
        """An unpublished or archived agent, or one that is not theirs to see. The
        platform working, so it is said plainly - and nothing answers in the named
        agent's place."""
        session = _session()

        with _chat(AsyncMock(side_effect=BadRequestError(message="That agent is not published"))):
            await session.process_message(_message())

        assert _frame_types(session) == ["user_prompt", "error"]
        assert _sent_events(session)[-1] == ("error", {"message": "That agent is not published"})
        assert session.conversation_history == []

    async def test_a_budget_stop_says_why_the_answer_stopped(self):
        """A run cut off by a cap looks identical to a broken agent unless
        somebody says so."""
        session = _session()
        stopped = BudgetExceeded(
            limit_usd=Decimal("20.00"),
            spent_usd=Decimal("20.0100"),
            scope=BudgetScope.ORGANIZATION,
        )

        with _chat(AsyncMock(side_effect=stopped)):
            await session.process_message(_message())

        assert _frame_types(session) == ["user_prompt", "error"]
        assert _sent_events(session)[-1] == (
            "error",
            {"message": "Organization monthly budget exhausted: $20.0100 spent of $20.00 limit"},
        )

    async def test_an_unexpected_failure_still_reaches_the_client(self):
        """A provider that answered 500 is not a refusal and not a bug in the
        spec, and the person sitting there gets told either way."""
        session = _session()

        with _chat(AsyncMock(side_effect=RuntimeError("the provider answered 503"))):
            await session.process_message(_message())

        assert _frame_types(session) == ["user_prompt", "error"]
        assert _sent_events(session)[-1] == ("error", {"message": "the provider answered 503"})

    async def test_a_disconnect_is_not_reported_to_the_socket_that_left(self):
        """A `WebSocketDisconnect` surfacing from inside the turn is re-raised
        rather than turned into an `error` frame: there is nobody to read it, and
        the turn task's callback logs a disconnect instead of a crash."""
        session = _session()

        with (
            _chat(AsyncMock(side_effect=WebSocketDisconnect(code=1006))),
            pytest.raises(WebSocketDisconnect),
        ):
            await session.process_message(_message())

        assert _frame_types(session) == ["user_prompt"]


class TestATurnTaskThatEnded:
    """`asyncio.create_task` swallows the exception of a task nobody awaits, and
    the turn task is never awaited on the success path - so this callback is the
    only place a crashed turn is ever heard about."""

    @staticmethod
    async def _ran(coro: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        with contextlib.suppress(Exception):
            await task
        return task

    async def test_a_crashed_turn_is_logged_with_its_traceback(self, caplog):
        session = _session()

        async def crash() -> None:
            raise RuntimeError("the run row was written twice")

        task = await self._ran(crash())

        with caplog.at_level(logging.ERROR, logger="app.services.agent_session"):
            session._on_turn_done(task)

        assert "Agent turn task crashed" in caplog.text
        assert "the run row was written twice" in caplog.text

    async def test_a_disconnect_is_not_logged_as_a_crash(self, caplog):
        """A tab closed mid-turn is how most sessions end. An error-level line for
        it is noise an operator learns to skip past, which is how the next real
        one gets skipped too."""
        session = _session()

        async def disconnect() -> None:
            raise WebSocketDisconnect(code=1001)

        task = await self._ran(disconnect())

        with caplog.at_level(logging.INFO, logger="app.services.agent_session"):
            session._on_turn_done(task)

        assert "Client disconnected during agent turn" in caplog.text
        assert "crashed" not in caplog.text

    async def test_a_turn_that_ended_cleanly_frees_its_slot(self):
        session = _session()
        task = await self._ran(asyncio.sleep(0))
        session._turn_task = task

        session._on_turn_done(task)

        assert session._turn_task is None

    async def test_a_cancelled_turn_is_not_asked_what_went_wrong(self):
        """`task.exception()` re-raises `CancelledError` on a cancelled task, and
        it would raise it inside a done callback, where nothing is waiting to
        catch it - the loop would report it against no turn at all."""
        session = _session()
        task = asyncio.create_task(asyncio.sleep(30))
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        session._turn_task = task

        session._on_turn_done(task)

        assert session._turn_task is None

    async def test_a_callback_for_an_earlier_turn_does_not_free_a_later_one(self):
        """The callback runs a loop iteration after its task ended, so a second
        frame can already have taken the slot. Clearing it then would let a third
        frame run concurrently with the second."""
        session = _session()
        earlier = await self._ran(asyncio.sleep(0))
        later = asyncio.create_task(asyncio.sleep(30))
        session._turn_task = later

        session._on_turn_done(earlier)

        assert session._turn_task is later
        later.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await later


class TestAskingTheUser:
    """The pause an agent can put in the middle of a run.

    Only a live surface can hold a question open, and holding it open means a
    future nothing else will complete - so every way the answer can be malformed
    has to release it, or the turn parks forever with the composer showing
    questions and no way to stop it.
    """

    _QUESTIONS = [{"question": "Which region?", "options": ["eu", "us"], "allow_custom": True}]

    async def test_an_answer_reaches_the_run_that_is_waiting_for_it(self):
        session = _session()
        asked = _next_frame(session)

        asking = asyncio.create_task(session._ask_user(self._QUESTIONS))
        await _wait(asked)

        assert _sent_events(session) == [("ask_user", {"questions": self._QUESTIONS})]

        await session.handle_frame(
            {"type": "ask_user_response", "answers": [{"answer": "eu", "skipped": False}]}
        )

        assert await asking == [{"answer": "eu", "skipped": False}]
        # Cleared, or the next question resolves against a future already done.
        assert session._ask_user_future is None

    async def test_an_answers_payload_that_is_not_a_list_releases_the_run_anyway(self):
        """A client that sent `null`, or an object, would otherwise leave the run
        parked on a future nobody completes. Empty answers render as "(no answer)"
        for the model, which is a turn that goes on."""
        session = _session()
        asked = _next_frame(session)

        asking = asyncio.create_task(session._ask_user(self._QUESTIONS))
        await _wait(asked)

        await session.handle_frame({"type": "ask_user_response", "answers": None})

        assert await asking == []

    async def test_an_answer_to_a_question_nobody_asked_is_ignored(self):
        session = _session()

        await session.handle_frame({"type": "ask_user_response", "answers": [{"answer": "eu"}]})

        assert _sent_events(session) == []
        assert session._ask_user_future is None

    async def test_a_second_answer_to_the_same_question_does_not_replace_the_first(self):
        """Two frames can arrive before the run resumes - a double-submit, or a
        reconnect replaying. `Future.set_result` on a resolved future raises
        `InvalidStateError`, which would crash the frame dispatcher rather than
        the turn."""
        session = _session()
        asked = _next_frame(session)

        asking = asyncio.create_task(session._ask_user(self._QUESTIONS))
        await _wait(asked)

        await session.handle_frame({"type": "ask_user_response", "answers": [{"answer": "eu"}]})
        await session.handle_frame({"type": "ask_user_response", "answers": [{"answer": "us"}]})

        assert await asking == [{"answer": "eu"}]

    async def test_a_delegates_single_question_is_put_to_the_client_and_answered(self):
        """`_ask_one` is what a delegate's `ask_parent` reaches - one question in, one
        answer string out, over the same batch channel a whole form uses."""
        session = _session()
        asked = _next_frame(session)

        asking = asyncio.create_task(session._ask_one("Which region?", ["eu", "us"]))
        await _wait(asked)

        assert _sent_events(session) == [
            (
                "ask_user",
                {
                    "questions": [
                        {"question": "Which region?", "options": ["eu", "us"], "allow_custom": True}
                    ]
                },
            )
        ]

        await session.handle_frame(
            {"type": "ask_user_response", "answers": [{"answer": "eu", "skipped": False}]}
        )

        assert await asking == "eu"

    async def test_a_delegates_question_left_unanswered_reads_as_no_answer(self):
        """An empty answers payload releases the delegate with "(no answer)" rather
        than hanging it: the delegate goes on with what it already had."""
        session = _session()
        asked = _next_frame(session)

        asking = asyncio.create_task(session._ask_one("Which region?", []))
        await _wait(asked)

        await session.handle_frame({"type": "ask_user_response", "answers": None})

        assert await asking == "(no answer)"

    async def test_two_delegates_asking_at_once_are_served_one_at_a_time(self):
        """A fan-out of sync delegates can reach `ask_parent` concurrently.

        The channel holds one question on the wire at a time — a single
        `_ask_user_future` and a response frame with no correlation — so without
        serialisation the second question would overwrite the first's future and
        strand that delegate for the whole ask timeout, hanging the turn. Under the
        lock the second waits for the first's answer, and each delegate gets its own.
        """
        session = _session()

        first_out = _next_frame(session)
        ask1 = asyncio.create_task(session._ask_one("Region?", []))
        ask2 = asyncio.create_task(session._ask_one("Currency?", []))
        await _wait(first_out)

        # Only the first round is on the wire; the second is queued behind the lock.
        assert _frame_types(session) == ["ask_user"]
        assert _sent_events(session)[0][1]["questions"][0]["question"] == "Region?"

        second_out = _next_frame(session)
        await session.handle_frame({"type": "ask_user_response", "answers": [{"answer": "eu"}]})
        assert await ask1 == "eu"

        # Answering the first releases the lock and lets the second question out.
        await _wait(second_out)
        assert _sent_events(session)[-1][1]["questions"][0]["question"] == "Currency?"
        await session.handle_frame({"type": "ask_user_response", "answers": [{"answer": "usd"}]})
        assert await ask2 == "usd"


class TestAttachedFiles:
    async def test_a_frame_carrying_only_a_file_is_not_an_empty_message(self):
        """ "Have a look at this" with the sentence left off is an ordinary way to
        send a file, and the attachment *is* the message. The rows go to the
        runner rather than into a prompt built here: where a file lands depends on
        whether the agent has a workspace, which only `prepare` knows."""
        session = _session()
        rows = [MagicMock(), MagicMock()]
        run = AsyncMock(return_value=_finished_turn())

        with (
            _chat(run),
            patch(
                "app.services.agent_session.load_attached_files",
                new=AsyncMock(return_value=rows),
            ),
        ):
            await session.process_message(
                {"message": "", "agent_id": str(uuid4()), "file_ids": ["f1", "f2"]}
            )

        assert _frame_types(session) == ["user_prompt", "message_saved", "complete"]
        assert run.await_args is not None
        assert run.await_args.kwargs["attachments"] == rows


class TestStreamingAModelResponse:
    """Every model-request event, translated into the frame the chat reads.

    Constructed from `pydantic_ai.messages` rather than mocked for the reason
    `TestForwardingToolEvents` gives: a `MagicMock` satisfies every `isinstance`
    this translation asks about, so a test built on one proves nothing about the
    shapes the library actually sends.
    """

    @staticmethod
    async def _stream(
        session: AgentSession, *events: Any, timeline: TurnTimeline | None = None
    ) -> str | None:
        """Drive the translation over `events`, returning the collected reasoning.

        `timeline` is passed by the tests that read the text or the order back; the
        rest only care about the frames that went out.
        """

        async def _events() -> AsyncIterator[Any]:
            for event in events:
                yield event

        collected = timeline if timeline is not None else TurnTimeline()
        await session._stream_request_events(_events(), collected)
        return collected.thinking

    async def test_a_part_that_starts_with_text_already_in_it_forwards_that_text(self):
        """Some providers put the first chunk inside the part rather than sending
        it as a delta. The client only appends on `text_delta`, so without this
        the opening words of an answer are silently dropped."""
        session = _session()

        await self._stream(session, PartStartEvent(index=0, part=TextPart(content="Two ")))

        assert _sent_events(session) == [
            ("part_start", {"index": 0, "part_type": "TextPart"}),
            ("text_delta", {"index": 0, "content": "Two "}),
        ]

    async def test_a_part_that_starts_empty_sends_no_delta(self):
        session = _session()

        await self._stream(session, PartStartEvent(index=0, part=TextPart(content="")))

        assert _frame_types(session) == ["part_start"]

    async def test_a_tool_call_starting_says_only_that_a_part_started(self):
        """A tool call's name and arguments arrive on `tool_call`, from the
        handle-response stream. Drawing anything from this one would draw a card
        twice."""
        session = _session()

        await self._stream(
            session,
            PartStartEvent(
                index=1, part=ToolCallPart(tool_name="count_open", args={}, tool_call_id="c1")
            ),
        )

        assert _sent_events(session) == [("part_start", {"index": 1, "part_type": "ToolCallPart"})]

    async def test_reasoning_reaches_both_the_client_and_the_transcript(self):
        """The pane is drawn from the frame; the persisted `thinking` is drawn from
        what is collected. One without the other is a reasoning trace that
        disappears on reload, or one that was never shown."""
        session = _session()

        thinking = await self._stream(
            session, PartStartEvent(index=0, part=ThinkingPart(content="Counting the open ones"))
        )

        assert _sent_events(session) == [
            ("part_start", {"index": 0, "part_type": "ThinkingPart"}),
            ("thinking_delta", {"index": 0, "content": "Counting the open ones"}),
        ]
        assert thinking == "Counting the open ones"

    async def test_a_second_block_of_reasoning_is_separated_from_the_first(self):
        """The pieces are joined into one string for persistence, so two blocks
        run together into one word without this."""
        session = _session()

        thinking = await self._stream(
            session,
            PartStartEvent(index=0, part=ThinkingPart(content="Counting.")),
            PartStartEvent(index=2, part=ThinkingPart(content="Now checking.")),
        )

        assert thinking == "Counting. Now checking."

    async def test_reasoning_that_starts_empty_is_neither_shown_nor_recorded(self):
        session = _session()

        thinking = await self._stream(
            session, PartStartEvent(index=0, part=ThinkingPart(content=""))
        )

        assert _frame_types(session) == ["part_start"]
        assert thinking is None

    async def test_a_text_delta_is_forwarded_with_the_part_it_extends(self):
        session = _session()

        await self._stream(
            session, PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="are open."))
        )

        assert _sent_events(session) == [("text_delta", {"index": 0, "content": "are open."})]

    async def test_a_reasoning_delta_is_forwarded_and_recorded(self):
        session = _session()

        thinking = await self._stream(
            session, PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta="Counting"))
        )

        assert _sent_events(session) == [("thinking_delta", {"index": 0, "content": "Counting"})]
        assert thinking == "Counting"

    async def test_a_reasoning_delta_carrying_only_a_signature_is_not_shown(self):
        """A signature is the provider's proof it produced the reasoning, sent as
        its own delta with no content. Forwarding it would put base64 in the
        reasoning pane and in the persisted trace."""
        session = _session()

        thinking = await self._stream(
            session, PartDeltaEvent(index=0, delta=ThinkingPartDelta(signature_delta="c2ln"))
        )

        assert _sent_events(session) == []
        assert thinking is None

    async def test_tool_arguments_are_forwarded_as_they_arrive(self):
        session = _session()

        await self._stream(
            session, PartDeltaEvent(index=1, delta=ToolCallPartDelta(args_delta='{"team": '))
        )

        assert _sent_events(session) == [
            ("tool_call_delta", {"index": 1, "args_delta": '{"team": '})
        ]

    async def test_the_frame_that_says_the_answer_has_started(self):
        session = _session()

        await self._stream(session, FinalResultEvent(tool_name=None, tool_call_id=None))

        assert _sent_events(session) == [("final_result_start", {"tool_name": None})]

    async def test_a_part_ending_needs_no_frame(self):
        """The client redraws from the deltas it already applied, so a `part_end`
        it does not switch on would be a frame sent for nobody to read."""
        session = _session()

        await self._stream(session, PartEndEvent(index=0, part=TextPart(content="Two are open.")))

        assert _sent_events(session) == []


def _answering_agent(*, tools: list[Any] | None = None) -> PydanticAgent[Any, Any]:
    """An agent that answers in two chunks, optionally calling one tool first.

    `output_type` matches what the factory builds, because the approval gate needs
    `DeferredToolRequests` in the union - a run driven through a different output
    type would take a different path out of the graph.
    """

    def answered(messages: list[ModelMessage]) -> bool:
        return any(
            isinstance(part, ToolReturnPart) for message in messages for part in message.parts
        )

    async def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Two are open.")])

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        if tools is None or answered(messages):
            yield "Two "
            yield "are open."
        else:
            yield {
                0: DeltaToolCall(
                    name="count_open", json_args='{"team": "sales"}', tool_call_id="call-1"
                )
            }

    return PydanticAgent(
        FunctionModel(respond, stream_function=stream),
        output_type=[str, DeferredToolRequests],
        tools=tools or [],
    )


def count_open(team: str) -> int:
    """How many are open for one team."""
    return 2


class TestATurnThatDidNotFinishStillKeepsWhatItSaid:
    """The half-written answer, on the paths that never return a `ChatTurn`.

    A run that failed, hit its budget, was stopped or lost its socket produces no
    `ChatTurn`, so the write on the success path is skipped - and everything the
    model had already streamed used to be discarded. The run stayed in history
    pointing at a transcript holding the question and nothing else, which is the
    run somebody opens.

    Driven over a real `Agent.iter`, because the text has to travel the same route
    the client's `text_delta` frames do: what is written down is what its reader
    saw, and a stub bypassing the translation would prove neither half.
    """

    @staticmethod
    def _interrupted(failure: BaseException, *, run: OpenedRun) -> AsyncMock:
        """A `run` that opens its row, streams two chunks, and then fails."""

        async def interrupted(**kwargs: Any) -> ChatTurn:
            kwargs["on_run_open"](run)
            async with _answering_agent().iter("how many are open?") as agent_run:
                await kwargs["stream"](agent_run)
            raise failure

        return AsyncMock(side_effect=interrupted)

    @staticmethod
    def _opened() -> OpenedRun:
        return OpenedRun(run_id=uuid4(), model_label="gpt-4.1", agent_version_id=uuid4())

    @pytest.mark.parametrize(
        "failure",
        [
            RuntimeError("the provider went away"),
            BudgetExceeded(limit_usd=1, spent_usd=2, scope=BudgetScope.AGENT),
            BadRequestError(message="that agent is archived"),
        ],
        ids=["a crash", "a budget stop", "a refusal"],
    )
    async def test_the_words_the_reader_saw_are_the_words_that_are_stored(self, failure):
        session = _session()
        run = self._opened()

        with _chat(self._interrupted(failure, run=run)) as chat:
            await session.process_message(_message())

        written = chat.answer.await_args
        assert written.args[1] == "Two are open."
        assert written.kwargs["run_id"] == run.run_id
        assert written.kwargs["agent_version_id"] == run.agent_version_id
        # The model comes off the opened run, not off a `ChatTurn` that was never
        # produced - a transcript naming no model cannot answer "which one said
        # this" for the turn most likely to be asked about.
        assert written.args[2] == "gpt-4.1"

    async def test_no_cost_is_invented_for_a_turn_that_never_reported_one(self):
        """The accounting is on the run row, written by `finish`. A figure guessed
        from a partial stream would disagree with it, and the run row is the one a
        budget is enforced against."""
        session = _session()

        with _chat(self._interrupted(RuntimeError("boom"), run=self._opened())) as chat:
            await session.process_message(_message())

        assert chat.answer.await_args.kwargs.get("usage") is None

    async def test_a_turn_refused_before_its_run_existed_writes_nothing(self):
        """An unpublished agent, or a membership revoked mid-session. There is no
        run to file a turn under and nothing was produced, and a blank assistant
        message would read as the agent having answered with silence."""
        session = _session()
        refused = AsyncMock(side_effect=BadRequestError(message="that agent is not published"))

        with _chat(refused) as chat:
            await session.process_message(_message())

        chat.answer.assert_not_awaited()
        assert _frame_types(session) == ["user_prompt", "error"]

    async def test_a_turn_whose_conversation_was_never_persisted_writes_no_partial(self):
        """`persist_user_turn` logs and swallows a write failure, so a turn can run
        with no thread to write into. There is nowhere to put the partial answer,
        and the run row is still the record that the work happened."""
        session = _session()

        with _chat(
            self._interrupted(RuntimeError("boom"), run=self._opened()), conversation=None
        ) as chat:
            await session.process_message(_message())

        chat.answer.assert_not_awaited()

    async def test_a_turn_that_finished_is_written_once_and_not_twice(self):
        """The `finally` cannot read `turn` to decide - that is the whole reason it
        exists - so it reads whether the write happened. A second row here would
        duplicate every answer in the product."""
        session = _session()

        with _chat(AsyncMock(return_value=_finished_turn())) as chat:
            await session.process_message(_message())

        chat.answer.assert_awaited_once()


class TestDrivingTheRun:
    """The node dispatch, over a real `Agent.iter`.

    A hand-written iterator would say nothing about whether `node.stream(...)` is
    reached, and that is where every delta in the transcript comes from.
    """

    async def test_a_turn_that_calls_a_tool_and_then_answers(self):
        session = _session()
        tool_calls: list[dict[str, Any]] = []
        timeline = TurnTimeline()

        async with _answering_agent(tools=[count_open]).iter("how many are open?") as agent_run:
            await session._stream_agent_run(agent_run, "how many are open?", tool_calls, timeline)

        # The same words that went out as `text_delta`, kept so a turn that never
        # finishes can still be written down as what its reader saw.
        assert timeline.text == "Two are open."
        # And where they sat: the call came before the answer, which is the order a
        # reload has to reproduce.
        assert [(part.type, part.text or part.tool_call_id) for part in timeline.parts] == [
            ("tool", "call-1"),
            ("text", "Two are open."),
        ]
        types = _frame_types(session)
        assert types[0] == "user_prompt_processed"
        assert types.count("model_request_start") == 2
        assert types.count("call_tools_start") == 2
        assert types[-1] == "final_result"
        assert _sent_events(session)[-1] == ("final_result", {"output": "Two are open."})
        assert tool_calls == [
            {
                "tool_call_id": "call-1",
                "tool_name": "count_open",
                "args": {"team": "sales"},
                "result": "2",
            }
        ]

    async def test_the_prompt_reported_is_the_sentence_that_was_typed(self):
        """With an attachment the assembled prompt is a list of content objects,
        and `BinaryContent` holds the file's bytes. Forwarding that would put a
        `repr` of a PNG in the transcript where the sentence belongs."""
        session = _session()
        prompt = ["have a look at this", BinaryContent(data=b"\x89PNG", media_type="image/png")]

        async with _answering_agent().iter(prompt) as agent_run:
            await session._stream_agent_run(agent_run, "have a look at this", [], TurnTimeline())

        assert _sent_events(session)[0] == (
            "user_prompt_processed",
            {"prompt": "have a look at this"},
        )


class TestForwardingToolEvents:
    """What a tool call looks like on the wire, read off real event objects.

    Constructed from `pydantic_ai.messages` rather than mocked, deliberately: a
    `MagicMock` answers to `.result`, `.part` and anything else, so a test built on
    one would have kept passing through exactly the rename that broke this.
    """

    async def test_a_tool_result_is_forwarded_with_its_content(self):
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

        await session._stream_tool_events(_events(), collected, TurnTimeline())

        assert [event for event in _sent_events(session) if event[0] == "tool_result"] == [
            ("tool_result", {"tool_call_id": "t1", "content": "wrote /a.txt"})
        ]

    async def test_the_result_is_kept_on_the_call_it_belongs_to(self):
        """The transcript persists one row per call, so a result that did not find
        its call is a tool call recorded as never having returned."""
        session = _session()
        collected: list[dict] = []

        async def _events():
            yield FunctionToolCallEvent(
                part=ToolCallPart(tool_name="ls", args={}, tool_call_id="t1")
            )
            yield FunctionToolResultEvent(
                part=ToolReturnPart(tool_name="ls", content=["/a.txt"], tool_call_id="t1")
            )

        await session._stream_tool_events(_events(), collected, TurnTimeline())

        assert collected == [
            {"tool_call_id": "t1", "tool_name": "ls", "args": {}, "result": "['/a.txt']"}
        ]

    async def test_a_retry_is_reported_rather_than_swallowed(self):
        """A tool that raised sends a `RetryPromptPart` down the same stream. It
        carries `content` too, and a card that never resolved would spin forever."""
        session = _session()

        async def _events():
            yield FunctionToolResultEvent(
                part=RetryPromptPart(content="path must be absolute", tool_call_id="t9")
            )

        await session._stream_tool_events(_events(), [], TurnTimeline())

        [(_type, data)] = [event for event in _sent_events(session) if event[0] == "tool_result"]
        assert data == {"tool_call_id": "t9", "content": "path must be absolute"}

    async def test_the_models_submit_final_answer_call_is_not_drawn_as_a_tool(self):
        """`OutputToolCallEvent` arrives on this same stream and shares a base class
        with the function-tool event. Matching the base would put a card named
        after the output schema in every turn, and persist one per message."""
        session = _session()
        collected: list[dict] = []

        async def _events():
            yield OutputToolCallEvent(
                part=ToolCallPart(
                    tool_name="final_result", args={"output": "Two"}, tool_call_id="o1"
                )
            )

        await session._stream_tool_events(_events(), collected, TurnTimeline())

        assert _sent_events(session) == []
        assert collected == []


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
                    # On the wire even when it is `None`, because the client
                    # switches on its presence to nest a panel: a field a surface
                    # only sometimes receives is a field it has to guess about, and
                    # guessing the parent is what this replaced.
                    "parent_task_id": None,
                    # `None` for a configured delegate; set only for a specialist the
                    # model invented at run time, whose definition a surface offers to
                    # keep. On the wire either way, for the same reason.
                    "specialist": None,
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
    request - through `book`, as the guard does, because that is where the entry is
    stamped with the delegation that made it. It happens *before* the sleep, and
    `spent` is what a test waits on rather than a delay: the assertion is about
    what a cancelled run reports having spent, so the money has to be on the
    ledger before the stop arrives.
    """

    async def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        ledger.book(_DELEGATE_REQUEST)
        spent.set()
        await anyio.sleep(30)
        return ModelResponse(parts=[TextPart("too late")])

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        ledger.book(_DELEGATE_REQUEST)
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

    def __init__(self, mode: str = "async") -> None:
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
            [CapabilityBinding(capability_id="subagents", config={"mode": mode})],
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

    def _prepared(self, agent: PydanticAgent[Any, Any]) -> PreparedRun:
        """A real `PreparedRun`: `iterate` is what meters the turn, so a mock of
        the prepared run would never reach the agent this class assembled."""
        built = MagicMock()
        built.agent = agent
        built.ledger = self.ledger
        built.model_label = "gpt-4.1"
        built.deps = AgentDeps(organization_id=uuid4(), run_id=uuid4())
        # Real `None` rather than a mock: Pydantic AI reads this per request.
        built.usage_limits = None
        return PreparedRun(
            run=MagicMock(id=uuid4(), agent_version_id=uuid4()),
            agent=MagicMock(id=uuid4()),
            spec=MagicMock(budget=None),
            built=built,
            approvals=MagicMock(parked={}, requested=[]),
        )

    @contextmanager
    def patched(self) -> Iterator[None]:
        """Everything between the frame and the agent that needs a database."""
        with (
            patch("app.services.agent_session.persist_user_turn", new=AsyncMock()) as persist,
            patch("app.services.agent_session.get_db_context") as db_context,
            patch("app.services.agent_chat.member_repo") as members,
            patch("app.services.agent_chat.AgentRunnerService") as runner_cls,
        ):
            persist.return_value = PersistedPrompt(
                conversation_id=_CONVERSATION, newly_created=False
            )
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
    """`stop` while a delegation is running, through the real teardown.

    One scenario, four assertions, because the failures are independent: a leaked
    task keeps spending against a closed session, a missing terminal frame leaves
    the client's spinner running forever, an unrecorded delegation loses its cost,
    and a run row written as if nothing was spent is a bill nobody can explain.

    Both modes, because the library covers neither of them the same way and
    covered `sync` - **the default** - not at all: a sync delegation has a handle
    and no task, so `TaskManager.cancel_all` never sees it, and
    `asyncio.CancelledError` is a `BaseException`, so `_run_sync`'s handlers never
    see it either.
    """

    async def test_a_stopped_sync_delegation_is_cancelled_rather_than_left_running(self):
        """The default mode, stopped mid-delegation.

        Every failure this class exists for at once, and none of them raises: the
        handle stayed `RUNNING`, so the delegation was filed as still going, its
        two dollars were attributed to nothing, the fan-out slot was never
        released, and the panel the client had opened was never closed.
        """
        turn = _Turn(mode="sync")
        session = _session()
        alive_before = len(asyncio.all_tasks())

        with turn.patched():
            await session.handle_frame({"message": "price this up", "agent_id": str(uuid4())})
            await turn.in_flight()
            assert turn.delegation.journal.in_flight() == 1

            await session.handle_frame({"type": "stop"})

        journal = turn.delegation.journal
        # A sync delegation has no asyncio task of its own, so the handle is the
        # only place its status lives - and it is what decides whether the
        # delegation is ever recorded.
        assert [handle.status for handle in journal.tasks.list_handles()] == [TaskStatus.CANCELLED]
        assert journal.in_flight() == 0
        assert len(asyncio.all_tasks()) == alive_before
        assert session._turn_task is None

        assert _sent_events(session)[-1] == (
            "complete",
            {"conversation_id": _CONVERSATION, "stopped": True},
        )
        assert [
            event_type for event_type, _data in _sent_events(session) if "subagent" in event_type
        ] == ["subagent_start", "subagent_complete"]

        # What the ledger accumulated while the delegate was running, on the
        # delegation's own record and on the run row.
        (outcome,) = turn.outcomes
        assert outcome.status == "cancelled"
        assert outcome.cost_usd == _DELEGATE_REQUEST.cost_usd
        assert turn.finished == [(RunStatus.CANCELLED, _DELEGATE_REQUEST.cost_usd, 7, 3)]

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
