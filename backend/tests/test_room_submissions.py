"""Room posts keep human authorship, durable idempotency and current permissions."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.conversation import Conversation, Message
from app.db.models.room_submission import RoomSubmission
from app.db.models.user import User
from app.schemas.room_submission import RoomMessageCreate
from app.services import room_submission as module

pytestmark = pytest.mark.anyio


@pytest.fixture
def room(monkeypatch: pytest.MonkeyPatch):
    org, person, conversation_id = uuid4(), uuid4(), uuid4()
    ctx = AuthContext(user_id=person, organization_id=org, role="member")
    user = User(
        id=person,
        email="writer@example.com",
        full_name="Writer",
        avatar_color=None,
        avatar_url=None,
    )
    topic = Conversation(
        id=conversation_id,
        organization_id=org,
        user_id=uuid4(),
        project_id=uuid4(),
        is_archived=False,
    )
    message = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        role="user",
        content="Hello",
        client_message_id="client-1",
        author_user_id=person,
        run_id=None,
        reply_to_message_id=None,
        created_at=datetime.now(UTC),
        updated_at=None,
    )
    db = MagicMock(info={})
    service = module.RoomSubmissionService(db)
    get_room = AsyncMock(return_value=topic)
    add_message = AsyncMock(return_value=message)
    monkeypatch.setattr(service.conversations, "get_conversation", get_room)
    monkeypatch.setattr(service.conversations, "add_message", add_message)
    monkeypatch.setattr(service.conversations, "get_message", AsyncMock(return_value=message))
    monkeypatch.setattr(service.conversations, "reply_quoted", AsyncMock(return_value=None))
    rows = []

    async def add(_db, row):
        row.created_at = datetime.now(UTC)
        row.ordinal = len(rows) + 1
        rows.append(row)
        return row

    async def existing(_db, **fields):
        return next(
            (
                row
                for row in rows
                if all(getattr(row, key) == value for key, value in fields.items())
            ),
            None,
        )

    monkeypatch.setattr(module.room_repo, "add", AsyncMock(side_effect=add))
    monkeypatch.setattr(module.room_repo, "for_client", AsyncMock(side_effect=existing))
    monkeypatch.setattr(module.room_repo, "save", AsyncMock())
    monkeypatch.setattr(module.room_repo, "active_count", AsyncMock(return_value=0))
    monkeypatch.setattr(module, "hold_subject", AsyncMock())
    registry = MagicMock(
        get_runnable_spec=AsyncMock(return_value=(MagicMock(), MagicMock(), uuid4())),
        get_pinned_spec=AsyncMock(return_value=(MagicMock(), MagicMock(), uuid4())),
    )
    monkeypatch.setattr(module, "AgentRegistryService", MagicMock(return_value=registry))
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(module, "enqueue", enqueue)
    deferred = []

    def defer(_db, coroutine, *, name):
        deferred.append(name)
        coroutine.close()

    monkeypatch.setattr(module, "spawn_after_commit", defer)
    return SimpleNamespace(
        ctx=ctx,
        user=user,
        topic=topic,
        message=message,
        db=db,
        service=service,
        registry=registry,
        enqueue=enqueue,
        rows=rows,
        deferred=deferred,
        get_room=get_room,
        add_message=add_message,
    )


def request(**values):
    return RoomMessageCreate(**({"client_message_id": "client-1", "content": "Hello"} | values))


def pending(room, **values):
    row = RoomSubmission(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        conversation_id=room.topic.id,
        requester_id=room.ctx.subject_id,
        message_id=room.message.id,
        ordinal=1,
        client_message_id="client-1",
        fingerprint=module.fingerprint(request(agent_id=values.get("agent_id"))),
        agent_id=uuid4(),
        version_id=uuid4(),
        status="queued",
        job_id=uuid4(),
        run_id=None,
        created_at=datetime.now(UTC),
    )
    for key, value in values.items():
        setattr(row, key, value)
    return row


@pytest.mark.parametrize(
    "body",
    [
        {"content": " "},
        {"content": "x" * 20_001},
        {"client_message_id": ""},
        {"client_message_id": "x" * 129},
        {"role": "assistant"},
        {"author_user_id": str(uuid4())},
        {"file_ids": [str(uuid4())]},
        {"local": {"folder": "/private"}},
        {"model_profile_id": str(uuid4())},
    ],
)
async def test_the_wire_contract_refuses_blank_unbounded_and_forged_context(body) -> None:
    with pytest.raises(ValidationError):
        request(**body)


async def test_human_post_is_saved_once_without_starting_an_agent(room) -> None:
    first = await room.service.post(room.ctx, room.topic.id, request(), room.user)
    again = await room.service.post(room.ctx, room.topic.id, request(), room.user)
    assert again == first and first.request is None
    assert first.message.sender.user_id == room.ctx.user_id
    assert first.message.content == "Hello"
    room.add_message.assert_awaited_once()
    assert room.add_message.call_args.args[1].role == "user"
    assert room.add_message.call_args.kwargs["user_id"] == room.ctx.user_id
    room.registry.get_runnable_spec.assert_not_called()
    room.enqueue.assert_not_called()
    assert room.deferred == ["room-message-posted"]
    assert room.rows[0].status == "posted" and "RoomSubmission" in repr(room.rows[0])


async def test_explicit_agent_is_pinned_and_retries_return_the_original_request(room) -> None:
    agent = uuid4()
    first = await room.service.post(room.ctx, room.topic.id, request(agent_id=agent), room.user)
    version = room.rows[0].version_id
    room.registry.get_runnable_spec.return_value = (MagicMock(), MagicMock(), uuid4())
    again = await room.service.post(room.ctx, room.topic.id, request(agent_id=agent), room.user)
    assert first == again and first.request.status == "queued"
    assert room.rows[0].version_id == version and room.rows[0].requester_id == room.ctx.user_id
    room.registry.get_runnable_spec.assert_awaited_once_with(room.ctx, agent)
    room.enqueue.assert_awaited_once()
    queued = room.enqueue.call_args
    assert queued.args[2].request_id == first.request.id
    assert queued.kwargs["dedupe_active"] is True
    assert queued.kwargs["concurrency_key"] == f"room:{room.topic.id}"
    assert set(room.deferred) == {"room-message-posted", "room-request-changed"}


@pytest.mark.parametrize(
    "changed", [{"content": "Different"}, {"reply_to_message_id": uuid4()}, {"agent_id": uuid4()}]
)
async def test_same_token_with_changed_content_reply_or_agent_conflicts(room, changed) -> None:
    await room.service.post(room.ctx, room.topic.id, request(), room.user)
    with pytest.raises(AlreadyExistsError, match="different post"):
        await room.service.post(room.ctx, room.topic.id, request(**changed), room.user)
    room.add_message.assert_awaited_once()


@pytest.mark.parametrize(
    "change", [{"api_key_id": uuid4()}, {"is_impersonated": True}, {"user_id": None}]
)
async def test_non_session_authority_is_rejected_before_any_room_lookup(room, change) -> None:
    ctx = replace(room.ctx, **change)
    with pytest.raises(AuthorizationError, match="own signed-in session"):
        await room.service.post(ctx, room.topic.id, request(), room.user)
    room.get_room.assert_not_called()
    room.add_message.assert_not_called()


async def test_user_argument_cannot_change_the_authenticated_author(room) -> None:
    with pytest.raises(AuthorizationError, match="yourself"):
        await room.service.post(
            replace(room.ctx, user_id=uuid4()), room.topic.id, request(), room.user
        )
    room.add_message.assert_not_called()


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("project_id", None, "project chat"),
        ("is_archived", True, "archived"),
    ],
)
async def test_only_open_project_rooms_accept_posts(room, field, value, match) -> None:
    setattr(room.topic, field, value)
    with pytest.raises(BadRequestError, match=match):
        await room.service.post(room.ctx, room.topic.id, request(), room.user)
    room.add_message.assert_not_called()


async def test_revoked_project_or_agent_authority_writes_nothing(room) -> None:
    room.get_room.side_effect = NotFoundError(message="No access")
    with pytest.raises(NotFoundError):
        await room.service.post(room.ctx, room.topic.id, request(agent_id=uuid4()), room.user)
    room.get_room.side_effect = None
    room.registry.get_runnable_spec.side_effect = AuthorizationError(message="No agent access")
    with pytest.raises(AuthorizationError):
        await room.service.post(room.ctx, room.topic.id, request(agent_id=uuid4()), room.user)
    room.add_message.assert_not_called()
    room.enqueue.assert_not_called()


async def test_pending_queue_is_bounded_before_the_human_post_is_written(room, monkeypatch) -> None:
    monkeypatch.setattr(module.room_repo, "active_count", AsyncMock(return_value=50))
    with pytest.raises(AlreadyExistsError, match="fifty"):
        await room.service.post(room.ctx, room.topic.id, request(agent_id=uuid4()), room.user)
    room.add_message.assert_not_called()


@pytest.mark.security
async def test_dedupe_scope_includes_tenant_room_and_requester(room) -> None:
    await room.service.post(room.ctx, room.topic.id, request(), room.user)
    scope = module.room_repo.for_client.call_args.kwargs
    assert scope == {
        "organization_id": room.ctx.organization_id,
        "conversation_id": room.topic.id,
        "requester_id": room.ctx.user_id,
        "client_message_id": "client-1",
    }


@pytest.mark.parametrize("can_post,archived", [(True, False), (False, False), (False, True)])
async def test_queue_reports_current_project_use_even_for_the_owner(
    room, monkeypatch, can_post, archived
) -> None:
    room.topic.is_archived = archived
    if not can_post and not archived:
        room.get_room.side_effect = [room.topic, NotFoundError(message="Read only")]
    row = pending(room)
    monkeypatch.setattr(module.room_repo, "list_requests", AsyncMock(return_value=([row], 1)))
    result = await room.service.list_for_room(room.ctx, room.topic.id, skip=5, limit=10)
    assert result.can_post is can_post and result.total == 1 and result.items[0].id == row.id
    assert module.room_repo.list_requests.call_args.kwargs["skip"] == 5


async def test_cancel_is_requester_only_and_queued_only(room, monkeypatch) -> None:
    row = pending(room)
    monkeypatch.setattr(module.room_repo, "get", AsyncMock(return_value=row))
    cancel = AsyncMock()
    monkeypatch.setattr(module.job_repo, "cancel_queued", cancel)
    result = await room.service.cancel(room.ctx, room.topic.id, row.id)
    assert result.status == "cancelled" and room.message.content == "Hello"
    again = await room.service.cancel(room.ctx, room.topic.id, row.id)
    assert again == result
    cancel.assert_awaited_once_with(room.db, row.job_id)
    row.status = "running"
    with pytest.raises(AlreadyExistsError, match="queued"):
        await room.service.cancel(room.ctx, room.topic.id, row.id)


@pytest.mark.parametrize(
    "change", [None, {"requester_id": uuid4()}, {"conversation_id": uuid4()}, {"agent_id": None}]
)
async def test_cancel_hides_missing_other_member_and_other_room_requests(
    room, monkeypatch, change
) -> None:
    row = None if change is None else pending(room, **change)
    monkeypatch.setattr(module.room_repo, "get", AsyncMock(return_value=row))
    with pytest.raises(NotFoundError):
        await room.service.cancel(room.ctx, room.topic.id, uuid4())


async def test_cancel_remains_valid_without_a_retained_queue_job(room, monkeypatch) -> None:
    row = pending(room, job_id=None)
    monkeypatch.setattr(module.room_repo, "get", AsyncMock(return_value=row))
    assert (await room.service.cancel(room.ctx, room.topic.id, row.id)).status == "cancelled"


async def test_queued_dispatch_dedupe_preserves_the_existing_job_id(room) -> None:
    row = pending(room)
    old_job = row.job_id
    room.enqueue.return_value = None
    await room.service.queue(row)
    assert row.job_id == old_job


async def test_execution_reconstructs_the_original_member_and_rechecks_pinned_agent(
    room, monkeypatch
) -> None:
    row = pending(room)
    row.fingerprint = module.fingerprint(request(agent_id=row.agent_id))
    member = AsyncMock(return_value=room.ctx)
    monkeypatch.setattr(module, "acting_member", member)
    monkeypatch.setattr(
        module.conversation_repo, "get_message_by_id", AsyncMock(return_value=room.message)
    )
    ctx, topic, message = await room.service.authority(row)
    assert (ctx, topic, message) == (room.ctx, room.topic, room.message)
    member.assert_awaited_once_with(room.db, row.organization_id, str(row.requester_id))
    room.registry.get_pinned_spec.assert_awaited_once_with(ctx, row.agent_id, row.version_id)
    assert room.get_room.call_args.kwargs["for_write"] is True


@pytest.mark.parametrize(
    "refusal", ["member", "agent", "missing", "room", "author", "role", "changed"]
)
async def test_execution_refuses_lost_or_changed_authority_and_original_message(
    room, monkeypatch, refusal
) -> None:
    row = pending(room)
    row.fingerprint = module.fingerprint(request(agent_id=row.agent_id))
    monkeypatch.setattr(
        module, "acting_member", AsyncMock(return_value=None if refusal == "member" else room.ctx)
    )
    message = room.message
    if refusal == "agent":
        row.agent_id = None
    elif refusal == "room":
        message.conversation_id = uuid4()
    elif refusal == "author":
        message.author_user_id = uuid4()
    elif refusal == "role":
        message.role = "assistant"
    elif refusal == "changed":
        message.content = "Injected afterwards"
    monkeypatch.setattr(
        module.conversation_repo,
        "get_message_by_id",
        AsyncMock(return_value=None if refusal == "missing" else message),
    )
    with pytest.raises((AuthorizationError, BadRequestError, NotFoundError, AlreadyExistsError)):
        await room.service.authority(row)


@pytest.mark.parametrize(
    "capability,config",
    [
        ("sandbox", {"backend": "local"}),
        ("coding_agent", {"runs_on": "this_computer"}),
        ("coding_agent", {"runs_on": "personal_sandbox"}),
    ],
)
async def test_local_agents_are_refused_by_the_server_at_submission(
    room, capability, config
) -> None:
    spec = AgentSpec(
        name="Local",
        model_profile_id=uuid4(),
        capabilities=[CapabilityBindingSpec(id=capability, config=config)],
    )
    room.registry.get_runnable_spec.return_value = (object(), spec, uuid4())
    with pytest.raises(BadRequestError, match="cloud agent"):
        await room.service.post(room.ctx, room.topic.id, request(agent_id=uuid4()), room.user)
    room.add_message.assert_not_called()


async def test_local_agent_pinned_version_is_refused_at_execution(room, monkeypatch) -> None:
    row = pending(room)
    monkeypatch.setattr(module, "acting_member", AsyncMock(return_value=room.ctx))
    spec = AgentSpec(
        name="Local",
        model_profile_id=uuid4(),
        capabilities=[CapabilityBindingSpec(id="sandbox", config={"backend": "local"})],
    )
    room.registry.get_pinned_spec.return_value = (object(), spec, uuid4())
    with pytest.raises(BadRequestError, match="cloud agent"):
        await room.service.authority(row)


async def test_disabled_local_capability_does_not_block_a_cloud_agent() -> None:
    module.cloud_agent(
        AgentSpec(
            name="Cloud",
            model_profile_id=uuid4(),
            capabilities=[
                CapabilityBindingSpec(id="sandbox", config={"backend": "local"}, enabled=False),
                CapabilityBindingSpec(id="coding_agent", config={"runs_on": "sandbox"}),
            ],
        )
    )


@pytest.mark.parametrize("status", ["running", "awaiting_answer", "awaiting_approval"])
async def test_room_resumption_revalidates_the_original_requester(
    room, monkeypatch, status
) -> None:
    row = pending(room, status=status, run_id=uuid4())
    row.fingerprint = module.fingerprint(request(agent_id=row.agent_id))
    monkeypatch.setattr(module.room_repo, "for_run", AsyncMock(return_value=row))
    monkeypatch.setattr(module.room_repo, "head", AsyncMock(return_value=row))
    monkeypatch.setattr(module, "acting_member", AsyncMock(return_value=room.ctx))
    monkeypatch.setattr(
        module.conversation_repo, "get_message_by_id", AsyncMock(return_value=room.message)
    )
    assert (
        await room.service.resume_authority(row.run_id, row.organization_id, required=True)
        == room.ctx
    )
    module.acting_member.assert_awaited_once_with(
        room.db, row.organization_id, str(row.requester_id)
    )


async def test_ordinary_resumes_need_no_room_authority_and_lost_room_fences_refuse(
    room, monkeypatch
) -> None:
    monkeypatch.setattr(module.room_repo, "for_run", AsyncMock(return_value=None))
    assert await room.service.resume_authority(uuid4(), room.ctx.organization_id) is None
    with pytest.raises(AlreadyExistsError):
        await room.service.resume_authority(uuid4(), room.ctx.organization_id, required=True)


@pytest.mark.parametrize("fault", ["terminal", "head", "membership", "project"])
async def test_a_parked_request_cannot_resume_with_lost_original_authority(
    room, monkeypatch, fault
) -> None:
    row = pending(
        room, status="completed" if fault == "terminal" else "awaiting_answer", run_id=uuid4()
    )
    monkeypatch.setattr(module.room_repo, "for_run", AsyncMock(return_value=row))
    monkeypatch.setattr(
        module.room_repo, "head", AsyncMock(return_value=None if fault == "head" else row)
    )
    monkeypatch.setattr(
        module, "acting_member", AsyncMock(return_value=None if fault == "membership" else room.ctx)
    )
    if fault == "project":
        room.get_room.side_effect = NotFoundError(message="Project use revoked")
    with pytest.raises((AlreadyExistsError, AuthorizationError, NotFoundError)):
        await room.service.resume_authority(row.run_id, row.organization_id, required=True)


async def test_human_message_response_cannot_launder_an_assistant_turn(room) -> None:
    room.message.role = "assistant"
    with pytest.raises(BadRequestError, match="human post"):
        await room.service.read_message(room.message, room.user)
