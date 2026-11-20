"""Subthreads cannot inherit another discussion's working state or resume scope."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai_harness.planning import PlanItem

from app.agents.capabilities.budget import SpendLedger
from app.agents.capabilities.planning import PLANNING_STORE_RESOURCE
from app.agents.capabilities.system_reminders._capability import ReminderState
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.agents.subagent_events import SubagentTextDelta
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.locks import LockScope
from app.db.models.agent import AgentKind
from app.db.models.agent_run import RunStatus, RunSurface
from app.services import live_turn
from app.services.agent_runner import AgentRunnerService, LiveRunSurface, PreparedRun, RunSegment
from tests.test_agent_runner import (
    _ctx,
    _db,
    _history_provenance,
    _parked_run,
    _prepared,
    _resolved_model,
)
from tests.test_agent_session import _sent_events, _session

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def no_external_account_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.agent_runner.user_repo.get_by_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "app.services.agent_registry.mcp_connection_repo.list_composio_for_user",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.channel_actions.agent_exposure_repo.list_for_agent",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.agent_runner.group_repo.names_for_member", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "app.services.agent_runner.group_repo.capped_groups_for_member", AsyncMock(return_value=[])
    )


@contextmanager
def build_inputs(service: AgentRunnerService, ctx: AuthContext) -> Iterator[SimpleNamespace]:
    agent = MagicMock(id=uuid4(), current_version_id=uuid4(), kind=AgentKind.AGENT.value)
    spec = AgentSpec(name="Room responder", model_profile_id=uuid4())
    conversation = SimpleNamespace(
        organization_id=ctx.organization_id,
        project_id=None,
        overhead_tokens=3865,
        reminder_state={"request_count": 9, "fire_counts": {"goal": 2}},
        plan_items=[{"id": "main", "content": "Working plan in main", "status": "in_progress"}],
    )
    with (
        patch.object(
            service.registry,
            "get_runnable_spec",
            AsyncMock(return_value=(agent, spec, agent.current_version_id)),
        ),
        patch.object(service.models, "resolve", AsyncMock(return_value=_resolved_model("test"))),
        patch.object(service.skills, "resolve_for_agent", AsyncMock(return_value=[])),
        patch(
            "app.services.agent_runner.agent_run_repo.create_run",
            AsyncMock(return_value=MagicMock(id=uuid4())),
        ),
        patch(
            "app.services.agent_runner.conversation_share_repo.get_shares_for_conversation",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.agent_runner.conversation_repo.get_conversation_by_id",
            AsyncMock(return_value=conversation),
        ),
        patch("app.services.agent_runner.build_agent") as build,
    ):
        build.return_value.ledger = SpendLedger()
        yield SimpleNamespace(agent=agent, spec=spec, conversation=conversation, build=build)


@pytest.mark.parametrize("in_thread", [False, True])
async def test_fresh_subthread_does_not_inherit_room_plan_reminder_or_overhead(
    in_thread: bool,
) -> None:
    service = AgentRunnerService(_db())
    ctx = _ctx()
    conversation_id = uuid4()
    root = uuid4() if in_thread else None
    room_key = f"room:project:{conversation_id}"
    with build_inputs(service, ctx) as given:
        prepared = await service.prepare(
            ctx,
            given.agent.id,
            conversation_id=conversation_id,
            memory_room_key=room_key,
            thread_root_message_id=root,
        )
    assert prepared.admitted_as.thread_root_message_id == root
    assert prepared.admitted_as.audience_room_key == room_key
    assert [item.content for item in await prepared.plan_store.get_items()] == (
        [] if in_thread else ["Working plan in main"]
    )
    assert given.build.call_args.kwargs["recorded_overhead"] == (None if in_thread else 3865)
    assert given.build.call_args.kwargs["recorded_reminder_state"] == (
        None if in_thread else given.conversation.reminder_state
    )


def conversation_store() -> tuple[SimpleNamespace, dict[str, object]]:
    stored: dict[str, object] = {
        "summary": "original main summary",
        "overhead": 100,
        "reminder": {"request_count": 8},
        "plan": [{"id": "main", "content": "Main plan", "status": "pending"}],
    }

    def setter(key: str) -> AsyncMock:
        async def save(_conversation_id: UUID, value: object, **_kwargs: object) -> None:
            stored[key] = value

        return AsyncMock(side_effect=save)

    return SimpleNamespace(
        keep_summary=setter("summary"),
        keep_overhead=setter("overhead"),
        keep_reminder_state=setter("reminder"),
        keep_plan=setter("plan"),
        history_for_provenance=AsyncMock(side_effect=lambda history, _provenance: history),
    ), stored


@pytest.mark.parametrize("in_thread", [False, True])
async def test_finished_subthread_does_not_replace_room_continuation_state(in_thread: bool) -> None:
    service = AgentRunnerService(_db())
    prepared = _prepared(conversation_id=uuid4())
    root = uuid4() if in_thread else None
    prepared.admitted_as.thread_root_message_id = root
    await prepared.plan_store.set_items([PlanItem(content="Work only for this request")])
    prepared.built.context.summarized = True
    prepared.built.context.overhead = 777
    prepared.built.reminder_state = ReminderState(request_count=3)
    prepared.built.capabilities = ()
    result = MagicMock(output="done")
    result.all_messages.return_value = [ModelResponse(parts=[TextPart("This request's summary")])]
    result.new_messages.return_value = []
    prepared.built.agent.run = AsyncMock(return_value=result)
    conversations, stored = conversation_store()
    original = dict(stored)
    with (
        patch.object(service, "prepare", AsyncMock(return_value=prepared)),
        patch("app.services.agent_runner.agent_run_repo.finish_run", AsyncMock()),
        patch.object(service.transcript, "record", AsyncMock()) as transcript,
        patch("app.services.agent_runner.ConversationService", return_value=conversations),
    ):
        output, _ = await service.execute(
            _ctx(), uuid4(), "Answer here", thread_root_message_id=root
        )
    assert output == "done"
    if in_thread:
        assert stored == original
    else:
        assert stored["overhead"] == 777
        assert stored["reminder"] == {"request_count": 3, "fire_counts": {}}
        assert stored["summary"] != original["summary"]
        assert stored["plan"] != original["plan"]
    assert transcript.await_args.kwargs.get("thread_root_message_id") == root


def paused_room_run(
    *, conversation_id: UUID, root: UUID, user_id: UUID, organization_id: UUID
) -> Any:
    messages = ModelMessagesTypeAdapter.dump_python(
        [ModelRequest(parts=[UserPromptPart("Continue only this subthread")])], mode="json"
    )
    return _parked_run(
        conversation_id=conversation_id,
        user_id=user_id,
        organization_id=organization_id,
        paused_state={
            "messages": messages,
            "tool_call_ids": {},
            "plan": [{"id": "own", "content": "Resume my own plan", "status": "in_progress"}],
            "admitted_as": {
                "audience_room_key": f"room:project:{conversation_id}",
                "thread_root_message_id": str(root),
            },
        },
    )


async def test_subthread_resume_keeps_saved_messages_and_plan_on_original_room_audience() -> None:
    ctx = _ctx()
    assert ctx.user_id is not None
    conversation_id, root = uuid4(), uuid4()
    run = paused_room_run(
        conversation_id=conversation_id,
        root=root,
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
    )
    service = AgentRunnerService(_db())
    captured: dict[str, object] = {}

    async def segment(prepared: PreparedRun, **kwargs: Any) -> RunSegment:
        captured["prepared"] = prepared
        captured["history"] = ModelMessagesTypeAdapter.dump_python(
            kwargs["message_history"], mode="json"
        )
        captured["plan"] = [item.content for item in await prepared.plan_store.get_items()]
        return RunSegment(output="continued", run=run, tool_calls=[], settled={})

    with (
        build_inputs(service, ctx) as given,
        patch(
            "app.services.agent_runner.agent_run_repo.claim_parked_run", AsyncMock(return_value=run)
        ),
        patch(
            "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
            AsyncMock(return_value=[]),
        ),
        patch("app.services.agent_runner.agent_run_repo.mark_running", AsyncMock()),
        patch(
            "app.services.agent_runner.conversation_repo.room_thread_for_run",
            AsyncMock(return_value=root),
        ),
        patch(
            "app.services.agent_runner.conversation_repo.has_imported_thread_context",
            AsyncMock(return_value=False),
        ),
        patch(
            "app.services.agent_runner.room_thread_repo.get_thread",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.room_submission.RoomSubmissionService.resume_authority",
            AsyncMock(return_value=ctx),
        ),
        patch.object(service, "_parked_spec", AsyncMock(return_value=(given.agent, given.spec))),
        patch.object(service, "_run", AsyncMock(side_effect=segment)),
        # Provenance matching has its own tests; this one is about the saved scope.
        patch("app.services.agent_runner._require_history_provenance"),
    ):
        given.agent.id = run.agent_id
        given.agent.current_version_id = run.agent_version_id
        run.paused_state["history_provenance"] = _history_provenance(
            run.agent_id, given.spec, _resolved_model("test"), ctx.user_id
        ).model_dump(mode="json")
        result = await service.resume(ctx, run.id)
    assert result.output == "continued"
    assert captured["plan"] == ["Resume my own plan"]
    assert captured["history"] == run.paused_state["messages"]
    prepared = captured["prepared"]
    assert isinstance(prepared, PreparedRun)
    assert prepared.admitted_as.thread_root_message_id == root
    assert prepared.admitted_as.audience_room_key == f"room:project:{conversation_id}"
    store = given.build.call_args.kwargs["resources"][PLANNING_STORE_RESOURCE]
    assert [item.content for item in await store.get_items()] == ["Resume my own plan"]
    assert given.build.call_args.kwargs["recorded_overhead"] is None
    assert given.build.call_args.kwargs["recorded_reminder_state"] is None


@pytest.mark.security
async def test_thread_scope_does_not_bypass_parked_requester_authority() -> None:
    ctx = _ctx()
    assert ctx.user_id is not None
    conversation_id, root = uuid4(), uuid4()
    run = paused_room_run(
        conversation_id=conversation_id,
        root=root,
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
    )
    service = AgentRunnerService(_db())
    with (
        patch(
            "app.services.agent_runner.agent_run_repo.claim_parked_run", AsyncMock(return_value=run)
        ),
        patch(
            "app.services.agent_runner.conversation_repo.room_thread_for_run",
            AsyncMock(return_value=root),
        ),
        patch(
            "app.services.room_submission.RoomSubmissionService.resume_authority",
            AsyncMock(side_effect=AuthorizationError(message="Requester lost room access")),
        ),
        patch.object(
            service,
            "_assemble",
            AsyncMock(side_effect=AssertionError("A refused run must not build")),
        ),
        pytest.raises(AuthorizationError, match="Requester lost room access"),
    ):
        await service.resume(ctx, run.id)


@pytest.mark.security
@pytest.mark.parametrize("missing", [False, True])
async def test_a_parked_thread_cannot_resume_against_a_different_saved_request(
    missing: bool,
) -> None:
    ctx = _ctx()
    assert ctx.user_id is not None
    conversation_id, root = uuid4(), uuid4()
    run = paused_room_run(
        conversation_id=conversation_id,
        root=root,
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
    )
    service = AgentRunnerService(_db())
    with (
        patch(
            "app.services.agent_runner.agent_run_repo.claim_parked_run", AsyncMock(return_value=run)
        ),
        patch(
            "app.services.agent_runner.conversation_repo.room_thread_for_run",
            AsyncMock(return_value=None if missing else uuid4()),
        ),
        patch(
            "app.services.room_submission.RoomSubmissionService.resume_authority",
            AsyncMock(return_value=ctx),
        ),
        patch.object(
            service,
            "_assemble",
            AsyncMock(side_effect=AssertionError("Changed scope must not build")),
        ),
        pytest.raises(BadRequestError, match="changed its subthread"),
    ):
        await service.resume(ctx, run.id)


@pytest.mark.parametrize("in_thread", [False, True])
async def test_closing_parked_subthread_does_not_put_its_plan_in_main(in_thread: bool) -> None:
    ctx = _ctx()
    root = uuid4() if in_thread else None
    run = _parked_run(
        conversation_id=uuid4(),
        organization_id=ctx.organization_id,
        paused_state={
            "messages": [],
            "tool_call_ids": {},
            "plan": [{"id": "own", "content": "Cancelled thread plan", "status": "in_progress"}],
            "admitted_as": {"thread_root_message_id": str(root) if root else None},
        },
    )
    service = AgentRunnerService(_db())
    conversations, stored = conversation_store()
    original = dict(stored)
    with (
        patch.object(service, "_cancel_delegations", AsyncMock()),
        patch.object(service.transcript, "record", AsyncMock()) as transcript,
        patch("app.services.agent_runner.agent_run_repo.expire_pending_approvals", AsyncMock()),
        patch("app.services.agent_runner.agent_run_repo.finish_run", AsyncMock()),
        patch("app.services.agent_runner.ConversationService", return_value=conversations),
    ):
        status = await service._close_parked(run, actor_user_id=ctx.user_id)
    assert status == RunStatus.AWAITING_APPROVAL.value
    if in_thread:
        assert stored == original
    else:
        assert stored["plan"] == [
            {"id": "own", "content": "Cancelled thread plan", "status": "pending"}
        ]
    assert transcript.await_args.kwargs.get("thread_root_message_id") == root


@pytest.mark.security
async def test_delayed_first_thread_frame_discloses_nothing_after_authority_expires() -> None:
    session = _session()
    conversation_id, root = str(uuid4()), str(uuid4())

    async def delayed(_conversation_id: str, _token: str) -> AsyncIterator[dict[str, Any]]:
        yield {
            "seq": 1,
            "type": "text_delta",
            "data": {
                "conversation_id": conversation_id,
                "thread_root_message_id": root,
                "content": "No longer authorized to read this reply",
            },
        }

    clock = iter([0.0, 31.0])
    with (
        patch.object(live_turn, "follow", delayed),
        patch("app.services.agent_session.time", SimpleNamespace(monotonic=lambda: next(clock))),
        patch.object(session, "_still_reads", AsyncMock(return_value=False)),
    ):
        continuing = await session._follow_one(conversation_id, "thread-token")
    assert not continuing
    assert _sent_events(session) == [(live_turn.END, {"conversation_id": conversation_id})]


async def test_truncated_thread_stream_closes_without_reattaching_as_main() -> None:
    session = _session()
    conversation_id, root = str(uuid4()), str(uuid4())
    payload = {
        "conversation_id": conversation_id,
        "thread_root_message_id": root,
        "content": "A partial thread reply",
    }

    async def truncated(_conversation_id: str, _token: str) -> AsyncIterator[dict[str, Any]]:
        yield {"seq": 1, "type": "text_delta", "data": payload}

    with (
        patch.object(live_turn, "follow", truncated),
        patch("app.services.agent_session.time", SimpleNamespace(monotonic=lambda: 0.0)),
    ):
        continuing = await session._follow_one(conversation_id, "thread-token")
    assert continuing
    assert _sent_events(session) == [
        (
            "turn_attached",
            {"conversation_id": conversation_id, "thread_root_message_id": root},
        ),
        ("text_delta", payload),
        (live_turn.END, {"conversation_id": conversation_id}),
    ]


@pytest.mark.parametrize("in_thread", [False, True])
async def test_resumed_frames_retain_server_scope_on_socket_and_shared_trace(
    in_thread: bool,
) -> None:
    prepared = _prepared(conversation_id=uuid4())
    prepared.run.surface = RunSurface.WEB.value
    prepared.run.user_id = uuid4()
    prepared.built.deps = AgentDeps()
    root = uuid4() if in_thread else None
    prepared.admitted_as.thread_root_message_id = root
    emit = AsyncMock()
    surface = LiveRunSurface(ask_user=AsyncMock(), ask_questions=AsyncMock(), emit=emit)
    turn = object()
    with (
        patch.object(live_turn, "begin", AsyncMock(return_value=turn)),
        patch.object(live_turn, "publish", AsyncMock()) as publish,
        patch.object(live_turn, "end", AsyncMock()),
        patch("app.services.chat_room.turn_begun", AsyncMock()),
    ):
        async with AgentRunnerService(_db())._resume_stream(
            prepared, live_surface=surface
        ) as frames:
            assert frames is not None
            await frames.emit(
                "text_delta",
                {
                    "content": "Continued reply",
                    "conversation_id": str(uuid4()),
                    "thread_root_message_id": str(uuid4()),
                },
            )
            assert prepared.deps.subagent_events is not None
            await prepared.deps.subagent_events(
                SubagentTextDelta(
                    task_id="child",
                    subagent="researcher",
                    depth=0,
                    delta="Found the source",
                )
            )
    delivered = [call.args for call in emit.await_args_list]
    assert [kind for kind, _payload in delivered] == [
        "background_task_turn",
        "model_request_start",
        "text_delta",
        "subagent_text_delta",
    ]
    assert all(
        payload["conversation_id"] == str(prepared.run.conversation_id) for _, payload in delivered
    )
    assert all(
        payload["thread_root_message_id"] == (str(root) if root else None)
        for _, payload in delivered
    )
    assert delivered[2][1]["content"] == "Continued reply"
    assert delivered[3][1]["delta"] == "Found the source"
    assert [(call.args[1], call.args[2]) for call in publish.await_args_list] == delivered


async def test_cross_room_resume_publishes_only_status_and_saved_identifiers() -> None:
    prepared = _prepared(conversation_id=uuid4())
    prepared.run.surface = RunSurface.WEB.value
    prepared.run.user_id = uuid4()
    prepared.built.deps = AgentDeps()
    root = uuid4()
    prepared.admitted_as.thread_root_message_id = root
    emit = AsyncMock()
    surface = LiveRunSurface(ask_user=AsyncMock(), ask_questions=AsyncMock(), emit=emit)
    turn = object()
    message_id, run_id = uuid4(), prepared.run.id
    with (
        patch.object(live_turn, "begin", AsyncMock(return_value=turn)),
        patch.object(live_turn, "publish", AsyncMock()) as publish,
        patch.object(live_turn, "end", AsyncMock()),
        patch("app.services.chat_room.turn_begun", AsyncMock()),
    ):
        async with AgentRunnerService(_db())._resume_stream(
            prepared,
            live_surface=surface,
            suppress_room_payloads=True,
        ) as frames:
            assert frames is not None
            for kind, payload in (
                ("user_prompt_processed", {"prompt": "private prompt"}),
                ("text_delta", {"content": "private answer"}),
                ("tool_result", {"content": "private tool result"}),
                ("subagent_text_delta", {"delta": "private delegation"}),
                (
                    "message_saved",
                    {
                        "message_id": str(message_id),
                        "run_id": str(run_id),
                        "run_status": "completed",
                        "content": "private answer",
                    },
                ),
            ):
                await frames.emit(kind, payload)

    delivered = [call.args for call in emit.await_args_list]
    assert [kind for kind, _payload in delivered] == [
        "background_task_turn",
        "model_request_start",
        "message_saved",
    ]
    assert delivered[0][1] == {
        "agent_id": str(prepared.run.agent_id),
        "resumed_run_id": str(prepared.run.id),
        "conversation_id": str(prepared.run.conversation_id),
        "thread_root_message_id": str(root),
    }
    assert delivered[1][1] == {
        "conversation_id": str(prepared.run.conversation_id),
        "thread_root_message_id": str(root),
    }
    assert delivered[2][1] == {
        "message_id": str(message_id),
        "run_id": str(run_id),
        "run_status": "completed",
        "conversation_id": str(prepared.run.conversation_id),
        "thread_root_message_id": str(root),
    }
    assert [(call.args[1], call.args[2]) for call in publish.await_args_list] == delivered


async def test_cross_room_worker_live_suppresses_prompt_and_model_payloads() -> None:
    from app.worker.tasks.room_tasks import _live

    conversation_id, accepted_root_id, display_root_id = uuid4(), uuid4(), uuid4()
    submission = SimpleNamespace(
        conversation_id=conversation_id,
        requester_id=uuid4(),
        agent_id=uuid4(),
        thread_root_message_id=accepted_root_id,
    )
    message = SimpleNamespace(
        id=uuid4(),
        client_message_id="client-message",
        content="visible saved user prompt",
        room_mentions=[],
        files=[],
        sender=None,
        reply_to=None,
        thread_root_message_id=display_root_id,
    )
    turn = object()
    with (
        patch.object(live_turn, "begin", AsyncMock(return_value=turn)),
        patch.object(live_turn, "publish", AsyncMock()) as publish,
        patch.object(live_turn, "end", AsyncMock()),
        patch("app.services.chat_room.turn_begun", AsyncMock()),
    ):
        async with _live(submission, message, suppress_room_payloads=True) as frames:
            await frames.emit("model_request_start", {"prompt": "private prompt"})
            await frames.emit("text_delta", {"content": "private answer"})
            await frames.emit("tool_call", {"args": "private args"})
            await frames.emit(
                "message_saved",
                {
                    "message_id": str(uuid4()),
                    "run_id": str(uuid4()),
                    "run_status": "completed",
                    "content": "private answer",
                },
            )

    delivered = [call.args for call in publish.await_args_list]
    assert [kind for _turn, kind, _payload in delivered] == [
        "model_request_start",
        "message_saved",
        "complete",
    ]
    assert delivered[0][2] == {
        "conversation_id": str(conversation_id),
        "thread_root_message_id": str(accepted_root_id),
    }
    assert delivered[1][2]["run_status"] == "completed"
    assert "content" not in delivered[1][2]
    assert delivered[2][2] == {
        "conversation_id": str(conversation_id),
        "thread_root_message_id": str(accepted_root_id),
    }


async def test_cross_room_final_authority_refusal_saves_failure_without_answer() -> None:
    service = AgentRunnerService(_db())
    destination_id, source_id = uuid4(), uuid4()
    prepared = _prepared(conversation_id=destination_id)
    prepared.admitted_as.thread_root_message_id = uuid4()
    sequence: list[tuple[str, UUID | None]] = []

    async def take_lock(_db: object, scope: LockScope, conversation_id: UUID) -> None:
        assert scope is LockScope.CONVERSATION_TURN
        sequence.append(("lock", conversation_id))

    @asynccontextmanager
    async def fresh_session() -> AsyncIterator[object]:
        yield object()

    async def revoked(_db: object) -> None:
        sequence.append(("check", None))
        raise RuntimeError("private source conversation and body")

    with (
        patch.object(service, "_answer", AsyncMock(return_value=None)),
        patch.object(service, "finish", AsyncMock()) as finish,
        patch.object(service.transcript, "record", AsyncMock(return_value=None)) as record,
        patch("app.services.agent_runner.hold_subject", new=AsyncMock(side_effect=take_lock)),
        patch(
            "app.services.agent_runner.get_db_context",
            return_value=fresh_session(),
        ),
        pytest.raises(AuthorizationError) as raised,
    ):
        await service._run(
            prepared,
            user_prompt=None,
            said=None,
            message_history=None,
            deferred_tool_results=None,
            result_authority_check=revoked,
            result_context_conversation_ids=(source_id, destination_id),
        )

    expected_locks = sorted((source_id, destination_id), key=str)
    assert sequence == [("lock", expected_locks[0]), ("lock", expected_locks[1]), ("check", None)]
    assert str(raised.value) == "This room request can no longer use its selected context"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    finish.assert_awaited_once()
    assert finish.await_args.kwargs["status"] is RunStatus.FAILED
    record.assert_awaited_once()
    assert record.await_args.kwargs["answer"] == ""
    assert record.await_args.kwargs["tool_calls"] == []
