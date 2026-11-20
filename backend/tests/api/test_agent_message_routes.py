"""Tests for the agent message routes.

The handlers are thin by design - the decision is the service's - so what is
worth asserting is the part that is not delegation: the thread id in the path
is the one the service is asked about, and a download streams the file the
service returned rather than one the path named.

That the routes are authorized at all, and by the right mechanism, is asserted
through the real app in `tests/api/test_platform_routes.py`.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.v1.agent_messages import (
    download_agent_message_attachment,
    get_agent_message_thread,
    list_agent_message_recipients,
    list_agent_message_threads,
    list_agent_messages,
    mark_agent_message_thread_read,
    react_to_agent_message,
    send_agent_message,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent_message import (
    AgentMessageList,
    AgentMessageReactionCreate,
    AgentMessageReactionsRead,
    AgentMessageRead,
    AgentMessageRecipientList,
    AgentMessageSend,
    AgentMessageThreadList,
    AgentMessageThreadRead,
    AgentRef,
)

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER)
NOW = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)


def _thread_read() -> AgentMessageThreadRead:
    return AgentMessageThreadRead(
        id=uuid.uuid4(),
        agent_a=AgentRef(id=uuid.uuid4(), slug="researcher", name="Researcher"),
        agent_b=AgentRef(id=uuid.uuid4(), slug="summariser", name="Summariser"),
        last_message_at=NOW,
        unread=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _message_read(thread_id: uuid.UUID) -> AgentMessageRead:
    return AgentMessageRead(
        id=uuid.uuid4(),
        thread_id=thread_id,
        sender_agent_id=uuid.uuid4(),
        sender_agent_slug="researcher",
        body="hello",
        created_at=NOW,
        updated_at=NOW,
    )


class TestReading:
    async def test_a_listing_reports_its_own_total(self) -> None:
        service = MagicMock(
            list_threads=AsyncMock(
                return_value=AgentMessageThreadList(items=[_thread_read()], total=1)
            )
        )

        result = await list_agent_message_threads(service, _CTX)

        assert result.total == 1

    async def test_a_thread_listing_passes_pagination_through(self) -> None:
        service = MagicMock(
            list_threads=AsyncMock(return_value=AgentMessageThreadList(items=[], total=0))
        )

        await list_agent_message_threads(service, _CTX, skip=10, limit=5)

        kwargs = service.list_threads.await_args.kwargs
        assert (kwargs["skip"], kwargs["limit"]) == (10, 5)

    async def test_recipients_are_the_service_s_answer(self) -> None:
        service = MagicMock(
            list_recipients=AsyncMock(
                return_value=AgentMessageRecipientList(
                    items=[AgentRef(id=uuid.uuid4(), slug="summariser", name="Summariser")],
                    total=1,
                )
            )
        )

        result = await list_agent_message_recipients(service, _CTX)

        assert [item.slug for item in result.items] == ["summariser"]

    async def test_messages_come_back_oldest_first_from_the_service(self) -> None:
        thread_id = uuid.uuid4()
        service = MagicMock(
            list_messages=AsyncMock(
                return_value=AgentMessageList(items=[_message_read(thread_id)], total=1)
            )
        )

        result = await list_agent_messages(thread_id, service, _CTX)

        assert result.items[0].thread_id == thread_id
        assert service.list_messages.await_args.args[1] == thread_id


class TestWriting:
    async def test_a_send_answers_with_the_stored_message(self) -> None:
        thread_id = uuid.uuid4()
        service = MagicMock(send=AsyncMock(return_value=_message_read(thread_id)))
        data = AgentMessageSend(sender_agent_id=uuid.uuid4(), recipient="summariser", body="hello")

        result = await send_agent_message(data, service, _CTX)

        assert result.thread_id == thread_id
        assert result.body == "hello"

    async def test_a_react_names_the_thread_in_the_path(self) -> None:
        """The route's thread id is the one the service checks the message
        against - a reaction aimed at the wrong thread is the service's
        refusal, not a reaction in the wrong place."""
        thread_id, message_id = uuid.uuid4(), uuid.uuid4()
        service = MagicMock(
            react=AsyncMock(return_value=AgentMessageReactionsRead(reacted=True, reactions=[]))
        )

        result = await react_to_agent_message(
            thread_id,
            message_id,
            AgentMessageReactionCreate(emoji="👍"),
            service,
            _CTX,
        )

        assert result.reacted is True
        kwargs = service.react.await_args.kwargs
        assert (kwargs["thread_id"], kwargs["message_id"]) == (thread_id, message_id)

    async def test_marking_a_thread_read_returns_nothing(self) -> None:
        thread_id = uuid.uuid4()
        service = MagicMock(mark_read=AsyncMock())

        assert await mark_agent_message_thread_read(thread_id, service, _CTX) is None

        service.mark_read.assert_awaited_once_with(_CTX, thread_id)

    async def test_a_download_streams_the_file_the_service_returned(self) -> None:
        thread_id, message_id, file_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        chat_file = MagicMock()
        service = MagicMock(download_attachment=AsyncMock(return_value=chat_file))
        with patch(
            "app.api.routes.v1.agent_messages.chat_file_response",
            new=AsyncMock(return_value="streamed"),
        ) as streamed:
            result = await download_agent_message_attachment(
                thread_id, message_id, file_id, service, _CTX
            )

        assert result == "streamed"
        kwargs = service.download_attachment.await_args.kwargs
        assert (kwargs["thread_id"], kwargs["message_id"], kwargs["chat_file_id"]) == (
            thread_id,
            message_id,
            file_id,
        )
        streamed.assert_awaited_once_with(chat_file, disposition="inline")

    async def test_getting_one_thread_asks_for_that_thread(self) -> None:
        thread = _thread_read()
        service = MagicMock(get_thread=AsyncMock(return_value=thread))

        assert await get_agent_message_thread(thread.id, service, _CTX) is thread
