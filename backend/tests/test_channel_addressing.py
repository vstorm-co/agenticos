"""When a channel bot speaks, and when it stays out of the way.

A bot in a Mattermost channel is one member of many, and its socket delivers
*every* post in every channel it belongs to. The default agent answered all of
them, so adding the bot to a team channel meant it replied to colleagues talking
to each other (agenticos#634). A direct message is the opposite case and always
was: there is nobody else in the room, so requiring a mention would be asking
somebody to address the only participant.

Three things have to hold together, and the middle one is what makes the rule
usable rather than merely quiet:

*A direct message is always answered.* No mention, no handle, nothing.

*An `@agent-slug` addresses the bot even though the platform has never heard of
it.* A slug is a name in this product; it is not an account, so it never appears
in a mention list. A gate that trusted only that list would have silently broken
every `@sales what is the refund window` in a channel - the loudest possible
regression, and the quietest to ship.

*Silence where the platform did not say.* Slack and Telegram deliver on their own
subscription rules, so reading "no mention data" as "ignore" would take a working
bot on either of them off the air.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.services.channels.base import IncomingMessage
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.router import ChannelMessageRouter

pytestmark = pytest.mark.anyio


def _incoming(
    *, chat_type: str = "group", text: str = "hej", addressed: bool | None = None
) -> IncomingMessage:
    return IncomingMessage(
        platform="mattermost",
        bot_id=str(uuid.uuid4()),
        platform_user_id="u-1",
        platform_chat_id="c-1",
        chat_type=chat_type,
        text=text,
        raw={},
        addressed=addressed,
    )


class TestWhetherAMessageWasMeantForTheBot:
    def test_a_direct_message_always_is(self) -> None:
        """There is nobody else in the room to address."""
        assert ChannelMessageRouter._is_overheard(_incoming(chat_type="private")) is False
        assert (
            ChannelMessageRouter._is_overheard(_incoming(chat_type="private", addressed=False))
            is False
        )

    def test_a_channel_message_naming_nobody_is_overheard(self) -> None:
        """The defect: two colleagues talking, and a bot answering both of them."""
        assert ChannelMessageRouter._is_overheard(_incoming(addressed=False)) is True

    def test_a_channel_message_that_named_the_bot_is_not(self) -> None:
        assert ChannelMessageRouter._is_overheard(_incoming(addressed=True)) is False

    def test_an_agent_handle_addresses_the_bot_the_platform_has_never_heard_of(self) -> None:
        """A slug is a name in this product rather than an account on Mattermost, so
        it is never in a mention list - and a gate that only read that list would
        have taken every `@slug` in a channel off the air."""
        addressed_by_handle = _incoming(text="@sales what is the refund window", addressed=False)

        assert ChannelMessageRouter._is_overheard(addressed_by_handle) is False

    def test_a_platform_that_says_nothing_is_answered_as_before(self) -> None:
        """Slack and Telegram deliver on their own subscription rules. Reading
        silence as "ignore" would make a working bot on either go quiet."""
        assert ChannelMessageRouter._is_overheard(_incoming(addressed=None)) is False

    def test_the_bot_is_named_by_a_direct_message_and_by_a_mention(self) -> None:
        """What decides whether an unknown handle is answered out loud: `@ada` in a
        channel is somebody's colleague, and a bot that says "@ada is not available
        on this bot" every time is the interruption the gate exists to stop."""
        assert ChannelMessageRouter._names_the_bot(_incoming(chat_type="private")) is True
        assert ChannelMessageRouter._names_the_bot(_incoming(addressed=True)) is True
        assert ChannelMessageRouter._names_the_bot(_incoming(addressed=None)) is True
        assert ChannelMessageRouter._names_the_bot(_incoming(addressed=False)) is False


class TestReadingMattermostsOwnMentionList:
    def _adapter(self, own: str | None) -> MattermostAdapter:
        adapter = MattermostAdapter()
        if own is not None:
            adapter._own_ids["bot-1"] = own
        return adapter

    def test_the_bots_own_id_in_the_list_is_a_mention_of_it(self) -> None:
        adapter = self._adapter("bot-user")

        assert adapter._addressed({"mentions": json.dumps(["bot-user"])}, "bot-1") is True

    def test_somebody_elses_id_is_not(self) -> None:
        """Read from the list rather than from the text: matching `@bot` against the
        message would make a bot called `bot` answer the word "robot"."""
        adapter = self._adapter("bot-user")

        assert adapter._addressed({"mentions": json.dumps(["ada"])}, "bot-1") is False

    def test_no_mentions_at_all_is_not(self) -> None:
        """The event carries the list whenever there is one, so its absence means
        nobody was mentioned - which is the ordinary channel chatter this drops."""
        adapter = self._adapter("bot-user")

        assert adapter._addressed({}, "bot-1") is False

    def test_an_unresolved_own_id_says_nothing_rather_than_no(self) -> None:
        """`None`, not `False`. Answering too much is the worse failure of the two
        where nobody chose it: a server that would not say who we are must not take
        the bot off the air."""
        adapter = self._adapter(None)

        assert adapter._addressed({"mentions": json.dumps(["ada"])}, "bot-1") is None

    def test_a_mention_list_that_is_not_a_list_is_read_as_no_mention(self) -> None:
        adapter = self._adapter("bot-user")

        assert adapter._addressed({"mentions": "not json"}, "bot-1") is False
        assert adapter._addressed({"mentions": json.dumps({"id": "bot-user"})}, "bot-1") is False
