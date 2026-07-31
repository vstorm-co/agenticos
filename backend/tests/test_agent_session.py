"""Tests for the chat WebSocket session's agent-only contract.

The template's general assistant used to answer any frame that named no agent.
It is gone: the factory is the only way to get a runnable agent, so a frame
without an `agent_id` is refused before anything is persisted. These pin the
refusal - the transcript must not collect messages nothing will answer.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_session import AgentSession

pytestmark = pytest.mark.anyio


def _session() -> AgentSession:
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    user = MagicMock()
    organization = MagicMock()
    return AgentSession(websocket, user, organization)


def _sent_events(session: AgentSession) -> list[tuple[str, dict]]:
    return [
        (call.args[0]["type"], call.args[0]["data"])
        for call in session.websocket.send_json.call_args_list
    ]


class TestFramesWithoutAnAgent:
    async def test_a_frame_naming_no_agent_is_refused_before_anything_is_persisted(self):
        """There is no assistant to fall back to, and a message nothing will
        answer does not belong in the transcript."""
        session = _session()

        with patch("app.services.agent_session.persist_user_turn", new=AsyncMock()) as persist:
            await session.process_message({"message": "hello"})

        events = _sent_events(session)
        assert len(events) == 1
        event_type, data = events[0]
        assert event_type == "error"
        assert "Pick an agent" in data["message"]
        persist.assert_not_called()

    async def test_a_frame_naming_something_that_is_not_an_agent_id_is_refused(self):
        """Ignoring a malformed id would silently run something the user never
        picked; refusing it names the problem."""
        session = _session()

        with patch("app.services.agent_session.persist_user_turn", new=AsyncMock()) as persist:
            await session.process_message({"message": "hello", "agent_id": "not-a-uuid"})

        events = _sent_events(session)
        assert len(events) == 1
        event_type, data = events[0]
        assert event_type == "error"
        assert "not a valid agent id" in data["message"]
        persist.assert_not_called()

    async def test_an_empty_frame_is_still_refused_as_empty(self):
        """The emptiness check stays first: a blank frame is a client bug, not
        a missing agent."""
        session = _session()

        await session.process_message({"message": ""})

        events = _sent_events(session)
        assert events == [("error", {"message": "Empty message"})]
