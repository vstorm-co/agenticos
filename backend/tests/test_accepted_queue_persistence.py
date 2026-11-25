"""Refusal and failure behavior at the accepted queue persistence boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.services.accepted_queued_message import AcceptedQueuedMessageService
from app.services.agent import PersistedPrompt, persist_user_turn

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _database(db: object) -> AsyncIterator[object]:
    """Supply the session used by `persist_user_turn` without opening a connection."""
    yield db


def _accepted_message(
    *, conversation_id: UUID, author_user_id: UUID, role: str = "user"
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation_id,
        author_user_id=author_user_id,
        role=role,
        content="frozen accepted text",
        reply_to_message_id=None,
    )


def _service_doubles(
    *, conversation_id: UUID, message: SimpleNamespace
) -> tuple[object, SimpleNamespace, MagicMock, MagicMock]:
    db = object()
    conversation = SimpleNamespace(id=conversation_id, title="Existing personal chat")
    conversations = MagicMock()
    conversations.get_conversation = AsyncMock(return_value=conversation)
    conversations.model_text = AsyncMock(return_value=message.content)
    queued = MagicMock()
    queued.claim_for_send = AsyncMock(return_value=message)
    return db, conversation, conversations, queued


async def _persist_accepted(
    *,
    user_id: UUID,
    organization_id: UUID,
    conversation_id: UUID,
    queue_context: AuthContext | None,
) -> PersistedPrompt:
    return await persist_user_turn(
        user=SimpleNamespace(id=user_id),
        # A retry may arrive with an edited client copy. The accepted receipt is
        # authoritative, so this value must not become the prompt or transcript.
        user_message="stale client copy",
        file_ids=[],
        requested_conversation_id=str(conversation_id),
        current_conversation_id=str(conversation_id),
        organization_id=organization_id,
        accepted_queue_id=uuid4(),
        queue_context=queue_context,
    )


def _read_receipt(*, state: str = "pending") -> SimpleNamespace:
    """Build only the persisted receipt fields the schema read boundary needs."""
    receipt_id, conversation_id, client_queue_id, agent_id = uuid4(), uuid4(), uuid4(), uuid4()
    quoted_message_id = uuid4()
    excerpt = "Frozen assistant answer"
    return SimpleNamespace(
        id=receipt_id,
        conversation_id=conversation_id,
        client_queue_id=client_queue_id,
        agent_id=agent_id,
        payload={
            "client_queue_id": str(client_queue_id),
            "agent_id": str(agent_id),
            "content": "frozen accepted text",
            "file_ids": [],
            "mentions": [],
            "reply_to_message_id": str(quoted_message_id),
            "reply_to_excerpt": excerpt,
            "quote_snapshot": {
                "message_id": str(quoted_message_id),
                "role": "assistant",
                "excerpt": excerpt,
            },
        },
        state=state,
        message_id=None,
        steering_run_id=None,
        created_at=datetime(2026, 11, 25, tzinfo=UTC),
    )


async def test_read_preserves_a_valid_frozen_assistant_quote_and_state() -> None:
    receipt = _read_receipt()

    read = AcceptedQueuedMessageService(object())._read(receipt)

    assert read.state == "pending"
    assert read.reply_to_role == "assistant"
    assert read.quote_excerpt == "Frozen assistant answer"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        (
            "quote_snapshot",
            {"role": "assistant", "excerpt": "Frozen assistant answer"},
            AlreadyExistsError,
        ),
        ("state", "corrupt", ValidationError),
    ],
)
async def test_read_refuses_malformed_quote_snapshot_or_stored_state(
    field: str, value: object, error: type[Exception]
) -> None:
    receipt = _read_receipt()
    if field == "quote_snapshot":
        receipt.payload[field] = value
    else:
        receipt.state = value

    with pytest.raises(error):
        AcceptedQueuedMessageService(object())._read(receipt)


@pytest.mark.security
@pytest.mark.parametrize("mismatch", ["missing", "other_owner", "other_organization"])
async def test_a_receipt_cannot_be_claimed_through_another_identity(mismatch: str) -> None:
    user_id, organization_id, conversation_id = uuid4(), uuid4(), uuid4()
    message = _accepted_message(conversation_id=conversation_id, author_user_id=user_id)
    db, _conversation, conversations, queued = _service_doubles(
        conversation_id=conversation_id, message=message
    )
    if mismatch == "missing":
        context = None
    elif mismatch == "other_owner":
        context = AuthContext(user_id=uuid4(), organization_id=organization_id, role="owner")
    else:
        context = AuthContext(user_id=user_id, organization_id=uuid4(), role="owner")

    with (
        patch("app.services.agent.get_db_context", side_effect=lambda: _database(db)),
        patch("app.services.agent.ConversationService", return_value=conversations),
        patch("app.services.agent.AcceptedQueuedMessageService", return_value=queued),
        pytest.raises(AuthorizationError, match="not yours"),
    ):
        await _persist_accepted(
            user_id=user_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            queue_context=context,
        )

    queued.claim_for_send.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("mismatch", ["conversation", "author", "role"])
async def test_a_claimed_receipt_must_return_its_own_user_message(mismatch: str) -> None:
    user_id, organization_id, conversation_id = uuid4(), uuid4(), uuid4()
    message = _accepted_message(conversation_id=conversation_id, author_user_id=user_id)
    if mismatch == "conversation":
        message.conversation_id = uuid4()
    elif mismatch == "author":
        message.author_user_id = uuid4()
    else:
        message.role = "assistant"
    db, _conversation, conversations, queued = _service_doubles(
        conversation_id=conversation_id, message=message
    )
    context = AuthContext(user_id=user_id, organization_id=organization_id, role="owner")

    with (
        patch("app.services.agent.get_db_context", side_effect=lambda: _database(db)),
        patch("app.services.agent.ConversationService", return_value=conversations),
        patch("app.services.agent.AcceptedQueuedMessageService", return_value=queued),
        pytest.raises(NotFoundError, match="Accepted queued message not found"),
    ):
        await _persist_accepted(
            user_id=user_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            queue_context=context,
        )

    queued.claim_for_send.assert_awaited_once()
    conversations.model_text.assert_not_awaited()


async def test_a_database_error_while_claiming_an_accepted_receipt_reaches_the_caller() -> None:
    user_id, organization_id, conversation_id = uuid4(), uuid4(), uuid4()
    message = _accepted_message(conversation_id=conversation_id, author_user_id=user_id)
    db, _conversation, conversations, queued = _service_doubles(
        conversation_id=conversation_id, message=message
    )
    failure = SQLAlchemyError("database unavailable")
    queued.claim_for_send = AsyncMock(side_effect=failure)
    context = AuthContext(user_id=user_id, organization_id=organization_id, role="owner")

    with (
        patch("app.services.agent.get_db_context", side_effect=lambda: _database(db)),
        patch("app.services.agent.ConversationService", return_value=conversations),
        patch("app.services.agent.AcceptedQueuedMessageService", return_value=queued),
        pytest.raises(SQLAlchemyError) as raised,
    ):
        await _persist_accepted(
            user_id=user_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            queue_context=context,
        )

    assert raised.value is failure
