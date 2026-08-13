"""What a channel bot is reminded of, and from which end of the thread.

`_load_history` asked for a page from the wrong one: the repository orders
oldest-first, so `limit` with no offset is the *first* N turns. A support channel
passes N in days - `channel_sessions` keys the conversation to the chat, so the
thread never rolls over - and past it the model was told how the conversation
opened and nothing said since, including the question before the one it was
answering (#638, #636).

Nothing errored, which is the whole reason this is worth a test rather than a
fix: the bot answered plausibly, from a version of the conversation that had
stopped hundreds of turns ago.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channels.router import HISTORY_MESSAGES, ChannelMessageRouter

pytestmark = pytest.mark.anyio

MODULE = "app.services.channels.router"


def _message(index: int) -> MagicMock:
    return MagicMock(role="user", content=f"turn-{index}")


class TestTheWindowIsTheMostRecentTurns:
    async def test_a_long_thread_is_read_from_its_recent_end(self) -> None:
        total = HISTORY_MESSAGES * 3
        read = AsyncMock(return_value=[])

        with (
            patch(f"{MODULE}.conversation_repo.count_messages", new=AsyncMock(return_value=total)),
            patch(f"{MODULE}.conversation_repo.get_messages_by_conversation", new=read),
        ):
            await ChannelMessageRouter._load_history(MagicMock(), uuid.uuid4())

        asked = read.await_args.kwargs
        assert asked["skip"] == total - HISTORY_MESSAGES
        assert asked["limit"] == HISTORY_MESSAGES

    async def test_a_short_thread_starts_at_the_beginning(self) -> None:
        """`max(0, …)`, because a thread of three turns has no offset to take."""
        read = AsyncMock(return_value=[])

        with (
            patch(f"{MODULE}.conversation_repo.count_messages", new=AsyncMock(return_value=3)),
            patch(f"{MODULE}.conversation_repo.get_messages_by_conversation", new=read),
        ):
            await ChannelMessageRouter._load_history(MagicMock(), uuid.uuid4())

        assert read.await_args.kwargs["skip"] == 0

    async def test_the_turns_come_back_oldest_first(self) -> None:
        """The window is the recent end; the *order* inside it is unchanged. A model
        handed the last two hundred turns newest-first would read the conversation
        backwards, which is the failure this fix could easily have introduced."""
        read = AsyncMock(return_value=[_message(1), _message(2), _message(3)])

        with (
            patch(f"{MODULE}.conversation_repo.count_messages", new=AsyncMock(return_value=3)),
            patch(f"{MODULE}.conversation_repo.get_messages_by_conversation", new=read),
        ):
            history = await ChannelMessageRouter._load_history(MagicMock(), uuid.uuid4())

        assert [turn["content"] for turn in history] == ["turn-1", "turn-2", "turn-3"]

    async def test_the_channel_window_is_its_own_number(self) -> None:
        """Wider than the widget's 40, and for a different reason: a widget is a
        public URL with somebody else's budget behind it, and a channel is a room
        the operator's own colleagues work in."""
        from app.services.embed_session import HISTORY_MESSAGES as WIDGET

        assert HISTORY_MESSAGES > WIDGET
