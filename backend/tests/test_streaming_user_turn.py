"""What the streaming socket writes as the user's turn.

`persist_user_turn` is the one write site that does not go through
`TranscriptService.record`, so it composes the same named body itself when a
message arrives blank beside its files (#750). The dashboard's composer
substitutes a placeholder before sending, so only a raw WebSocket client ever
reaches this - which is exactly why it went unnoticed.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from app.services.agent import persist_user_turn
from app.services.conversation import ConversationService

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _db_context():
    yield MagicMock()


def _service(attached):
    service = create_autospec(ConversationService, instance=True)
    service.create_conversation.return_value = MagicMock(id=uuid.uuid4())
    service.add_message.return_value = MagicMock(id=uuid.uuid4())
    service.list_attached_files.return_value = attached
    return service


async def _persist(service, message, file_ids):
    with (
        patch("app.services.agent.get_db_context", _db_context),
        patch("app.services.agent.get_conversation_service", return_value=service),
    ):
        return await persist_user_turn(
            MagicMock(id=uuid.uuid4()),
            message,
            file_ids,
            requested_conversation_id=None,
            current_conversation_id=None,
            organization_id=uuid.uuid4(),
        )


async def test_a_blank_message_beside_files_is_written_naming_what_arrived():
    """A photo sent with no words off a raw client is a turn somebody took.

    Same body, same vocabulary as `TranscriptService.record` writes for the
    non-streaming surfaces - a blank user message reads as somebody sending
    nothing (#750).
    """
    service = _service(
        [
            MagicMock(file_type="image", filename="photo.jpg"),
            MagicMock(file_type="spreadsheet", filename="q3.xlsx"),
        ]
    )

    await _persist(service, "", ["f1", "f2"])

    written = service.add_message.call_args.args[1]
    assert (written.role, written.content) == (
        "user",
        "Attached image: photo.jpg\nAttached file: q3.xlsx",
    )


async def test_a_typed_message_is_never_replaced():
    """The naming fills only a turn that said nothing; words stay verbatim."""
    service = _service([MagicMock(file_type="image", filename="photo.jpg")])

    await _persist(service, "co tu widzisz", ["f1"])

    assert service.add_message.call_args.args[1].content == "co tu widzisz"
    service.list_attached_files.assert_not_called()


async def test_a_blank_message_with_no_files_stays_blank():
    """The session refuses this frame before persisting, but the write site must
    not invent a body on its own: nothing arrived, so there is nothing to name."""
    service = _service([])

    await _persist(service, "", [])

    assert service.add_message.call_args.args[1].content == ""
    service.list_attached_files.assert_not_called()
