"""Authorized reads keep selected thread context complete and repairable."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.repositories import conversation as conversation_repo
from app.repositories import room_message_reaction as reaction_repo
from app.repositories import room_thread as thread_repo
from app.services.room_thread_context_read import RoomThreadContextReadService

pytestmark = pytest.mark.anyio


def _actor(organization_id: UUID) -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=organization_id, role="member")


def _conversation(organization_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        project_id=None,
        room_visibility="private",
        is_archived=False,
    )


def _saved_context(
    destination: SimpleNamespace, source: SimpleNamespace, root_message_id: UUID
) -> SimpleNamespace:
    message_ids = [uuid4(), uuid4()]
    return SimpleNamespace(
        organization_id=destination.organization_id,
        conversation_id=destination.id,
        root_message_id=root_message_id,
        context_source_conversation_id=source.id,
        context_start_message_id=message_ids[0],
        context_end_message_id=message_ids[-1],
        context_first_ordinal=10,
        context_last_ordinal=20,
        context_excluded_message_ids=[],
        context_message_ids=message_ids,
        context_moved=True,
        context_revision=4,
    )


def _message(message_id: UUID, conversation_id: UUID) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=message_id,
        conversation_id=conversation_id,
        role="user",
        content=f"Selected message {message_id}",
        created_at=now,
        updated_at=now,
    )


def _service(
    monkeypatch: pytest.MonkeyPatch,
    mock_db_session: AsyncMock,
    *,
    destination: SimpleNamespace,
    root: SimpleNamespace,
    actor: AuthContext,
) -> RoomThreadContextReadService:
    service = RoomThreadContextReadService(mock_db_session)
    monkeypatch.setattr(
        service.threads,
        "_conversation_and_root",
        AsyncMock(return_value=(destination, root, destination.organization_id, actor.user_id)),
    )
    monkeypatch.setattr(service.access, "assert_visible", AsyncMock())
    monkeypatch.setattr(service.conversations, "_attach_senders", AsyncMock())
    monkeypatch.setattr(service.conversations, "_attach_replies", AsyncMock())
    monkeypatch.setattr(reaction_repo, "list_aggregates", AsyncMock(return_value={}))
    return service


async def test_an_ordinary_thread_has_no_separate_context(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    organization_id = uuid4()
    destination = _conversation(organization_id)
    actor = _actor(organization_id)
    root = SimpleNamespace(id=uuid4(), author_user_id=actor.user_id)
    service = _service(
        monkeypatch, mock_db_session, destination=destination, root=root, actor=actor
    )
    row = SimpleNamespace(context_source_conversation_id=None)
    monkeypatch.setattr(thread_repo, "get_thread", AsyncMock(return_value=row))

    context, messages = await service.detail(actor, destination.id, root.id)
    history_scope = await service.assert_history(destination=destination, root_message_id=root.id)

    assert context is None
    assert messages == []
    assert history_scope is None
    assert not service.access.assert_visible.await_args_list


@pytest.mark.security
@pytest.mark.parametrize("source_exists", [False, True])
async def test_context_refuses_a_missing_or_cross_tenant_source(
    source_exists: bool,
    monkeypatch: pytest.MonkeyPatch,
    mock_db_session: AsyncMock,
) -> None:
    organization_id = uuid4()
    destination = _conversation(organization_id)
    actor = _actor(organization_id)
    root = SimpleNamespace(id=uuid4(), author_user_id=actor.user_id)
    service = _service(
        monkeypatch, mock_db_session, destination=destination, root=root, actor=actor
    )
    source_id = uuid4()
    row_source = SimpleNamespace(id=source_id)
    row = _saved_context(destination, row_source, root.id)
    source = SimpleNamespace(id=source_id, organization_id=uuid4()) if source_exists else None
    monkeypatch.setattr(thread_repo, "get_thread", AsyncMock(return_value=row))
    monkeypatch.setattr(conversation_repo, "get_conversation_by_id", AsyncMock(return_value=source))

    with pytest.raises(NotFoundError, match="Thread context is unavailable"):
        await service.detail(actor, destination.id, root.id)

    assert not service.access.assert_visible.await_args_list


@pytest.mark.parametrize("stale", [False, True])
async def test_detail_keeps_snapshot_metadata_and_never_returns_partial_rows(
    stale: bool,
    monkeypatch: pytest.MonkeyPatch,
    mock_db_session: AsyncMock,
) -> None:
    organization_id = uuid4()
    destination = _conversation(organization_id)
    source = _conversation(organization_id)
    actor = _actor(organization_id)
    root = SimpleNamespace(id=uuid4(), author_user_id=actor.user_id)
    service = _service(
        monkeypatch, mock_db_session, destination=destination, root=root, actor=actor
    )
    row = _saved_context(destination, source, root.id)
    messages = [_message(message_id, source.id) for message_id in row.context_message_ids]
    monkeypatch.setattr(thread_repo, "get_thread", AsyncMock(return_value=row))
    monkeypatch.setattr(conversation_repo, "get_conversation_by_id", AsyncMock(return_value=source))
    monkeypatch.setattr(
        thread_repo,
        "context_messages",
        AsyncMock(return_value=messages[:-1] if stale else messages),
    )

    context, body = await service.detail(actor, destination.id, root.id)

    assert context is not None
    assert context.message_ids == row.context_message_ids
    assert context.message_count == len(row.context_message_ids)
    assert context.revision == row.context_revision
    assert context.stale is stale
    assert [message.id for message in body] == ([] if stale else row.context_message_ids)


@pytest.mark.security
async def test_model_history_fails_closed_for_stale_context_and_checks_responder(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    organization_id = uuid4()
    destination = _conversation(organization_id)
    source = _conversation(organization_id)
    actor = _actor(organization_id)
    root = SimpleNamespace(id=uuid4(), author_user_id=actor.user_id)
    responder_agent_id = uuid4()
    service = _service(
        monkeypatch, mock_db_session, destination=destination, root=root, actor=actor
    )
    row = _saved_context(destination, source, root.id)
    monkeypatch.setattr(thread_repo, "get_thread", AsyncMock(return_value=row))
    monkeypatch.setattr(conversation_repo, "get_conversation_by_id", AsyncMock(return_value=source))
    monkeypatch.setattr(conversation_repo, "context_snapshot_exists", AsyncMock(return_value=False))

    with pytest.raises(ConflictError, match="saved context changed") as raised:
        await service.assert_history(
            destination=destination,
            root_message_id=root.id,
            actor=actor,
            responder_agent_id=responder_agent_id,
        )

    assert raised.value.details == {"reason": "stale_context"}
    access_args = service.access.assert_visible.await_args
    assert access_args is not None
    assert access_args.kwargs["actor"] is actor
    assert access_args.kwargs["responder_agent_id"] == responder_agent_id


@pytest.mark.security
async def test_candidates_refuse_a_non_manager(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    organization_id = uuid4()
    destination = _conversation(organization_id)
    actor = _actor(organization_id)
    root = SimpleNamespace(id=uuid4(), author_user_id=uuid4())
    service = _service(
        monkeypatch, mock_db_session, destination=destination, root=root, actor=actor
    )
    monkeypatch.setattr(service.threads.participants, "_can_post", AsyncMock(return_value=True))
    monkeypatch.setattr(service.threads.participants, "_can_manage", AsyncMock(return_value=False))
    candidates = AsyncMock(return_value=[])
    monkeypatch.setattr(thread_repo, "context_candidates", candidates)

    with pytest.raises(AuthorizationError, match="thread starter or a room manager"):
        await service.candidates(actor, destination.id, root.id)

    assert not candidates.await_args_list


async def test_candidates_offer_live_rows_to_replace_a_stale_snapshot(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    organization_id = uuid4()
    destination = _conversation(organization_id)
    source = _conversation(organization_id)
    actor = _actor(organization_id)
    root = SimpleNamespace(id=uuid4(), author_user_id=actor.user_id)
    service = _service(
        monkeypatch, mock_db_session, destination=destination, root=root, actor=actor
    )
    monkeypatch.setattr(service.threads.participants, "_can_post", AsyncMock(return_value=True))
    row = _saved_context(destination, source, root.id)
    live_messages = [
        _message(row.context_message_ids[0], source.id),
        _message(uuid4(), source.id),
    ]
    monkeypatch.setattr(thread_repo, "get_thread", AsyncMock(return_value=row))
    monkeypatch.setattr(conversation_repo, "get_conversation_by_id", AsyncMock(return_value=source))
    monkeypatch.setattr(thread_repo, "context_candidates", AsyncMock(return_value=live_messages))

    result = await service.candidates(actor, destination.id, root.id)

    assert result.source_conversation_id == source.id
    assert result.total == len(live_messages)
    assert [message.id for message in result.items] == [message.id for message in live_messages]
