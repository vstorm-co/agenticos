"""Room socket authorization when transcript context imports another room."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services import agent_session as agent_session_module
from app.services import chat_room
from app.services.agent_session import AgentSession

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_CONVERSATION = "11111111-1111-1111-1111-111111111111"


def _session() -> AgentSession:
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    user = SimpleNamespace(id=uuid4())
    organization = SimpleNamespace(id=uuid4())
    return AgentSession(websocket, user, organization)


async def test_imported_room_rechecks_after_source_access_is_revoked() -> None:
    session = _session()
    session._room_has_imported_thread_context = True
    # Simulate a successful check cached before the source access was revoked.
    session._reads_until = time.monotonic() + agent_session_module.ROOM_READS_FOR_SECONDS
    session._still_reads = AsyncMock(side_effect=[True, False])

    assert await session._reads_lately(_CONVERSATION)
    assert not await session._reads_lately(_CONVERSATION)

    assert session._still_reads.await_count == 2
    assert session._reads_until == float("-inf")


async def test_unbound_room_keeps_the_short_positive_cache() -> None:
    session = _session()
    session._room_has_imported_thread_context = False
    session._reads_until = time.monotonic() + agent_session_module.ROOM_READS_FOR_SECONDS
    session._still_reads = AsyncMock(return_value=False)

    assert await session._reads_lately(_CONVERSATION)

    session._still_reads.assert_not_awaited()


async def test_room_thread_event_invalidates_cache_and_refreshes_context(monkeypatch) -> None:
    session = _session()
    session._room = _CONVERSATION
    session._room_has_imported_thread_context = False
    session._reads_until = time.monotonic() + agent_session_module.ROOM_READS_FOR_SECONDS
    session._still_reads = AsyncMock(return_value=False)
    refreshed: list[str] = []

    async def room_events(_conversation_id: str):
        yield {
            "type": chat_room.ROOM_THREAD,
            "thread_root_message_id": str(uuid4()),
        }

    async def refresh_context(conversation_id: str) -> None:
        refreshed.append(conversation_id)
        session._room_has_imported_thread_context = True

    present = AsyncMock(return_value=[])
    leave = AsyncMock()
    monkeypatch.setattr(agent_session_module.chat_room, "present", present)
    monkeypatch.setattr(agent_session_module.chat_room, "events", room_events)
    monkeypatch.setattr(agent_session_module.chat_room, "leave", leave)
    monkeypatch.setattr(session, "_refresh_room_context_access", refresh_context)

    await session._hear_room(_CONVERSATION)

    assert refreshed == [_CONVERSATION]
    session._still_reads.assert_awaited_once_with(_CONVERSATION)
    leave.assert_awaited_once_with(_CONVERSATION, session.user.id, session._socket)
    session.websocket.send_json.assert_not_awaited()
