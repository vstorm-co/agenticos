"""What a visitor's frame is allowed to ask of a public socket.

`test_embed_frames.py` covers what comes *out* of a turn. This covers what goes
*in*: the frames `handle` refuses before a run is ever started, and the two
endings that produce no words. Both halves matter more here than on the
dashboard, because the caller is a stranger on somebody else's page — every
refusal below is a request that reached the server and cost nothing.

The turn itself is stubbed throughout. What is being asserted is the guard, not
the run behind it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.db.models.agent_run import RunStatus
from app.services.embed_session import MAX_MESSAGE_CHARS, EmbedSession

pytestmark = pytest.mark.anyio

MODULE = "app.services.embed_session"


def _embed(**overrides: Any) -> MagicMock:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "owner_user_id": uuid.uuid4(),
        "name": "Support",
        "kind": "page",
        "config": {"kind": "page"},
        "rate_limit_per_minute": 10,
    }
    return MagicMock(**{**fields, **overrides})


def _session(embed: MagicMock | None = None, *, visitor: str | None = None) -> EmbedSession:
    @asynccontextmanager
    async def sessions() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    return EmbedSession(
        sessions=sessions,
        embed=embed if embed is not None else _embed(),
        visitor=visitor,
        websocket=websocket,
    )


def _sent(session: EmbedSession) -> list[tuple[str, dict[str, Any]]]:
    return [
        (call.args[0]["type"], call.args[0]["data"])
        for call in session.websocket.send_json.await_args_list
    ]


def _errors(session: EmbedSession) -> list[str]:
    return [data["message"] for kind, data in _sent(session) if kind == "error"]


class TestWhatIsRefusedBeforeATurnStarts:
    """Every one of these is a request from a stranger. None reaches a model."""

    async def test_a_frame_that_is_not_a_message_is_ignored(self):
        """A client may send a kind this server predates - somebody's browser is
        older than this deployment - and closing the socket on it would take the
        conversation with it."""
        session = _session()

        with patch.object(EmbedSession, "_turn_frames", AsyncMock()) as turn:
            await session.handle({"type": "ping"})

        turn.assert_not_awaited()
        assert _sent(session) == []

    async def test_a_message_with_neither_text_nor_a_file_starts_nothing(self):
        session = _session()

        with patch.object(EmbedSession, "_turn_frames", AsyncMock()) as turn:
            await session.handle({"type": "message", "text": "   "})

        turn.assert_not_awaited()
        assert _sent(session) == []

    async def test_a_message_past_the_character_cap_is_refused_not_truncated(self):
        """Truncating would send the model half a question and answer it
        confidently, which is worse than saying no."""
        session = _session()

        with patch.object(EmbedSession, "_turn_frames", AsyncMock()) as turn:
            await session.handle({"type": "message", "text": "x" * (MAX_MESSAGE_CHARS + 1)})

        turn.assert_not_awaited()
        assert _errors(session) == ["That message is too long. Try a shorter one."]

    async def test_a_visitor_past_the_rate_limit_is_refused(self):
        """The cap is the operator's, per visitor, and it is the only thing
        standing between a public URL and their monthly bill."""
        session = _session()

        with (
            patch(f"{MODULE}._allowed", return_value=False),
            patch.object(EmbedSession, "_turn_frames", AsyncMock()) as turn,
        ):
            await session.handle({"type": "message", "text": "hello"})

        turn.assert_not_awaited()
        assert _errors(session) == ["You are sending messages too quickly."]


class TestHowATurnEnds:
    async def test_a_turn_that_answered_says_only_that_it_is_complete(self):
        session = _session()

        with patch.object(EmbedSession, "_turn_frames", AsyncMock(return_value=None)):
            await session.handle({"type": "message", "text": "hello"})

        assert _errors(session) == []
        assert ("complete", {}) in _sent(session)

    async def test_a_turn_with_no_words_says_why_and_still_completes(self):
        """A client stops drawing the turn on `complete`, so a refusal that
        omitted it would leave the caret pulsing under the notice."""
        session = _session()

        with patch.object(EmbedSession, "_turn_frames", AsyncMock(return_value="No answer.")):
            await session.handle({"type": "message", "text": "hello"})

        assert _errors(session) == ["No answer."]
        assert _sent(session)[-1] == ("complete", {})

    async def test_a_refused_run_tells_the_visitor_nothing_about_the_server(self):
        """The exception is this deployment's business: an `AppException` here
        names an agent, a model profile or an organization, and the caller is a
        stranger on somebody else's page."""
        session = _session()

        with patch.object(
            EmbedSession, "_answer", AsyncMock(side_effect=BadRequestError(message="no profile"))
        ):
            unanswered = await session._turn_frames("hello", ())

        assert unanswered == "This assistant is unavailable."

    async def test_a_run_that_produced_no_text_is_named_by_why(self):
        """`_no_answer` holds the one copy of those sentences - a budget stop is
        not raised out of `_answer`, it is a status on the row."""
        session = _session()
        run = MagicMock(status=RunStatus.BUDGET_EXCEEDED, awaiting_approval_run_id=None)

        with patch.object(EmbedSession, "_answer", AsyncMock(return_value=("", run))):
            unanswered = await session._turn_frames("hello", ())

        assert unanswered is not None


class TestTheRestOfTheSession:
    async def test_fail_reaches_the_visitor_as_an_error_frame(self):
        session = _session()

        await session.fail("This assistant is unavailable.")

        assert _errors(session) == ["This assistant is unavailable."]

    async def test_closing_releases_nothing_because_it_owns_nothing(self):
        """The session holds no task and no client - the factory hands one out per
        turn - so this is a seam for the route rather than a teardown."""
        session = _session()

        released = await session.close()

        assert released is None
        session.websocket.send_json.assert_not_awaited()

    async def test_a_thread_with_no_conversation_yet_has_no_history(self):
        session = _session()
        session.conversation_id = None

        history = await session._history(MagicMock())

        assert history == []


class TestTheThreadAVisitorComesBackTo:
    async def test_a_continuity_key_with_no_row_behind_it_still_gets_a_thread(self):
        """The row is written at `greet`, so its absence means a key nobody here
        issued - a stale one, or one somebody typed. The turn is answered anyway
        and simply does not come back to the same thread: refusing a stranger
        their answer over a cookie is the worse trade.
        """
        session = _session()
        session.visitor_key = "vk-from-nowhere"
        session.conversation_id = None
        conversation = MagicMock(id=uuid.uuid4())

        runner = MagicMock()
        runner.return_value.execute = AsyncMock(return_value=("hello", MagicMock()))

        with (
            patch.object(EmbedSession, "_context", AsyncMock(return_value=MagicMock())),
            patch.object(EmbedSession, "_history", AsyncMock(return_value=[])),
            patch.object(EmbedSession, "_files", AsyncMock(return_value=[])),
            patch(f"{MODULE}.AgentRunnerService", runner),
            patch(
                f"{MODULE}.conversation_repo.create_conversation",
                AsyncMock(return_value=conversation),
            ),
            patch(f"{MODULE}.embed_visitor_repo.get", AsyncMock(return_value=None)),
            patch(f"{MODULE}.embed_visitor_repo.link_conversation", AsyncMock()) as link,
        ):
            await session._turn(MagicMock(), "hello")

        assert session.conversation_id == conversation.id
        link.assert_not_awaited()


class TestWhichFilesAVisitorMayAttach:
    """A file is usable when it belongs to the embed's owner and is not already on
    a message. Anything else is somebody else's row, or one already spent."""

    async def test_files_that_are_all_usable_are_passed_through_silently(self):
        session = _session()
        rows = [
            MagicMock(user_id=session.embed.owner_user_id, message_id=None),
            MagicMock(user_id=session.embed.owner_user_id, message_id=None),
        ]
        attached = [uuid.uuid4(), uuid.uuid4()]

        with patch(f"{MODULE}.chat_file_repo.get_many", AsyncMock(return_value=rows)):
            usable = await session._files(MagicMock(), attached)

        assert usable == rows

    async def test_an_id_that_resolves_to_nothing_usable_is_dropped_not_refused(self):
        """Refusing somebody their answer over a stale id in a composer is the
        worse trade, so the turn goes ahead without it."""
        session = _session()
        mine = MagicMock(user_id=session.embed.owner_user_id, message_id=None)
        spent = MagicMock(user_id=session.embed.owner_user_id, message_id=uuid.uuid4())

        with patch(f"{MODULE}.chat_file_repo.get_many", AsyncMock(return_value=[mine, spent])):
            usable = await session._files(MagicMock(), [uuid.uuid4(), uuid.uuid4()])

        assert usable == [mine]

    async def test_a_turn_carrying_no_ids_asks_the_repository_nothing(self):
        session = _session()

        with patch(f"{MODULE}.chat_file_repo.get_many", AsyncMock()) as get_many:
            usable = await session._files(MagicMock(), ())

        assert usable == []
        get_many.assert_not_awaited()
