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

And the rule belongs to the *bot*, not to one way of reaching it: Mattermost's
outgoing webhook hands over a watched channel's posts the same way the socket
does, and answered all of them for as long as it said nothing about who they
named (#662).
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

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


class TestARefusalStaysOutOfARoomItWasNotAddressedIn:
    """The whitelist bot that talked over the channel (agenticos#634, the second
    time). A refusal - the whitelist not listing the speaker, a jwt bot they have
    not linked to - posted to a message that named a colleague, or named nobody,
    is the same interruption as answering one. So it is logged, not sent, unless
    the bot itself was named - the rule `_answer_mention` already applies to an
    unknown handle, now applied to the access and identity refusals too.
    """

    async def test_a_refusal_to_an_unaddressed_channel_message_is_not_posted(self):
        router = ChannelMessageRouter()
        router._send_reply = AsyncMock()

        await router._refuse_if_named(MagicMock(), _incoming(addressed=False), "denied")

        router._send_reply.assert_not_awaited()

    async def test_a_refusal_in_a_direct_message_is_posted(self):
        router = ChannelMessageRouter()
        router._send_reply = AsyncMock()

        await router._refuse_if_named(MagicMock(), _incoming(chat_type="private"), "denied")

        router._send_reply.assert_awaited_once()

    async def test_a_refusal_to_a_message_that_named_the_bot_is_posted(self):
        router = ChannelMessageRouter()
        router._send_reply = AsyncMock()

        await router._refuse_if_named(MagicMock(), _incoming(addressed=True), "denied")

        router._send_reply.assert_awaited_once()


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


class TestTheOutgoingWebhookTransportObeysTheSameRule:
    """The rule was the socket's alone, so the other half of the same adapter
    answered everything it was handed (#662). An outgoing-webhook body carries no
    mention list, so what stands in for one is `trigger_word`: the word an operator
    told *this integration* to fire on. Empty means the webhook fired on its
    channel filter, which delivers every post exactly as the socket does.
    """

    @staticmethod
    def _delivered(**payload: str) -> IncomingMessage:
        body = {
            "token": "t",
            "user_id": "u1",
            "user_name": "kacper",
            "channel_id": "c1",
            "channel_name": "town-square",
            "post_id": "p1",
            "text": "standup at 10 then",
            **payload,
        }
        incoming = MattermostAdapter().parse_incoming(body, "bot-1")
        assert incoming is not None
        return incoming

    def test_a_channel_post_that_fired_no_trigger_word_is_overheard(self) -> None:
        """The defect: Mattermost hands over every post in a watched channel and
        the bot answered each one, having said nothing about whether it was named."""
        delivered = self._delivered()

        assert delivered.addressed is False
        assert ChannelMessageRouter._is_overheard(delivered) is True

    def test_a_trigger_word_is_mattermosts_own_record_that_the_post_was_for_us(self) -> None:
        delivered = self._delivered(trigger_word="@ops", text="@ops standup at 10 then")

        assert delivered.addressed is True
        assert ChannelMessageRouter._is_overheard(delivered) is False

    def test_an_agent_handle_reaches_the_bot_without_one(self) -> None:
        """A slug is a name in this product, not a trigger word somebody had to
        configure, so it is read out of the text on either transport."""
        delivered = self._delivered(text="@sales what is the refund window")

        assert delivered.addressed is False
        assert ChannelMessageRouter._is_overheard(delivered) is False

    def test_a_direct_message_is_answered_without_one(self) -> None:
        """There is nobody else in the room, and no trigger word to type."""
        delivered = self._delivered(channel_name="u1__u2")

        assert ChannelMessageRouter._is_overheard(delivered) is False
