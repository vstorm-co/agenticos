"""Durable question answers continue on a socket that can still serve delegates."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import anyio
import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

from app.agents.ask_user import QuestionItem, park_the_question
from app.agents.capabilities import CapabilityBinding, build, load_builtins
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from app.core.permissions import OrgRoleName
from app.schemas.agent import ParkedQuestion
from app.services.agent_runner import AgentRunnerService, LiveRunSurface, RunSegment
from app.services.agent_session import AgentSession
from tests.test_agent_runner import _ctx, _db, _parked_run, _prepared
from tests.test_agent_session import _CONVERSATION, _frame_types, _sent_events, _session
from tests.test_subagents_capability import a_capability, a_delegate, a_runtime, asking

pytestmark = pytest.mark.anyio


def _run(session: AgentSession) -> SimpleNamespace:
    session._room = _CONVERSATION
    return SimpleNamespace(
        id=uuid4(),
        conversation_id=UUID(_CONVERSATION),
        user_id=session.user.id,
        organization_id=session.organization_id,
        agent_id=uuid4(),
        agent_version_id=uuid4(),
        model_label="test",
        surface="web",
        status="awaiting_answer",
        cost_usd=Decimal("0"),
        cost_is_partial=False,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )


def _request(run: SimpleNamespace, request_id: str = "answer-1") -> dict[str, object]:
    return {
        "type": "answer_run",
        "request_id": request_id,
        "run_id": str(run.id),
        "responses": {"main-q": [{"selected": ["Casual"]}]},
    }


@contextmanager
def _continuation(session: AgentSession, run: SimpleNamespace) -> Iterator[SimpleNamespace]:
    runner = MagicMock()
    runner.get_run = AsyncMock(return_value=run)
    runner.parked_calls = AsyncMock(return_value=[])
    runner.parked_questions = AsyncMock(return_value=[])

    async def answered(*_args: object, **_kwargs: object) -> RunSegment:
        run.status = "completed"
        return RunSegment(output="done", run=run, tool_calls=[], settled={})

    async def cancelled(*_args: object, **_kwargs: object) -> None:
        run.status = "cancelled"

    runner.answer = AsyncMock(side_effect=answered)
    runner.cancel_parked = AsyncMock(side_effect=cancelled)
    membership = AsyncMock(return_value=SimpleNamespace(role=OrgRoleName.MEMBER))
    conversation = MagicMock(get_conversation=AsyncMock())
    admitted = SimpleNamespace(open=False)

    @asynccontextmanager
    async def db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    @asynccontextmanager
    async def claim(*_args: object, **_kwargs: object) -> AsyncIterator[bool]:
        admitted.open = True
        try:
            yield True
        finally:
            admitted.open = False

    with (
        patch("app.services.agent_session.get_db_context", db),
        patch("app.services.agent_session.AgentRunnerService", return_value=runner),
        patch("app.services.agent_session.member_repo.get", membership),
        patch("app.services.agent_session.ConversationService", return_value=conversation),
        patch("app.services.conversation_turns.claim", claim),
        patch.object(session, "_stop_following", new=AsyncMock()),
        patch.object(session, "_follow_if_running", new=AsyncMock()),
        patch.object(session, "_leave_room", new=AsyncMock()),
        patch.object(session, "_tell_the_absent", new=AsyncMock()),
    ):
        yield SimpleNamespace(
            runner=runner, membership=membership, conversation=conversation, admitted=admitted
        )


async def _finish(
    session: AgentSession, run: SimpleNamespace, request_id: str = "answer-1"
) -> None:
    await session.handle_frame(_request(run, request_id))
    task = session._turn_task
    assert task is not None
    with anyio.fail_after(5):
        await task


@pytest.mark.parametrize("model_label", ["test", None])
async def test_a_socket_answer_returns_its_result_and_releases_admission_before_ready(
    model_label: str | None,
) -> None:
    session = _session()
    run = _run(session)
    run.model_label = model_label
    with _continuation(session, run) as fake:
        original = session._emit

        async def emit(kind: str, payload: Any) -> bool:
            if kind == "session_ready":
                assert not fake.admitted.open
                assert session._turn_task is None
            return await original(kind, payload)

        with patch.object(session, "_emit", side_effect=emit):
            await _finish(session, run)

    [(_, reply), (_, ready)] = _sent_events(session)
    assert reply["request_id"] == "answer-1"
    assert reply["result"]["run_id"] == str(run.id)
    assert reply["result"]["output"] == "done"
    assert ready["conversation_id"] == _CONVERSATION
    assert isinstance(fake.runner.answer.await_args.kwargs["live_surface"], LiveRunSurface)


async def test_owner_progress_is_sent_without_publishing_a_second_trace() -> None:
    session = _session()
    with patch("app.services.agent_session.live_turn.publish", new=AsyncMock()) as publish:
        await session._resume_frame("text_delta", {"content": "answer"})
    assert _sent_events(session) == [("text_delta", {"content": "answer"})]
    publish.assert_not_awaited()


@pytest.mark.parametrize("saved_status", ["running", "completed"])
async def test_a_resume_cancellation_only_finishes_a_run_still_running(saved_status: str) -> None:
    service = AgentRunnerService(_db())
    ctx = _ctx()
    run = _parked_run(user_id=ctx.user_id, paused_state={"messages": [], "tool_call_ids": {}})
    prepared = _prepared()
    prepared.run = run

    async def interrupted(*_args: object, **_kwargs: object) -> None:
        run.status = saved_status
        raise asyncio.CancelledError

    with (
        patch(
            "app.services.agent_runner.agent_run_repo.claim_parked_run", AsyncMock(return_value=run)
        ),
        patch(
            "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            service, "_parked_spec", AsyncMock(return_value=(MagicMock(), AgentSpec(name="Clerk")))
        ),
        patch.object(service, "_assemble", AsyncMock(return_value=prepared)),
        patch.object(service, "_run", AsyncMock(side_effect=interrupted)),
        patch.object(service, "finish", AsyncMock()) as finish,
        pytest.raises(asyncio.CancelledError),
    ):
        await service.resume(ctx, run.id)

    assert finish.await_count == (1 if saved_status == "running" else 0)


async def test_an_http_continuation_still_publishes_its_shared_trace() -> None:
    prepared = _prepared(conversation_id=uuid4())
    prepared.run.surface = "web"
    prepared.run.user_id = uuid4()
    turn = object()
    with (
        patch("app.services.live_turn.begin", AsyncMock(return_value=turn)),
        patch("app.services.live_turn.publish", AsyncMock()) as publish,
        patch("app.services.live_turn.end", AsyncMock()) as end,
        patch("app.services.chat_room.turn_begun", AsyncMock()),
    ):
        async with AgentRunnerService(_db())._resume_stream(prepared) as frames:
            assert frames is not None
            await frames.emit("text_delta", {"content": "continued"})
    assert [call.args[1] for call in publish.await_args_list] == [
        "background_task_turn",
        "model_request_start",
        "text_delta",
    ]
    end.assert_awaited_once_with(turn)


@pytest.mark.security
@pytest.mark.parametrize(
    "refusal", ["member", "owner", "surface", "room", "status", "access", "tenant"]
)
async def test_a_socket_answer_refuses_invalid_authority_or_room(refusal: str) -> None:
    session = _session()
    run = _run(session)
    with _continuation(session, run) as fake:
        if refusal == "member":
            fake.membership.return_value = None
        elif refusal == "owner":
            run.user_id = uuid4()
        elif refusal == "surface":
            run.surface = "api"
        elif refusal == "room":
            session._room = str(uuid4())
        elif refusal == "status":
            run.status = "completed"
        elif refusal == "access":
            fake.conversation.get_conversation.side_effect = AuthorizationError(message="No access")
        else:
            fake.runner.get_run.side_effect = NotFoundError(message="Run not found")
        await _finish(session, run)

    reply = _sent_events(session)[0][1]
    assert reply["request_id"] == "answer-1"
    assert reply["error"]["status"] in (400, 403, 404)
    fake.runner.answer.assert_not_awaited()
    fake.runner.cancel_parked.assert_not_awaited()


@pytest.mark.security
async def test_a_revoked_socket_cannot_answer_a_run() -> None:
    session = _session()
    session._auth_token = "revoked"
    session.websocket.close = AsyncMock()
    run = _run(session)
    with (
        _continuation(session, run) as fake,
        patch(
            "app.services.agent_session.authenticate_socket_token",
            new=AsyncMock(side_effect=AuthenticationError()),
        ),
    ):
        await session.handle_frame(_request(run))
    fake.runner.answer.assert_not_awaited()
    session.websocket.close.assert_awaited_once()


async def test_a_busy_answer_is_correlated_without_advertising_readiness() -> None:
    session = _session()
    run = _run(session)
    task = asyncio.create_task(asyncio.Event().wait())
    session._turn_task = task
    try:
        await session.handle_frame(_request(run))
        assert session._turn_task is task
        [(kind, reply)] = _sent_events(session)
        assert kind == "run_answer_result"
        assert reply["error"]["status"] == 409
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("request_id", [None, "", 7, "x" * 129])
async def test_an_uncorrelatable_answer_is_ignored(request_id: object) -> None:
    session = _session()
    run = _run(session)
    frame = _request(run)
    frame["request_id"] = request_id
    await session.handle_frame(frame)
    assert _sent_events(session) == []


async def test_a_malformed_answer_is_correlated_and_leaves_the_socket_ready() -> None:
    session = _session()
    await session.handle_frame({"type": "answer_run", "request_id": "bad", "run_id": "not-a-uuid"})
    assert _frame_types(session) == ["run_answer_result", "session_ready"]
    assert _sent_events(session)[0][1]["error"]["status"] == 400


async def test_an_unexpected_continuation_failure_keeps_server_details_off_the_wire() -> None:
    session = _session()
    run = _run(session)
    with _continuation(session, run) as fake:
        fake.runner.answer.side_effect = RuntimeError("https://internal?key=secret")
        await _finish(session, run)
    reply = _sent_events(session)[0][1]
    assert reply["error"]["status"] == 500
    assert "secret" not in str(reply)


@pytest.mark.security
async def test_stop_before_execution_closes_the_authorized_parked_run() -> None:
    session = _session()
    run = _run(session)
    entered = asyncio.Event()

    @asynccontextmanager
    async def waiting_claim(*_args: object, **_kwargs: object) -> AsyncIterator[bool]:
        entered.set()
        await asyncio.Event().wait()
        yield True

    with (
        _continuation(session, run) as fake,
        patch("app.services.conversation_turns.claim", waiting_claim),
    ):
        await session.handle_frame(_request(run))
        await entered.wait()
        assert session._live == _CONVERSATION
        session._stop_following.assert_awaited_once()
        await session.handle_frame({"type": "stop"})
    fake.runner.answer.assert_not_awaited()
    fake.runner.cancel_parked.assert_awaited_once()
    reply = _sent_events(session)[0][1]
    assert reply["error"]["details"]["status"] == "cancelled"


async def test_stop_after_terminal_commit_reports_the_completed_state() -> None:
    session = _session()
    run = _run(session)
    entered = asyncio.Event()

    async def delayed_result(*_args: object, **_kwargs: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    with (
        _continuation(session, run) as fake,
        patch("app.services.agent_session.run_result", side_effect=delayed_result),
    ):
        await session.handle_frame(_request(run))
        await entered.wait()
        await session.handle_frame({"type": "stop"})
    fake.runner.cancel_parked.assert_not_awaited()
    assert _sent_events(session)[0][1]["error"]["details"]["status"] == "completed"


@pytest.mark.security
async def test_stop_during_authorization_never_cancels_an_unchecked_run() -> None:
    session = _session()
    run = _run(session)
    entered = asyncio.Event()

    async def checking(*_args: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    with (
        _continuation(session, run) as fake,
        patch.object(session, "_answer_context", side_effect=checking),
    ):
        await session.handle_frame(_request(run))
        await entered.wait()
        await session.handle_frame({"type": "stop"})
    fake.runner.cancel_parked.assert_not_awaited()
    assert "status" not in _sent_events(session)[0][1]["error"]["details"]


async def test_an_unavailable_saved_status_is_reported_without_inventing_cancellation() -> None:
    session = _session()
    run = _run(session)
    entered = asyncio.Event()

    async def waiting(*_args: object, **_kwargs: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    with _continuation(session, run) as fake:
        fake.runner.answer.side_effect = waiting
        fake.runner.get_run.side_effect = [run, RuntimeError("database unavailable")]
        await session.handle_frame(_request(run))
        await entered.wait()
        await session.handle_frame({"type": "stop"})
    assert "status" not in _sent_events(session)[0][1]["error"]["details"]


async def test_a_second_main_question_remains_answerable_on_the_same_run() -> None:
    session = _session()
    run = _run(session)
    next_question = ParkedQuestion(
        tool_call_id="next-q", questions=[QuestionItem(question="Which size?")]
    )
    with _continuation(session, run) as fake:
        fake.runner.answer.side_effect = None
        fake.runner.answer.return_value = RunSegment(output="", run=run, tool_calls=[], settled={})
        fake.runner.parked_questions.return_value = [next_question]
        await _finish(session, run)
        first_reply = _sent_events(session)[0][1]
        assert first_reply["result"]["questions"][0]["tool_call_id"] == "next-q"
        assert session._turn_task is None
        fake.runner.parked_questions.return_value = []
        run.status = "awaiting_answer"

        async def completed(*_args: object, **_kwargs: object) -> RunSegment:
            run.status = "completed"
            return RunSegment(output="large", run=run, tool_calls=[], settled={})

        fake.runner.answer.side_effect = completed
        frame = _request(run, "answer-2")
        frame["responses"] = {"next-q": [{"answer": "large"}]}
        await session.handle_frame(frame)
        await session._turn_task
    replies = [data for kind, data in _sent_events(session) if kind == "run_answer_result"]
    assert [reply["request_id"] for reply in replies] == ["answer-1", "answer-2"]
    assert replies[-1]["result"]["run_id"] == str(run.id)
    assert replies[-1]["result"]["output"] == "large"


async def test_a_delegate_question_is_released_when_the_conversation_is_left() -> None:
    session = _session()
    run = _run(session)
    asked = asyncio.Event()

    async def answer(*_args: object, live_surface: LiveRunSurface, **_kwargs: object) -> RunSegment:
        asked.set()
        result = await live_surface.ask_user("Which currency?", [])
        run.status = "completed"
        return RunSegment(output=result, run=run, tool_calls=[], settled={})

    with _continuation(session, run) as fake:
        fake.runner.answer.side_effect = answer
        await session.handle_frame(_request(run))
        task = session._turn_task
        await asked.wait()
        await session._attach(None)
        await task
    assert session._ask_user_future is None
    reply = next(data for kind, data in _sent_events(session) if kind == "run_answer_result")
    assert reply["result"]["output"] == "(no answer)"


async def test_disconnecting_releases_a_delegates_live_question() -> None:
    session = _session()
    run = _run(session)
    asked = asyncio.Event()

    async def answer(*_args: object, live_surface: LiveRunSurface, **_kwargs: object) -> RunSegment:
        asked.set()
        result = await live_surface.ask_user("Which currency?", [])
        run.status = "completed"
        return RunSegment(output=result, run=run, tool_calls=[], settled={})

    with _continuation(session, run) as fake:
        fake.runner.answer.side_effect = answer
        await session.handle_frame(_request(run))
        await asked.wait()
        await session.shutdown()
    assert session._ask_user_future is None
    reply = next(data for kind, data in _sent_events(session) if kind == "run_answer_result")
    assert reply["result"]["output"] == "(no answer)"


@pytest.mark.parametrize("batch", [False, True])
async def test_a_main_answer_then_a_real_delegates_question_uses_the_same_socket(
    batch: bool,
) -> None:
    session = _session()
    run = _run(session)
    load_builtins()
    question = {
        "header": "Tone",
        "question": "How formal?",
        "options": [{"label": "Formal"}, {"label": "Casual"}],
    }

    async def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        returned = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returned:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "ask_user_question", {"questions": [question]}, tool_call_id="main-q"
                    )
                ]
            )
        if returned[-1].tool_name == "ask_user_question":
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "task",
                        {"subagent_type": "researcher", "description": "Research a price"},
                        tool_call_id="task-1",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(str(returned[-1].content))])

    delegate = a_delegate(model=asking("Which currency?"))
    if batch:

        async def child_model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            returned = [
                part
                for message in messages
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            ]
            if returned:
                return ModelResponse(parts=[TextPart(str(returned[-1].content))])
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "ask_user_question", {"questions": [question]}, tool_call_id="child-q"
                    )
                ]
            )

        delegate = replace(
            delegate,
            build=lambda: Agent(
                FunctionModel(child_model),
                deps_type=AgentDeps,
                capabilities=build([CapabilityBinding(capability_id="ask_user")]),
                output_type=[str, DeferredToolRequests],
            ),
        )

    agent = Agent(
        FunctionModel(model),
        deps_type=AgentDeps,
        capabilities=[
            *build([CapabilityBinding(capability_id="ask_user")]),
            a_capability(a_runtime(delegate), {"allow_questions": True}),
        ],
        output_type=[str, DeferredToolRequests],
    )
    first = await agent.run("Find a price", deps=AgentDeps(ask_questions=park_the_question))
    assert isinstance(first.output, DeferredToolRequests)

    async def answer(*_args: object, live_surface: LiveRunSurface, **_kwargs: object) -> RunSegment:
        result = await agent.run(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(calls={"main-q": {"Tone": ["Casual"]}}),
            deps=AgentDeps(
                ask_user=live_surface.ask_user, ask_questions=live_surface.ask_questions
            ),
        )
        run.status = "completed"
        return RunSegment(output=str(result.output), run=run, tool_calls=[], settled={})

    asked = asyncio.Event()
    original = session._emit

    async def emit(kind: str, payload: Any) -> bool:
        sent = await original(kind, payload)
        if kind == "ask_user":
            asked.set()
        return sent

    with _continuation(session, run) as fake, patch.object(session, "_emit", side_effect=emit):
        fake.runner.answer.side_effect = answer
        await session.handle_frame(_request(run))
        task = session._turn_task
        with anyio.fail_after(5):
            await asked.wait()
            await session.handle_frame(
                {
                    "type": "ask_user_response",
                    "answers": [{"selected": ["Casual"]}] if batch else [{"answer": "euros"}],
                }
            )
            await task

    reply = next(data for kind, data in _sent_events(session) if kind == "run_answer_result")
    assert reply["result"]["run_id"] == str(run.id)
    assert ("Casual" if batch else "euros") in reply["result"]["output"]
    assert "no communication channel" not in reply["result"]["output"]
