"""What a surface reminds a model of, and from which end of the thread.

The window was asked for from the wrong one: the repository orders oldest-first,
so `limit` with no offset is the *first* N turns. A support channel passes N in
days - `channel_sessions` keys the conversation to the chat, so the thread never
rolls over - and past it the model was told how the conversation opened and
nothing said since, including the question before the one it was answering
(#638, #636). The widget had the same hole from the other direction (#39).

Nothing errored, which is the whole reason this is worth a test rather than a
fix: the bot answered plausibly, from a version of the conversation that had
stopped hundreds of turns ago.

The offset now lives in `conversation_repo.get_recent_messages`, so that is what
these are written against - three surfaces reading the window three times is how
it came to be wrong twice.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories import conversation as conversation_repo
from app.services.channels.router import HISTORY_MESSAGES

pytestmark = pytest.mark.anyio

MODULE = "app.repositories.conversation"


def _message(index: int) -> MagicMock:
    return MagicMock(role="user", content=f"turn-{index}")


class TestTheWindowIsTheMostRecentTurns:
    async def test_a_long_thread_is_read_from_its_recent_end(self) -> None:
        total = HISTORY_MESSAGES * 3
        read = AsyncMock(return_value=[])

        with (
            patch(f"{MODULE}.count_messages", new=AsyncMock(return_value=total)),
            patch(f"{MODULE}.get_messages_by_conversation", new=read),
        ):
            await conversation_repo.get_recent_messages(
                MagicMock(), uuid.uuid4(), limit=HISTORY_MESSAGES
            )

        asked = read.await_args.kwargs
        assert asked["skip"] == total - HISTORY_MESSAGES
        assert asked["limit"] == HISTORY_MESSAGES

    async def test_a_short_thread_starts_at_the_beginning(self) -> None:
        """`max(0, …)`, because a thread of three turns has no offset to take."""
        read = AsyncMock(return_value=[])

        with (
            patch(f"{MODULE}.count_messages", new=AsyncMock(return_value=3)),
            patch(f"{MODULE}.get_messages_by_conversation", new=read),
        ):
            await conversation_repo.get_recent_messages(
                MagicMock(), uuid.uuid4(), limit=HISTORY_MESSAGES
            )

        assert read.await_args.kwargs["skip"] == 0

    async def test_the_turns_come_back_oldest_first(self) -> None:
        """The window is the recent end; the *order* inside it is unchanged. A model
        handed the last two hundred turns newest-first would read the conversation
        backwards, which is the failure this fix could easily have introduced."""
        read = AsyncMock(return_value=[_message(1), _message(2), _message(3)])

        with (
            patch(f"{MODULE}.count_messages", new=AsyncMock(return_value=3)),
            patch(f"{MODULE}.get_messages_by_conversation", new=read),
        ):
            window = await conversation_repo.get_recent_messages(
                MagicMock(), uuid.uuid4(), limit=HISTORY_MESSAGES
            )

        assert [turn.content for turn in window] == ["turn-1", "turn-2", "turn-3"]


class TestEachSurfaceChoosesItsOwnWidth:
    def test_the_channel_window_is_wider_than_the_widgets(self) -> None:
        """A widget is a public URL with somebody else's budget behind it, and a
        channel is a room the operator's own colleagues work in."""
        from app.services.embed_session import HISTORY_MESSAGES as WIDGET

        assert HISTORY_MESSAGES > WIDGET

    def test_web_chat_reads_the_same_width_as_a_channel(self) -> None:
        """Both are signed-in members working in a thread that never rolls over."""
        from app.services.agent_session import HISTORY_MESSAGES as WEB_CHAT

        assert WEB_CHAT == HISTORY_MESSAGES
