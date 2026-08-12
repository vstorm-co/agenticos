"""What a public surface puts on the wire, and what its operator can stop.

The embed speaks the dashboard's frame vocabulary since #634 - one loop, one set
of names - so a hosted page streams an answer as it arrives rather than showing a
lump of text after thirty seconds. What differs is not the loop but the *sink*:
`EmbedSession._emit` drops every kind the operator has not agreed to show.

**These tests assert the frame is absent, not invisible.** That is the whole
reason the filter is at emission: `show_thinking: false` enforced in CSS is an
agent's reasoning sitting in a stranger's devtools, and a page is exactly where a
stranger has one open. So every assertion here is about what reached
`websocket.send_json`.

One frame is refused whatever the settings, and it is a leak rather than a
preference: `user_prompt_processed` carries the prompt *as assembled*, which on
this surface is the operator's placement note and the supplied block above what
the visitor typed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent, PartStartEvent
from pydantic_ai.messages import TextPart, ThinkingPart, ToolCallPart, ToolReturnPart

from app.db.models.agent_run import RunStatus
from app.services.embed_session import EmbedSession, _no_answer, visible_frames
from app.services.run_stream import RunFrames

pytestmark = pytest.mark.anyio


def _embed(*, kind: str = "page", **config: Any) -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        name="Support",
        kind=kind,
        config={"kind": "page", **config} if kind == "page" else {"kind": kind},
    )


def _session(embed: MagicMock) -> EmbedSession:
    @asynccontextmanager
    async def sessions() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    return EmbedSession(sessions=sessions, embed=embed, visitor=None, websocket=websocket)


def _sent(session: EmbedSession) -> list[tuple[str, dict[str, Any]]]:
    return [
        (call.args[0]["type"], call.args[0]["data"])
        for call in session.websocket.send_json.await_args_list
    ]


def _kinds(session: EmbedSession) -> list[str]:
    return [kind for kind, _payload in _sent(session)]


async def _stream(session: EmbedSession, *events: Any) -> None:
    """Drive the shared request loop into this session's sink."""

    async def _events() -> AsyncIterator[Any]:
        for event in events:
            yield event

    await RunFrames(emit=session._emit).request(_events())


async def _tools(session: EmbedSession, *events: Any) -> None:
    async def _events() -> AsyncIterator[Any]:
        for event in events:
            yield event

    await RunFrames(emit=session._emit).tools(_events())


def _called() -> FunctionToolCallEvent:
    return FunctionToolCallEvent(
        part=ToolCallPart(tool_name="search_kb", args={"q": "refunds"}, tool_call_id="c1")
    )


def _returned() -> FunctionToolResultEvent:
    return FunctionToolResultEvent(
        ToolReturnPart(tool_name="search_kb", content="30 days", tool_call_id="c1")
    )


class TestAnAnswerArrivesAsItIsWritten:
    async def test_the_words_reach_the_visitor_a_delta_at_a_time(self) -> None:
        """The page showed one lump of text because the session awaited the whole
        answer, not because a public socket cannot carry more."""
        session = _session(_embed())

        await _stream(session, PartStartEvent(index=0, part=TextPart(content="Thirty ")))

        assert _sent(session) == [
            ("part_start", {"index": 0, "part_type": "TextPart"}),
            ("text_delta", {"index": 0, "content": "Thirty "}),
        ]


class TestTheReasoningIsNeverSentUnlessItWasAgreedTo:
    async def test_a_page_that_shows_no_thinking_sends_no_thinking_frame(self) -> None:
        session = _session(_embed(show_thinking=False))

        await _stream(session, PartStartEvent(index=0, part=ThinkingPart(content="Deciding.")))

        assert "thinking_delta" not in _kinds(session)
        assert "Deciding." not in str(_sent(session)), "not hidden - not sent"

    async def test_a_page_that_shows_it_sends_it(self) -> None:
        session = _session(_embed(show_thinking=True))

        await _stream(session, PartStartEvent(index=0, part=ThinkingPart(content="Deciding.")))

        assert ("thinking_delta", {"index": 0, "content": "Deciding."}) in _sent(session)

    async def test_thinking_is_off_by_default(self) -> None:
        assert "thinking_delta" not in visible_frames(_embed())


class TestWhatTheAgentIsDoing:
    async def test_a_page_that_shows_steps_names_the_tool(self) -> None:
        """On by default: the alternative is a page that goes quiet for thirty
        seconds, which reads as broken."""
        session = _session(_embed())

        await _tools(session, _called())

        assert ("tool_call", {"tool_call_id": "c1", "tool_name": "search_kb"}) in _sent(session)

    async def test_a_page_that_shows_none_sends_no_step_frame(self) -> None:
        session = _session(_embed(show_tool_steps=False))

        await _tools(session, _called(), _returned())

        assert _kinds(session) == []

    async def test_a_step_carries_no_arguments_until_the_detail_is_shown(self) -> None:
        """The narration and the detail are different claims about what a stranger
        may read, and an argument list is where something internal turns up."""
        session = _session(_embed(show_tool_steps=True, show_tool_results=False))

        await _tools(session, _called(), _returned())

        assert _kinds(session) == ["tool_call"]
        assert "args" not in _sent(session)[0][1]
        assert "refunds" not in str(_sent(session))

    async def test_the_detail_arrives_when_it_is_shown(self) -> None:
        session = _session(_embed(show_tool_steps=True, show_tool_results=True))

        await _tools(session, _called(), _returned())

        step, result = _sent(session)
        assert step[0] == "tool_call"
        assert step[1]["args"] == {"q": "refunds"}
        assert result == ("tool_result", {"tool_call_id": "c1", "content": "30 days"})

    async def test_the_detail_cannot_be_shown_without_the_step_it_opens(self) -> None:
        """There is nothing for it to open, so `show_tool_results` alone is not a
        way to publish a tool's output with no context around it."""
        shown = visible_frames(_embed(show_tool_steps=False, show_tool_results=True))

        assert "tool_result" not in shown
        assert "tool_call" not in shown


class TestTheAssembledPromptIsNeverEchoed:
    async def test_the_frame_that_carries_it_is_refused_outright(self) -> None:
        """`user_prompt_processed` holds the prompt the *model* was given: the
        operator's placement note and the supplied block above the visitor's own
        words. The dashboard sends it to a member of the organization that wrote
        both; there is no setting that makes it right here.
        """
        for embed in (_embed(show_thinking=True, show_tool_results=True), _embed(kind="widget")):
            assert "user_prompt_processed" not in visible_frames(embed)

    async def test_even_a_page_that_shows_everything_refuses_it(self) -> None:
        session = _session(_embed(show_thinking=True, show_tool_steps=True, show_tool_results=True))

        await session._emit("user_prompt_processed", {"prompt": "[Context for this placement: …]"})

        assert _kinds(session) == []


class TestASurfaceWithNoSwitchesGetsTheSafeOnes:
    async def test_a_widget_and_a_socket_read_the_page_defaults(self) -> None:
        """Neither kind carries the three switches, and the defaults are read off
        `PageConfig` rather than repeated - a second copy of "off by default" is a
        copy that can disagree with the one somebody sees in the Builder."""
        for kind in ("widget", "socket"):
            shown = visible_frames(_embed(kind=kind))
            assert "thinking_delta" not in shown
            assert "tool_result" not in shown
            assert "tool_call" in shown
            assert "text_delta" in shown


class TestWhatATurnCostStaysWithTheOperator:
    async def test_the_terminal_frame_carries_no_usage(self) -> None:
        """The dashboard's `complete` reports the turn's tokens and cost. A visitor
        is not the one paying and is not shown the bill."""
        session = _session(_embed())

        await session._emit("complete", {})

        assert _sent(session) == [("complete", {})]


class TestATurnThatProducedNoWords:
    def test_a_parked_run_says_a_person_has_to_decide_and_offers_no_link(self) -> None:
        """A channel links to `/runs?run=…` because the reader is a member who can
        open it. Here they are a stranger holding a link, and a URL into somebody's
        console is not an answer to them."""
        message = _no_answer(MagicMock(status=RunStatus.AWAITING_APPROVAL.value))

        assert "approve" in message
        assert "http" not in message

    def test_a_run_stopped_by_its_budget_says_so(self) -> None:
        message = _no_answer(MagicMock(status=RunStatus.BUDGET_EXCEEDED.value))

        assert message == "This assistant has reached its usage limit."

    def test_anything_else_apologises_rather_than_naming_a_queue(self) -> None:
        """Sending somebody to a decision that was never raised is worse than
        saying nothing useful."""
        message = _no_answer(MagicMock(status=RunStatus.FAILED.value))

        assert "approve" not in message
