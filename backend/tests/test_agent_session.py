"""Tests for the chat WebSocket session's agent-only contract.

The template's general assistant used to answer any frame that named no agent.
It is gone: the factory is the only way to get a runnable agent, so a frame
without an `agent_id` is refused before anything is persisted. These pin the
refusal - the transcript must not collect messages nothing will answer.

`TestForwardingToolEvents` is here for a different reason: this module is not in
the coverage gate, and the one field it reads off a Pydantic AI event was renamed
under it. Nothing noticed until every tool call in web chat answered "❌ Error:
'FunctionToolResultEvent' object has no attribute 'result'".
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


class TestForwardingToolEvents:
    """What a tool call looks like on the wire, read off real event objects.

    Constructed from `pydantic_ai.messages` rather than mocked, deliberately: a
    `MagicMock` answers to `.result`, `.part` and anything else, so a test built on
    one would have kept passing through exactly the rename that broke this.
    """

    async def test_a_tool_result_is_forwarded_with_its_content(self):
        from pydantic_ai.messages import (
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            ToolCallPart,
            ToolReturnPart,
        )

        session = _session()
        collected: list[dict] = []

        async def _events():
            yield FunctionToolCallEvent(
                part=ToolCallPart(
                    tool_name="write_file", args={"path": "/a.txt"}, tool_call_id="t1"
                )
            )
            yield FunctionToolResultEvent(
                part=ToolReturnPart(
                    tool_name="write_file", content="wrote /a.txt", tool_call_id="t1"
                )
            )

        await session._stream_tool_events(_events(), collected)

        assert [event for event in _sent_events(session) if event[0] == "tool_result"] == [
            ("tool_result", {"tool_call_id": "t1", "content": "wrote /a.txt"})
        ]

    async def test_the_result_is_kept_on_the_call_it_belongs_to(self):
        """The transcript persists one row per call, so a result that did not find
        its call is a tool call recorded as never having returned."""
        from pydantic_ai.messages import (
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            ToolCallPart,
            ToolReturnPart,
        )

        session = _session()
        collected: list[dict] = []

        async def _events():
            yield FunctionToolCallEvent(
                part=ToolCallPart(tool_name="ls", args={}, tool_call_id="t1")
            )
            yield FunctionToolResultEvent(
                part=ToolReturnPart(tool_name="ls", content=["/a.txt"], tool_call_id="t1")
            )

        await session._stream_tool_events(_events(), collected)

        assert collected == [
            {"tool_call_id": "t1", "tool_name": "ls", "args": {}, "result": "['/a.txt']"}
        ]

    async def test_a_retry_is_reported_rather_than_swallowed(self):
        """A tool that raised sends a `RetryPromptPart` down the same stream. It
        carries `content` too, and a card that never resolved would spin forever."""
        from pydantic_ai.messages import FunctionToolResultEvent, RetryPromptPart

        session = _session()

        async def _events():
            yield FunctionToolResultEvent(
                part=RetryPromptPart(content="path must be absolute", tool_call_id="t9")
            )

        await session._stream_tool_events(_events(), [])

        [(_type, data)] = [event for event in _sent_events(session) if event[0] == "tool_result"]
        assert data == {"tool_call_id": "t9", "content": "path must be absolute"}
