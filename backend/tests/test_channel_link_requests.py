"""Connecting a chat account to the person behind it (#10).

Nothing in the repository ever wrote `channel_identities.link_code`, so `/link`
answered "invalid or expired" to every code that was never generated, every
identity kept `user_id = NULL`, and every channel refused every message with
"Link your account first". No channel answered anything - and it was silent,
because a command that always fails reads as a command somebody typed wrong.

What replaced it runs the other way round: the bot mints a request for the chat
account in front of it and answers with a URL, and whoever opens it confirms
while already signed in. A code typed from one screen into another was the first
attempt, and it died on contact with Mattermost, which parses a leading `/`
itself and never delivered the command carrying it.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channel_link import REQUEST_TTL, ChannelLinkService
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter, _as_command

pytestmark = pytest.mark.anyio


def _incoming(chat_type: str = "private") -> IncomingMessage:
    return IncomingMessage(
        platform="mattermost",
        bot_id=str(uuid.uuid4()),
        platform_user_id="u-1",
        platform_chat_id="c-1",
        chat_type=chat_type,
        text="hej",
        raw={},
        platform_username="kacper.wlodarczyk",
        platform_display_name="Kacper",
    )


def _request(**overrides) -> MagicMock:
    request = MagicMock()
    request.id = uuid.uuid4()
    request.token = "tok"
    request.platform = "mattermost"
    request.platform_user_id = "u-1"
    request.platform_username = "kacper.wlodarczyk"
    request.platform_display_name = "Kacper"
    for key, value in overrides.items():
        setattr(request, key, value)
    return request


class TestRequesting:
    async def test_the_url_carries_the_token_and_points_at_the_dashboard(self):
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_for_identity",
                new=AsyncMock(),
            ),
            patch(
                "app.services.channel_link.channel_link_request_repo.create",
                new=AsyncMock(return_value=_request(token="abc123")),
            ),
        ):
            url = await ChannelLinkService(MagicMock()).request(_incoming())

        assert url.endswith("/link/abc123")
        assert url.startswith("http")

    async def test_the_chat_account_is_recorded_so_the_page_can_name_it(self):
        """A page that says only "connect your account" asks somebody to trust a
        URL that arrived in a chat."""
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_for_identity",
                new=AsyncMock(),
            ),
            patch(
                "app.services.channel_link.channel_link_request_repo.create",
                new=AsyncMock(return_value=_request()),
            ) as create,
        ):
            await ChannelLinkService(MagicMock()).request(_incoming())

        assert create.call_args.kwargs["platform_user_id"] == "u-1"
        assert create.call_args.kwargs["platform_username"] == "kacper.wlodarczyk"

    async def test_asking_again_retires_the_url_that_scrolled_away(self):
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_for_identity",
                new=AsyncMock(),
            ) as clear,
            patch(
                "app.services.channel_link.channel_link_request_repo.create",
                new=AsyncMock(return_value=_request()),
            ),
        ):
            await ChannelLinkService(MagicMock()).request(_incoming())

        assert clear.call_args.kwargs["platform_user_id"] == "u-1"

    async def test_the_token_is_long_enough_not_to_be_guessed(self):
        """It is the whole of the authorisation: whoever opens the URL claims
        that chat account."""
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_for_identity",
                new=AsyncMock(),
            ),
            patch(
                "app.services.channel_link.channel_link_request_repo.create",
                new=AsyncMock(return_value=_request()),
            ) as create,
        ):
            await ChannelLinkService(MagicMock()).request(_incoming())

        assert len(create.call_args.kwargs["token"]) >= 32

    async def test_it_expires_in_minutes_rather_than_days(self):
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_for_identity",
                new=AsyncMock(),
            ),
            patch(
                "app.services.channel_link.channel_link_request_repo.create",
                new=AsyncMock(return_value=_request()),
            ) as create,
        ):
            await ChannelLinkService(MagicMock()).request(_incoming())

        expires_at = create.call_args.kwargs["expires_at"]
        assert timedelta(0) < expires_at - datetime.now(UTC) <= REQUEST_TTL
        assert timedelta(hours=1) >= REQUEST_TTL


class TestConfirming:
    async def _confirm(self, found: MagicMock | None, identity: MagicMock | None) -> object:
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.get_valid",
                new=AsyncMock(return_value=found),
            ),
            patch(
                "app.services.channel_link.channel_identity_repo.get_by_platform_user",
                new=AsyncMock(return_value=identity),
            ),
            patch(
                "app.services.channel_link.channel_identity_repo.create", new=AsyncMock()
            ) as created,
            patch(
                "app.services.channel_link.channel_identity_repo.update", new=AsyncMock()
            ) as updated,
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_by_id",
                new=AsyncMock(),
            ) as spent,
        ):
            result = await ChannelLinkService(MagicMock()).confirm("tok", self.user_id)
        self.created, self.updated, self.spent = created, updated, spent
        return result

    def setup_method(self) -> None:
        self.user_id = uuid.uuid4()

    async def test_the_chat_account_already_seen_gains_its_person(self):
        """The common path: they messaged the bot, were refused, and are now
        clicking the link that refusal carried - so the row is already there."""
        assert await self._confirm(_request(), MagicMock()) is not None
        assert self.updated.call_args.kwargs["update_data"] == {"user_id": self.user_id}

    async def test_an_unseen_chat_account_is_created_already_linked(self):
        assert await self._confirm(_request(), None) is not None
        assert self.created.call_args.kwargs["user_id"] == self.user_id

    async def test_a_link_is_spent_once(self):
        await self._confirm(_request(), MagicMock())
        assert self.spent.call_count == 1

    async def test_a_token_that_does_not_resolve_links_nothing(self):
        """Unknown and expired answer the same way: the difference is not
        something the person clicking can act on differently."""
        assert await self._confirm(None, MagicMock()) is None
        assert self.created.call_count == 0
        assert self.updated.call_count == 0
        assert self.spent.call_count == 0


class TestWhatTheBotSaysToAStranger:
    async def test_a_direct_message_gets_the_link(self):
        with patch.object(
            ChannelLinkService, "request", new=AsyncMock(return_value="https://app.test/link/abc")
        ):
            reply = await ChannelMessageRouter()._invite_to_link(_incoming(), MagicMock())

        assert "https://app.test/link/abc" in reply

    async def test_a_channel_gets_the_instruction_and_no_link(self):
        """The URL is a bearer credential and a channel is a room full of people.

        Sending it there would let anybody who reads the channel claim the
        sender's chat account.
        """
        with patch.object(
            ChannelLinkService, "request", new=AsyncMock(return_value="https://app.test/link/abc")
        ) as minted:
            reply = await ChannelMessageRouter()._invite_to_link(_incoming("group"), MagicMock())

        assert "https://app.test/link/abc" not in reply
        assert "direct message" in reply.lower()
        assert minted.call_count == 0, "nothing should be minted for a room it cannot be sent to"


class TestASlashAPlatformAte:
    """Mattermost parses a leading `/` itself.

    Typing `/link` there answers "command with a trigger of '/link' not found"
    and never delivers anything - and connecting an account is what somebody does
    before any channel will answer them. Found on a real server a minute after
    the integration first worked.
    """

    def test_the_bare_word_is_read_as_the_command(self):
        assert _as_command("link") == "/link"

    def test_case_and_spacing_do_not_matter(self):
        assert _as_command("  Link  ") == "/Link"

    def test_the_slash_form_still_works_where_the_platform_allows_it(self):
        assert _as_command("/link") == "/link"

    @pytest.mark.parametrize(
        "text",
        ["link do dokumentu?", "can you send me the link please", "linked", "link this"],
    )
    def test_an_ordinary_sentence_is_not_a_command(self, text: str):
        """ "link" is an ordinary word in English and in Polish, so only the whole
        message being that word counts."""
        assert _as_command(text) == text.strip()

    def test_nothing_else_gains_a_bare_form(self):
        """Only `link`. The others are reachable wherever a slash is delivered,
        and a bare `new` or `help` would swallow real messages."""
        assert _as_command("new") == "new"
        assert _as_command("help") == "help"


class TestWhatSomebodyHasConnected:
    """A link is granted in a chat and spent in a browser, so without a list the
    only record of what was connected is a message that has scrolled away."""

    async def _unlink(self, owned: list, identity_id: uuid.UUID) -> tuple[bool, object]:
        with (
            patch(
                "app.services.channel_link.channel_identity_repo.list_for_user",
                new=AsyncMock(return_value=owned),
            ),
            patch(
                "app.services.channel_link.channel_identity_repo.update", new=AsyncMock()
            ) as updated,
        ):
            done = await ChannelLinkService(MagicMock()).unlink(uuid.uuid4(), identity_id)
        return done, updated

    async def test_unlinking_clears_the_owner_rather_than_deleting_the_row(self):
        """The row carries the chat account's own id, and the sessions and
        conversations hang off it - the person keeps messaging the bot from the
        same account after they disconnect it."""
        identity = MagicMock()
        identity.id = uuid.uuid4()

        done, updated = await self._unlink([identity], identity.id)

        assert done is True
        assert updated.call_args.kwargs["update_data"] == {"user_id": None}

    async def test_an_identity_that_is_not_theirs_is_not_unlinked(self):
        """Scoped by owner rather than by id alone - an endpoint that unlinks by
        id is one that unlinks somebody else's."""
        identity = MagicMock()
        identity.id = uuid.uuid4()

        done, updated = await self._unlink([identity], uuid.uuid4())

        assert done is False
        assert updated.call_count == 0
