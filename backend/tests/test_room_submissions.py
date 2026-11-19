"""Room posts keep human authorship, durable idempotency and current permissions."""

import hashlib
import json
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
from app.schemas.room_participant import RoomParticipantRead, RoomParticipantRef
from app.schemas.room_submission import RoomMessageCreate
from app.services import room_submission as module
from app.services.notifications import NotificationService
from app.services.room_participant import RoomParticipantService

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
    monkeypatch.setattr(module.chat_file_repo, "for_message", AsyncMock(return_value=[]))
    monkeypatch.setattr(module.reaction_repo, "list_aggregates", AsyncMock(return_value={}))
    monkeypatch.setattr(service.conversations, "list_attached_files", AsyncMock(return_value=[]))
    monkeypatch.setattr(service.conversations, "link_files_to_message", AsyncMock())
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
    monkeypatch.setattr(RoomParticipantService, "automatic_agents", AsyncMock(return_value=[]))
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
        intent="message",
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


@pytest.mark.security
async def test_a_planning_run_cannot_resume_as_the_full_published_agent(room, monkeypatch):
    row = pending(room, intent="ask_lead", lead_policy_revision=1, status="awaiting_answer")
    monkeypatch.setattr(module.room_repo, "for_run", AsyncMock(return_value=row))
    with pytest.raises(AlreadyExistsError, match="new Ask lead"):
        await room.service.resume_authority(uuid4(), room.ctx.organization_id)


@pytest.mark.parametrize(
    "body",
    [
        {"content": " "},
        {"content": "x" * 20_001},
        {"client_message_id": ""},
        {"client_message_id": "x" * 129},
        {"role": "assistant"},
        {"author_user_id": str(uuid4())},
        {"file_ids": ["not-a-file-id"]},
        {"file_ids": [str(uuid4()) for _ in range(11)]},
        {"local": {"folder": "/private"}},
        {"model_profile_id": str(uuid4())},
        {"intent": "ask_lead"},
        {"intent": "ask_lead", "expected_policy_revision": 1, "agent_id": str(uuid4())},
        {"expected_policy_revision": 1},
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
    "changed",
    [
        {"content": "Different"},
        {"reply_to_message_id": uuid4()},
        {"reply_to_message_id": uuid4(), "reply_to_excerpt": "A different selected excerpt"},
        {"agent_id": uuid4()},
        {"thread_root_message_id": uuid4()},
    ],
)
async def test_same_token_with_changed_content_reply_thread_or_agent_conflicts(
    room, changed
) -> None:
    await room.service.post(room.ctx, room.topic.id, request(), room.user)
    with pytest.raises(AlreadyExistsError, match="different post"):
        await room.service.post(room.ctx, room.topic.id, request(**changed), room.user)
    room.add_message.assert_awaited_once()


def test_main_room_fingerprint_keeps_the_deployed_digest_shape() -> None:
    agent, quote = uuid4(), uuid4()
    data = request(content="Hello 世界", agent_id=agent, reply_to_message_id=quote)
    deployed = json.dumps(
        {"content": data.content, "reply_to_message_id": str(quote), "agent_id": str(agent)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    assert module.fingerprint(data) == hashlib.sha256(deployed).hexdigest()
    assert module.fingerprint(data.model_copy(update={"thread_root_message_id": uuid4()})) != (
        module.fingerprint(data)
    )


def test_room_quote_is_normalized_and_part_of_the_idempotency_fingerprint() -> None:
    quote = uuid4()
    plain = request(reply_to_message_id=quote)
    selected = request(reply_to_message_id=quote, reply_to_excerpt="  one\u00a0 selected\n line ")

    assert selected.reply_to_excerpt == "one selected line"
    assert module.fingerprint(selected) != module.fingerprint(plain)


def test_room_excerpt_requires_a_linked_message() -> None:
    with pytest.raises(ValidationError, match="requires reply_to_message_id"):
        request(reply_to_excerpt="quote")


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
        ("project_id", None, "make this conversation a room"),
        ("is_archived", True, "archived"),
    ],
)
async def test_ordinary_or_archived_conversations_cannot_accept_room_posts(
    room, field, value, match
) -> None:
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
        await room.service.read_message(
            room.message, room.user, organization_id=room.ctx.organization_id
        )


@pytest.fixture
def multiplayer(room, monkeypatch: pytest.MonkeyPatch):
    room.topic.project_id = None
    room.topic.room_visibility = "private"
    room.topic.title = "Design team"
    room.message.room_mentions = []
    first = RoomParticipantRead(
        kind="agent",
        id=uuid4(),
        name="Analyst",
        avatar_url=None,
        is_member=True,
        can_add=False,
        can_mention=True,
        auto_reply=True,
    )
    second = first.model_copy(update={"id": uuid4(), "name": "Reviewer"})
    human = first.model_copy(
        update={"kind": "user", "id": uuid4(), "name": "Alex", "auto_reply": False}
    )
    members = [first, second, human]

    async def validate(_ctx, _conversation_id, refs):
        return [
            next(item for item in members if (item.kind, item.id) == (ref.kind, ref.id))
            for ref in refs
        ]

    async def keep(_db, *, message, mentions):
        message.room_mentions = mentions

    validate_mentions = AsyncMock(side_effect=validate)
    automatic = AsyncMock(return_value=[])
    monkeypatch.setattr(RoomParticipantService, "validate_mentions", validate_mentions)
    monkeypatch.setattr(RoomParticipantService, "automatic_agents", automatic)
    monkeypatch.setattr(module.room_repo, "keep_mentions", AsyncMock(side_effect=keep))
    monkeypatch.setattr(
        module.room_repo,
        "for_post",
        AsyncMock(
            side_effect=lambda _db, *, root: [
                row for row in room.rows if row.id == root.id or row.parent_submission_id == root.id
            ]
        ),
    )
    notify = AsyncMock()
    monkeypatch.setattr(NotificationService, "room_mentioned", notify)
    return SimpleNamespace(
        room=room,
        first=first,
        second=second,
        human=human,
        members=members,
        validate=validate_mentions,
        automatic=automatic,
        notify=notify,
    )


def refs(*participants):
    return [RoomParticipantRef(kind=item.kind, id=item.id) for item in participants]


async def test_multiple_bot_mentions_share_one_post_and_retry_returns_all_original_requests(
    multiplayer,
):
    m, room = multiplayer, multiplayer.room
    data = request(mentions=refs(m.first, m.second, m.human))
    first = await room.service.post(room.ctx, room.topic.id, data, room.user)
    versions = [row.version_id for row in room.rows]
    # Reordered recipient ids and a later rename still describe the accepted post.
    m.first.name = "Renamed later"
    again = await room.service.post(
        room.ctx,
        room.topic.id,
        data.model_copy(update={"mentions": list(reversed(data.mentions))}),
        room.user,
    )
    assert first == again
    assert first.request == first.requests[0]
    assert [item.agent_id for item in first.requests] == [m.first.id, m.second.id]
    assert len(room.rows) == 2 and room.rows[1].parent_submission_id == room.rows[0].id
    assert {row.message_id for row in room.rows} == {room.message.id}
    assert {row.client_message_id for row in room.rows} == {"client-1"}
    assert all(row.dispatch == "mention" for row in room.rows)
    assert [row.version_id for row in room.rows] == versions
    assert first.message.room_mentions[0].name == "Analyst"
    room.add_message.assert_awaited_once()
    assert room.enqueue.await_count == 2
    m.validate.assert_awaited_once()
    m.notify.assert_awaited_once()
    assert m.notify.await_args.kwargs["recipients"] == [m.human.id]
    m.automatic.assert_not_awaited()


async def test_human_mentions_notify_without_spending_or_enabling_automatic_replies(multiplayer):
    m, room = multiplayer, multiplayer.room
    own = m.human.model_copy(update={"id": room.ctx.subject_id})
    m.members.append(own)
    data = request(mentions=refs(m.human, own))
    result = await room.service.post(room.ctx, room.topic.id, data, room.user)
    await room.service.post(room.ctx, room.topic.id, data, room.user)
    assert result.request is None and result.requests == []
    assert [item.id for item in result.message.room_mentions] == [m.human.id, own.id]
    room.enqueue.assert_not_awaited()
    room.registry.get_runnable_spec.assert_not_awaited()
    m.automatic.assert_not_awaited()
    m.notify.assert_awaited_once()
    assert m.notify.await_args.kwargs["recipients"] == [m.human.id]


@pytest.mark.security
async def test_unknown_or_removed_mention_is_rejected_before_saving_any_post(multiplayer):
    m, room = multiplayer, multiplayer.room
    m.validate.side_effect = AuthorizationError(message="Recipient is no longer a member")
    with pytest.raises(AuthorizationError):
        await room.service.post(room.ctx, room.topic.id, request(mentions=refs(m.first)), room.user)
    room.add_message.assert_not_awaited()
    room.enqueue.assert_not_awaited()
    m.notify.assert_not_awaited()


@pytest.mark.security
async def test_every_mentioned_agent_must_be_runnable_before_any_message_is_written(multiplayer):
    m, room = multiplayer, multiplayer.room
    room.registry.get_runnable_spec.side_effect = [
        (MagicMock(), MagicMock(), uuid4()),
        AuthorizationError(message="Agent use revoked"),
    ]
    with pytest.raises(AuthorizationError):
        await room.service.post(
            room.ctx, room.topic.id, request(mentions=refs(m.first, m.second)), room.user
        )
    room.add_message.assert_not_awaited()
    room.enqueue.assert_not_awaited()


async def test_fanout_capacity_is_checked_for_all_agents_together(multiplayer, monkeypatch):
    m, room = multiplayer, multiplayer.room
    monkeypatch.setattr(module.room_repo, "active_count", AsyncMock(return_value=49))
    with pytest.raises(AlreadyExistsError, match="fifty"):
        await room.service.post(
            room.ctx, room.topic.id, request(mentions=refs(m.first, m.second)), room.user
        )
    room.add_message.assert_not_awaited()


async def test_automatic_dispatch_is_frozen_across_retries_and_visible_in_the_queue(multiplayer):
    m, room = multiplayer, multiplayer.room
    m.automatic.return_value = [m.first, m.second]
    room.message.content = "Please review"
    data = request(content=room.message.content)
    first = await room.service.post(room.ctx, room.topic.id, data, room.user)
    m.automatic.return_value = [m.second]
    again = await room.service.post(room.ctx, room.topic.id, data, room.user)
    assert first == again and first.request.dispatch == "automatic"
    assert [item.agent_id for item in first.requests] == [m.first.id]
    m.automatic.assert_awaited_once()
    room.enqueue.assert_awaited_once()


@pytest.mark.security
@pytest.mark.parametrize("fault", ["none", "removed", "disabled", "retargeted", "parent"])
async def test_child_dequeue_rechecks_membership_and_original_post(multiplayer, monkeypatch, fault):
    m, room = multiplayer, multiplayer.room
    data = request(mentions=refs(m.first, m.second))
    result = await room.service.post(room.ctx, room.topic.id, data, room.user)
    child, parent = room.rows[1], room.rows[0]
    monkeypatch.setattr(module, "acting_member", AsyncMock(return_value=room.ctx))
    monkeypatch.setattr(
        module.conversation_repo, "get_message_by_id", AsyncMock(return_value=room.message)
    )
    monkeypatch.setattr(module.room_repo, "get", AsyncMock(return_value=parent))
    if fault == "removed":
        m.validate.side_effect = AuthorizationError(message="Agent removed")
    elif fault == "disabled":
        child.dispatch = "automatic"
        m.second.auto_reply = False
    elif fault == "retargeted":
        room.message.room_mentions = [room.message.room_mentions[0]]
    elif fault == "parent":
        parent.client_message_id = "another-post"
    if fault == "none":
        assert result.requests[1].id == child.id
        assert await room.service.authority(child) == (room.ctx, room.topic, room.message)
    else:
        with pytest.raises((AuthorizationError, AlreadyExistsError)):
            await room.service.authority(child)


def test_mention_identity_and_fingerprint_use_kind_and_id_not_display_names():
    same_id = uuid4()
    one = RoomParticipantRef(kind="user", id=same_id)
    two = RoomParticipantRef(kind="agent", id=same_id)
    data = request(mentions=[one, two])
    assert module.fingerprint(data) == module.fingerprint(request(mentions=[two, one]))
    assert module.fingerprint(data) != module.fingerprint(request(mentions=[one]))
    with pytest.raises(ValidationError):
        request(mentions=[one, one])
    with pytest.raises(ValidationError):
        request(mentions=[two], agent_id=uuid4())
    with pytest.raises(ValidationError):
        request(mentions=[two], intent="ask_lead", expected_policy_revision=1)
    assert request(mentions=[one], intent="ask_lead", expected_policy_revision=1).mentions == [one]


def test_automatic_router_only_uses_opted_in_candidates_and_bounds_broad_replies(multiplayer):
    m = multiplayer
    candidates = [m.first, m.second] + [
        m.first.model_copy(update={"id": uuid4(), "name": f"Bot {i}"}) for i in range(5)
    ]
    assert module.automatic_targets("Thanks!", candidates) == []
    assert module.automatic_targets("Nothing to route", []) == []
    assert module.automatic_targets("Reviewer, can you check this?", candidates) == [m.second]
    assert module.automatic_targets("All agents please review", candidates) == candidates[:4]
    short = m.first.model_copy(update={"name": "Al"})
    assert module.automatic_targets("Call Reviewer", [short, m.second]) == [m.second]


def test_room_upload_contract_accepts_captionless_files_and_freezes_their_identities():
    first, second = uuid4(), uuid4()
    data = request(content="", file_ids=[first, second])
    assert data.content == "" and data.file_ids == [first, second]
    assert module.fingerprint(data) == module.fingerprint(
        request(content="", file_ids=[second, first])
    )
    assert module.fingerprint(data) != module.fingerprint(request(content="", file_ids=[first]))
    with pytest.raises(ValidationError, match="Attach each file once"):
        request(file_ids=[first, first])
    with pytest.raises(ValidationError, match="Write a message"):
        request(content="", file_ids=[])


async def test_room_uploads_link_once_and_a_retry_returns_the_same_file_cards(room, monkeypatch):
    upload = SimpleNamespace(
        id=uuid4(), filename="diagram.png", mime_type="image/png", file_type="image"
    )
    room.message.content = ""
    reads = module.chat_file_repo.for_message
    room.service.conversations.list_attached_files.return_value = [upload]

    async def linked(*_args, **_kwargs):
        reads.return_value = [upload]

    room.service.conversations.link_files_to_message.side_effect = linked
    monkeypatch.setattr(module.room_repo, "for_post", AsyncMock(return_value=room.rows))
    data = request(content="", file_ids=[upload.id])
    first = await room.service.post(room.ctx, room.topic.id, data, room.user)
    second = await room.service.post(room.ctx, room.topic.id, data, room.user)
    assert first == second and first.message.content == ""
    assert first.message.files[0].id == upload.id
    room.add_message.assert_awaited_once()
    room.service.conversations.link_files_to_message.assert_awaited_once_with(
        room.message.id, [str(upload.id)], user_id=room.user.id
    )
    room.service.conversations.list_attached_files.assert_awaited_once()
    room.enqueue.assert_not_awaited()


@pytest.mark.security
async def test_foreign_or_already_claimed_upload_refuses_the_entire_room_post(room):
    room.service.conversations.list_attached_files.side_effect = BadRequestError(
        message="Those files cannot be attached"
    )
    with pytest.raises(BadRequestError, match="cannot be attached"):
        await room.service.post(
            room.ctx, room.topic.id, request(agent_id=uuid4(), file_ids=[uuid4()]), room.user
        )
    room.add_message.assert_not_awaited()
    room.enqueue.assert_not_awaited()
    assert room.rows == []


async def test_thread_reply_notifies_once_and_direct_mentions_are_not_duplicated(
    multiplayer, monkeypatch
):
    from app.services.room_thread import RoomThreadService

    m, room = multiplayer, multiplayer.room
    root_id = uuid4()
    room.message.thread_root_message_id = root_id
    replyable = AsyncMock()
    notify = AsyncMock()
    monkeypatch.setattr(RoomThreadService, "assert_replyable", replyable)
    monkeypatch.setattr(RoomThreadService, "reply_saved", notify)
    data = request(thread_root_message_id=root_id, mentions=refs(m.human))

    first = await room.service.post(room.ctx, room.topic.id, data, room.user)
    again = await room.service.post(room.ctx, room.topic.id, data, room.user)

    assert first == again
    replyable.assert_awaited_once_with(room.topic.id, root_id)
    notify.assert_awaited_once_with(
        organization_id=room.ctx.organization_id,
        conversation_id=room.topic.id,
        root_message_id=root_id,
        reply_message_id=room.message.id,
        actor_user_id=room.ctx.subject_id,
        sender="Writer",
        excluded_user_ids={m.human.id},
    )
    m.notify.assert_awaited_once()


@pytest.mark.security
async def test_archived_thread_refuses_new_posts_before_saving_or_queuing(room, monkeypatch):
    from app.services.room_thread import RoomThreadService

    monkeypatch.setattr(
        RoomThreadService,
        "assert_replyable",
        AsyncMock(side_effect=BadRequestError(message="Thread is archived")),
    )
    with pytest.raises(BadRequestError, match="archived"):
        await room.service.post(
            room.ctx,
            room.topic.id,
            request(thread_root_message_id=uuid4(), agent_id=uuid4()),
            room.user,
        )
    room.add_message.assert_not_awaited()
    room.enqueue.assert_not_awaited()


@pytest.mark.security
async def test_archiving_a_thread_revokes_an_already_queued_agents_reply(room, monkeypatch):
    from app.services.room_thread import RoomThreadService

    row = pending(room)
    root_id = uuid4()
    room.message.thread_root_message_id = root_id
    row.fingerprint = module.fingerprint(
        request(agent_id=row.agent_id, thread_root_message_id=root_id)
    )
    monkeypatch.setattr(module, "acting_member", AsyncMock(return_value=room.ctx))
    monkeypatch.setattr(
        module.conversation_repo, "get_message_by_id", AsyncMock(return_value=room.message)
    )
    replyable = AsyncMock(side_effect=BadRequestError(message="Thread is archived"))
    monkeypatch.setattr(RoomThreadService, "assert_replyable", replyable)
    with pytest.raises(BadRequestError, match="archived"):
        await room.service.authority(row)
    replyable.assert_awaited_once_with(room.topic.id, root_id)
