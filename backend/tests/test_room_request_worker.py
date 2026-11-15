"""Ordered room execution uses the requester and never replays an uncertain run."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AlreadyExistsError, AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.room_submission import RoomSubmission
from app.schemas.conversation import ChatPerson, MessageRead
from app.worker.jobs import RUN_ROOM_REQUEST, RoomRequestJob
from app.worker.tasks import room_tasks as module

pytestmark = pytest.mark.anyio


@pytest.fixture
def work(monkeypatch: pytest.MonkeyPatch):
    row = RoomSubmission(
        id=uuid4(),
        organization_id=uuid4(),
        conversation_id=uuid4(),
        requester_id=uuid4(),
        message_id=uuid4(),
        ordinal=1,
        agent_id=uuid4(),
        version_id=uuid4(),
        status="queued",
        run_id=None,
        job_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    ctx = AuthContext(user_id=row.requester_id, organization_id=row.organization_id, role="member")
    message = SimpleNamespace(id=row.message_id, content="Please answer this")
    topic = SimpleNamespace(id=row.conversation_id)
    sender = SimpleNamespace(id=row.requester_id)
    read = MessageRead(
        id=row.message_id,
        conversation_id=row.conversation_id,
        role="user",
        content=message.content,
        client_message_id="client-1",
        created_at=datetime.now(UTC),
        sender=ChatPerson(user_id=row.requester_id, name="Requester"),
    )
    db = MagicMock(commit=AsyncMock(), info={})

    @asynccontextmanager
    async def database():
        yield db

    @asynccontextmanager
    async def admitted(*_args, **_kwargs):
        yield True

    @asynccontextmanager
    async def live(*_args, **_kwargs):
        yield MagicMock(drive=AsyncMock())

    get = AsyncMock(return_value=row)
    monkeypatch.setattr(module, "get_worker_db_context", database)
    monkeypatch.setattr(module, "claim", admitted)
    monkeypatch.setattr(module.room_repo, "get", get)
    monkeypatch.setattr(module.room_repo, "head", AsyncMock(return_value=row))
    monkeypatch.setattr(module.room_repo, "save", AsyncMock())
    monkeypatch.setattr(
        module.conversation_repo, "users_by_id", AsyncMock(return_value={row.requester_id: sender})
    )
    monkeypatch.setattr(module.conversation_repo, "link_message_to_run", AsyncMock())
    service = MagicMock(
        authority=AsyncMock(return_value=(ctx, topic, message)),
        read_message=AsyncMock(return_value=read),
        queue=AsyncMock(),
        conversations=MagicMock(model_text=AsyncMock(return_value="Requester: Please answer this")),
    )
    monkeypatch.setattr(module, "RoomSubmissionService", MagicMock(return_value=service))
    history = [object()]
    history_service = MagicMock(model_history=AsyncMock(return_value=history))
    monkeypatch.setattr(module, "ConversationService", MagicMock(return_value=history_service))
    monkeypatch.setattr(module, "_live", live)
    monkeypatch.setattr(module, "_emit_saved", AsyncMock())
    monkeypatch.setattr(module, "announce_request", MagicMock())
    monkeypatch.setattr(module, "start_deferred", MagicMock())
    execute = AsyncMock()
    monkeypatch.setattr(module.AgentRunnerService, "execute", execute)
    run = SimpleNamespace(id=uuid4(), organization_id=row.organization_id, status="completed")
    execute.return_value = ("Answer", run)
    return SimpleNamespace(
        row=row,
        ctx=ctx,
        db=db,
        service=service,
        get=get,
        execute=execute,
        history=history,
        history_service=history_service,
        run=run,
        message=message,
        read=read,
        job=RoomRequestJob(request_id=row.id, organization_id=row.organization_id),
    )


@pytest.mark.parametrize(
    "status",
    [
        "posted",
        "running",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
        "awaiting_answer",
        "awaiting_approval",
    ],
)
async def test_manual_retry_of_an_already_admitted_request_never_starts_again(work, status) -> None:
    work.row.status = status
    await module.run_request(work.job)
    work.execute.assert_not_called()
    work.service.authority.assert_not_called()
    assert RUN_ROOM_REQUEST.max_attempts == 1


async def test_deleted_requests_never_start(work) -> None:
    work.get.return_value = None
    await module.run_request(work.job)
    work.execute.assert_not_called()


async def test_busy_room_defers_without_spending_or_churning_new_jobs(work, monkeypatch) -> None:
    @asynccontextmanager
    async def busy(*_args, **kwargs):
        assert kwargs["room_request_id"] == work.row.id and kwargs["background"]
        yield False

    monkeypatch.setattr(module, "claim", busy)
    await module.run_request(work.job)
    assert work.row.status == "queued"
    work.execute.assert_not_called()
    work.service.queue.assert_not_called()


@pytest.mark.parametrize("changed", ["deleted", "started", "later"])
async def test_admission_rechecks_the_durable_request_and_oldest_head(
    work, monkeypatch, changed
) -> None:
    if changed == "deleted":
        work.get.side_effect = [work.row, None]
    elif changed == "started":
        second = SimpleNamespace(status="running")
        work.get.side_effect = [work.row, second]
    else:
        monkeypatch.setattr(
            module.room_repo, "head", AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        )
    await module.run_request(work.job)
    work.execute.assert_not_called()


async def test_revoked_authority_fails_before_opening_any_paid_run(work) -> None:
    work.service.authority.side_effect = AuthorizationError(message="Revoked")
    await module.run_request(work.job)
    assert work.row.status == "failed"
    work.execute.assert_not_called()
    assert "Access" in work.row.error


async def test_missing_sender_after_revalidation_still_refuses_execution(work, monkeypatch) -> None:
    monkeypatch.setattr(module.conversation_repo, "users_by_id", AsyncMock(return_value={}))
    await module.run_request(work.job)
    assert work.row.status == "failed"
    work.execute.assert_not_called()


async def test_pinned_requester_runs_once_with_bounded_history_and_shared_audience(work) -> None:
    async def execute(ctx, agent_id, prompt, **options):
        assert ctx is work.ctx and ctx.user_id == work.row.requester_id
        assert agent_id == work.row.agent_id and options["version_id"] == work.row.version_id
        assert prompt == "Requester: Please answer this"
        assert options["said"] == ""  # The human post is already durable.
        assert options["memory_room_key"] == f"room:project:{work.row.conversation_id}"
        assert options["message_history"] is work.history
        assert options["acts_for_sender"] is True and options["parks_questions"] is True
        assert "local" not in options and "model_profile_id" not in options
        assert work.row.status == "running"
        work.db.commit.assert_awaited_once()
        await options["on_run_open"](work.run)
        assert work.row.run_id == work.run.id
        await options["check_model_request"](work.db)
        await options["on_segment"](SimpleNamespace(run=work.run))
        return "Answer", work.run

    work.execute.side_effect = execute
    await module.run_request(work.job)
    assert work.row.status == "completed"
    work.history_service.model_history.assert_awaited_once_with(
        work.row.conversation_id, limit=60, room_request_message_id=work.row.message_id
    )
    module.conversation_repo.link_message_to_run.assert_awaited_once_with(
        work.db,
        message_id=work.row.message_id,
        run_id=work.run.id,
        conversation_id=work.row.conversation_id,
    )
    assert work.service.authority.await_count == 2
    await module.run_request(work.job)
    work.execute.assert_awaited_once()


@pytest.mark.parametrize("stage", ["open", "before-model"])
async def test_a_lost_request_fence_stops_before_a_model_can_spend(work, stage) -> None:
    async def execute(*_args, **options):
        if stage == "open":
            work.row.status = "interrupted"
            with pytest.raises(AlreadyExistsError):
                await options["on_run_open"](work.run)
        else:
            await options["on_run_open"](work.run)
            work.row.status = "interrupted"
            with pytest.raises(AlreadyExistsError):
                await options["check_model_request"](work.db)
        return "", work.run

    work.execute.side_effect = execute
    await module.run_request(work.job)
    assert work.row.status == "interrupted"


async def test_prepare_refusal_is_reported_without_auto_replay(work) -> None:
    work.execute.side_effect = AuthorizationError(message="Model access changed")
    await module.run_request(work.job)
    assert work.row.status == "failed"
    await module.run_request(work.job)
    work.execute.assert_awaited_once()


@pytest.mark.security
@pytest.mark.parametrize("settlement", ["deleted", "completed"])
async def test_a_late_execution_error_cannot_reopen_or_overwrite_a_settled_request(
    work, settlement
) -> None:
    async def execute(*_args, **_options):
        if settlement == "deleted":
            work.get.return_value = None
        else:
            work.row.status = "completed"
        raise AuthorizationError(message="A late provider refusal")

    work.execute.side_effect = execute

    await module.run_request(work.job)
    await module.run_request(work.job)

    work.execute.assert_awaited_once()
    module.room_repo.save.assert_awaited_once()  # Only the original running transition.
    module.announce_request.assert_called_once()
    work.service.queue.assert_not_awaited()
    if settlement == "completed":
        assert work.row.status == "completed" and work.row.error is None


@pytest.mark.parametrize(
    "status,expected",
    [
        ("awaiting_approval", "awaiting_approval"),
        ("awaiting_answer", "awaiting_answer"),
        ("completed", "completed"),
        ("cancelled", "cancelled"),
        ("guardrail_blocked", "failed"),
    ],
)
async def test_settlement_follows_the_saved_run_and_never_discloses_raw_errors(
    work, status, expected
) -> None:
    work.row.status = "running"
    work.row.run_id = work.run.id
    work.run.status = status
    await module._settle(work.db, work.row.id, work.run)
    assert work.row.status == expected
    assert (work.row.error is not None) == (expected == "failed")


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_lost_dispatch_is_terminal_and_manual_retry_cannot_repeat_actions(
    work, status
) -> None:
    work.row.status = status
    await module.settle_lost_request(work.job, "raw secret-bearing vendor exception")
    assert work.row.status == "interrupted" and "secret-bearing" not in work.row.error
    await module.run_request(work.job)
    work.execute.assert_not_called()


@pytest.mark.parametrize("status", ["posted", "completed", "awaiting_answer", "awaiting_approval"])
async def test_a_late_job_settler_preserves_completed_and_parked_work(work, status) -> None:
    work.row.status = status
    await module.settle_lost_request(work.job, "lost duplicate")
    assert work.row.status == status


async def test_reconciler_settles_resumes_and_queues_only_repository_selected_heads(
    work, monkeypatch
) -> None:
    work.row.status = "awaiting_answer"
    work.row.run_id = work.run.id
    ready = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(
        module.room_repo, "unsettled_runs", AsyncMock(return_value=[(work.row, work.run)])
    )
    monkeypatch.setattr(module.room_repo, "ready", AsyncMock(return_value=[ready]))
    assert await module.reconcile_requests() == 2
    assert work.row.status == "completed"
    work.service.queue.assert_awaited_once_with(ready)


@pytest.mark.parametrize("trace_available", [False, True])
async def test_live_stream_uses_the_same_saved_prompt_and_sender(
    monkeypatch, trace_available
) -> None:
    # Exercise the real stream context separately from the worker fixture.
    row = SimpleNamespace(conversation_id=uuid4(), requester_id=uuid4(), agent_id=uuid4())
    message = MessageRead(
        id=uuid4(),
        conversation_id=row.conversation_id,
        role="user",
        content="Hello",
        client_message_id="token",
        created_at=datetime.now(UTC),
        sender=ChatPerson(user_id=row.requester_id, name="Sender"),
    )
    trace = object() if trace_available else None
    begin, publish, end, begun = (
        AsyncMock(return_value=trace),
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
    )
    monkeypatch.setattr(module.live_turn, "begin", begin)
    monkeypatch.setattr(module.live_turn, "publish", publish)
    monkeypatch.setattr(module.live_turn, "end", end)
    monkeypatch.setattr(module.chat_room, "turn_begun", begun)
    async with module._live(row, message):
        pass
    begun.assert_awaited_once_with(str(row.conversation_id), row.requester_id)
    if trace_available:
        event = publish.call_args_list[0].args
        assert event[1] == "turn_prompt" and event[2]["message_id"] == str(message.id)
        assert event[2]["sender"]["user_id"] == str(row.requester_id)
        assert publish.call_args_list[-1].args[1] == "complete"
        end.assert_awaited_once_with(trace)
    else:
        publish.assert_not_awaited()
        end.assert_not_awaited()


@pytest.mark.parametrize("visible", [False, True])
async def test_saved_acknowledgement_requires_a_committed_assistant_message(
    monkeypatch, visible
) -> None:
    db = MagicMock()

    @asynccontextmanager
    async def database():
        yield db

    run = SimpleNamespace(id=uuid4(), status="completed")
    message = SimpleNamespace(id=uuid4(), run_id=run.id, conversation_id=uuid4())
    segment = SimpleNamespace(run=run, message_id=message.id)
    frames = MagicMock(emit=AsyncMock())
    monkeypatch.setattr(module, "get_worker_db_context", database)
    monkeypatch.setattr(
        module.conversation_repo,
        "get_message_by_id",
        AsyncMock(return_value=message if visible else None),
    )
    await module._emit_saved(frames, segment)
    assert frames.emit.await_count == int(visible)
    if visible:
        assert frames.emit.call_args.args[0] == "message_saved"
        assert frames.emit.call_args.args[1]["message_id"] == str(message.id)


async def test_no_saved_acknowledgement_is_invented_for_an_unpersisted_turn() -> None:
    frames = MagicMock(emit=AsyncMock())
    await module._emit_saved(frames, None)
    await module._emit_saved(frames, SimpleNamespace(message_id=None))
    frames.emit.assert_not_called()


@pytest.mark.parametrize("kind", ["message", "request"])
async def test_room_invalidation_contains_only_identifiers_and_includes_the_sender(
    monkeypatch, kind
) -> None:
    room_id, record = str(uuid4()), uuid4()
    announce = AsyncMock()
    monkeypatch.setattr(module.chat_room, "_announce", announce)
    if kind == "message":
        await module.chat_room.room_message(room_id, record)
    else:
        await module.chat_room.room_request(room_id, record)
    args, kwargs = announce.call_args
    assert args == (room_id, f"room_{kind}")
    assert kwargs == {f"{kind}_id": str(record)}
