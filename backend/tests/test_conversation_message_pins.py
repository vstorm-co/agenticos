"""Reader-scoped message pins, authorized as transcript reads."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.conversation import Message
from app.repositories import conversation as conversation_repo
from app.repositories import conversation_message_pin as pin_repo
from app.repositories import message_rating as message_rating_repo
from app.services.conversation import ConversationService
from app.services.conversation_message_pin import ConversationMessagePinService
from app.services.message_history import REFUSED_TURN

pytestmark = pytest.mark.anyio


async def test_a_pin_deleted_before_readback_returns_message_not_found(
    service: ConversationMessagePinService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pin_repo, "get_message_pin", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="Message not found") as refused:
        await service.pin_message(
            CONVERSATION_ID,
            MESSAGE_ID,
            organization_id=ORG_ID,
            user_id=USER_ID,
            ctx=_ctx(),
        )
    assert refused.value.details == {"message_id": MESSAGE_ID}


async def test_unpin_write_deletes_only_the_requested_readers_message() -> None:
    from sqlalchemy.dialects import postgresql

    db = AsyncMock()
    await pin_repo.set_message_pin(
        db,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
        pinned=False,
    )
    statement = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert str(statement).startswith("DELETE FROM conversation_message_pins WHERE ")
    assert set(statement.params.values()) == {USER_ID, CONVERSATION_ID, MESSAGE_ID}
    assert "conversation_message_pins.user_id =" in str(statement)
    assert "conversation_message_pins.conversation_id =" in str(statement)
    assert "conversation_message_pins.message_id =" in str(statement)
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


async def test_empty_transcript_page_needs_no_pin_lookup() -> None:
    db = AsyncMock()
    assert (
        await pin_repo.message_pin_ids(
            db, user_id=USER_ID, conversation_id=CONVERSATION_ID, message_ids=[]
        )
        == set()
    )
    db.execute.assert_not_awaited()


def test_pin_debug_representation_identifies_reader_conversation_and_message() -> None:
    from app.db.models.conversation_message_pin import ConversationMessagePin

    pin = ConversationMessagePin(
        user_id=USER_ID, conversation_id=CONVERSATION_ID, message_id=MESSAGE_ID
    )
    assert repr(pin) == (
        f"<ConversationMessagePin(user_id={USER_ID}, "
        f"conversation_id={CONVERSATION_ID}, message_id={MESSAGE_ID})>"
    )


ORG_ID = uuid4()
USER_ID = uuid4()
CONVERSATION_ID = uuid4()
MESSAGE_ID = uuid4()
THREAD_ROOT_ID = uuid4()
OTHER_CONVERSATION_ID = uuid4()


def _ctx() -> AuthContext:
    return AuthContext(user_id=USER_ID, organization_id=ORG_ID, role="member")


def _message(*, conversation_id=CONVERSATION_ID, refused: bool = False):
    return SimpleNamespace(
        id=MESSAGE_ID,
        conversation_id=conversation_id,
        role="assistant",
        content="private answer text",
        model_content="normalized answer text",
        guardrail_refused=refused,
        thread_root_message_id=None,
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
    )


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> ConversationMessagePinService:
    service = ConversationMessagePinService(AsyncMock())
    conversation = SimpleNamespace(id=CONVERSATION_ID)
    monkeypatch.setattr(
        service.conversations, "get_conversation", AsyncMock(return_value=conversation)
    )
    monkeypatch.setattr(conversation_repo, "get_message_by_id", AsyncMock(return_value=_message()))
    monkeypatch.setattr(pin_repo, "set_message_pin", AsyncMock())
    monkeypatch.setattr(
        pin_repo,
        "get_message_pin",
        AsyncMock(
            return_value=SimpleNamespace(
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                message_id=MESSAGE_ID,
                created_at=datetime(2026, 11, 17, tzinfo=UTC),
            )
        ),
    )
    monkeypatch.setattr(pin_repo, "list_message_pins", AsyncMock(return_value=([], 0)))
    return service


async def test_listing_requires_the_existing_read_path_and_projects_live_message_metadata(
    service: ConversationMessagePinService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = SimpleNamespace(created_at=datetime(2026, 11, 16, tzinfo=UTC))
    monkeypatch.setattr(
        pin_repo,
        "list_message_pins",
        AsyncMock(return_value=([(pin, _message())], 1)),
    )

    page = await service.list_message_pins(
        CONVERSATION_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        skip=0,
        limit=50,
        ctx=_ctx(),
    )

    assert page.total == 1
    assert page.items[0].preview == "normalized answer text"
    assert service.conversations.get_conversation.await_args.kwargs == {
        "organization_id": ORG_ID,
        "user_id": USER_ID,
        "include_favourite": False,
        "ctx": _ctx(),
    }
    assert pin_repo.list_message_pins.await_args.kwargs == {
        "user_id": USER_ID,
        "conversation_id": CONVERSATION_ID,
        "skip": 0,
        "limit": 50,
    }


async def test_a_pin_is_idempotent_at_the_repository_boundary_and_redacts_a_refused_turn(
    service: ConversationMessagePinService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        conversation_repo, "get_message_by_id", AsyncMock(return_value=_message(refused=True))
    )

    result = await service.pin_message(
        CONVERSATION_ID,
        MESSAGE_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        ctx=_ctx(),
    )

    assert result.preview == REFUSED_TURN
    assert pin_repo.set_message_pin.await_args.kwargs == {
        "user_id": USER_ID,
        "conversation_id": CONVERSATION_ID,
        "message_id": MESSAGE_ID,
        "pinned": True,
    }
    assert pin_repo.get_message_pin.await_count == 1


async def test_a_message_from_another_conversation_is_missing_and_cannot_be_pinned(
    service: ConversationMessagePinService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        conversation_repo,
        "get_message_by_id",
        AsyncMock(return_value=_message(conversation_id=OTHER_CONVERSATION_ID)),
    )

    with pytest.raises(NotFoundError):
        await service.pin_message(
            CONVERSATION_ID,
            MESSAGE_ID,
            organization_id=ORG_ID,
            user_id=USER_ID,
            ctx=_ctx(),
        )

    pin_repo.set_message_pin.assert_not_awaited()


async def test_unpinning_an_absent_pin_is_harmless_after_authorization(
    service: ConversationMessagePinService,
) -> None:
    await service.unpin_message(
        CONVERSATION_ID,
        MESSAGE_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        ctx=_ctx(),
    )

    assert pin_repo.set_message_pin.await_args.kwargs["pinned"] is False


def _transcript_message(
    *, message_id: UUID = MESSAGE_ID, thread_root_message_id: UUID | None = None
) -> Message:
    created_at = datetime(2026, 11, 17, tzinfo=UTC)
    return Message(
        id=message_id,
        conversation_id=CONVERSATION_ID,
        role="assistant",
        content="current answer",
        thread_root_message_id=thread_root_message_id,
        interrupted=False,
        created_at=created_at,
        updated_at=created_at,
    )


def _mock_transcript_reads(
    monkeypatch: pytest.MonkeyPatch,
    service: ConversationService,
    *,
    messages: list[Message],
) -> None:
    monkeypatch.setattr(
        service,
        "get_conversation",
        AsyncMock(return_value=SimpleNamespace(id=CONVERSATION_ID)),
    )
    monkeypatch.setattr(
        conversation_repo, "get_messages_by_conversation", AsyncMock(return_value=messages)
    )
    monkeypatch.setattr(conversation_repo, "count_messages", AsyncMock(return_value=len(messages)))
    monkeypatch.setattr(conversation_repo, "run_outcomes", AsyncMock(return_value={}))
    monkeypatch.setattr(conversation_repo, "thread_summaries", AsyncMock(return_value={}))
    monkeypatch.setattr(pin_repo, "message_pin_ids", AsyncMock(return_value={MESSAGE_ID}))
    monkeypatch.setattr(
        message_rating_repo, "get_user_ratings_for_messages", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        message_rating_repo, "get_rating_counts_for_messages", AsyncMock(return_value={})
    )
    monkeypatch.setattr(service, "_attach_senders", AsyncMock())
    monkeypatch.setattr(service, "_attach_replies", AsyncMock())
    monkeypatch.setattr(service, "_cost", AsyncMock(return_value=None))


async def test_transcript_pin_status_is_enriched_for_the_authenticated_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock()
    service = ConversationService(db)
    _mock_transcript_reads(monkeypatch, service, messages=[_transcript_message()])

    items, total, _cost = await service.transcript(
        CONVERSATION_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        ctx=_ctx(),
    )

    assert total == 1
    assert items[0].is_pinned is True
    pin_repo.message_pin_ids.assert_awaited_once_with(
        db,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        message_ids=[MESSAGE_ID],
    )


async def test_room_thread_transcript_enriches_its_root_and_replies_for_the_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock()
    service = ConversationService(db)
    root = _transcript_message(message_id=THREAD_ROOT_ID)
    reply = _transcript_message(message_id=MESSAGE_ID, thread_root_message_id=THREAD_ROOT_ID)
    _mock_transcript_reads(monkeypatch, service, messages=[reply])
    monkeypatch.setattr(conversation_repo, "get_thread_root", AsyncMock(return_value=root))
    monkeypatch.setattr(
        pin_repo,
        "message_pin_ids",
        AsyncMock(return_value={THREAD_ROOT_ID, MESSAGE_ID}),
    )

    items, total, _cost = await service.transcript(
        CONVERSATION_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        ctx=_ctx(),
        thread_root_message_id=THREAD_ROOT_ID,
    )

    assert total == 2
    assert [item.id for item in items] == [THREAD_ROOT_ID, MESSAGE_ID]
    assert [item.is_pinned for item in items] == [True, True]
    assert pin_repo.message_pin_ids.await_args.kwargs["message_ids"] == [THREAD_ROOT_ID, MESSAGE_ID]


@pytest.mark.parametrize("for_model", [False, True])
async def test_transcript_does_not_query_or_expose_personal_pin_status_outside_personal_reads(
    monkeypatch: pytest.MonkeyPatch,
    for_model: bool,
) -> None:
    db = AsyncMock()
    service = ConversationService(db)
    _mock_transcript_reads(monkeypatch, service, messages=[_transcript_message()])

    items, _total, _cost = await service.transcript(
        CONVERSATION_ID,
        organization_id=ORG_ID,
        user_id=USER_ID if for_model else None,
        ctx=_ctx() if for_model else None,
        for_model=for_model,
    )

    pin_repo.message_pin_ids.assert_not_awaited()
    if for_model:
        assert items[0].is_pinned is None
    else:
        assert isinstance(items[0], Message)
