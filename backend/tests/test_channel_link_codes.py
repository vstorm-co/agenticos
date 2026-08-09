"""Connecting a chat account to the person behind it (#10).

Nothing in the repository ever wrote `channel_identities.link_code`, so `/link`
answered "invalid or expired" to every code that was never generated, every
identity kept `user_id = NULL`, and `ChannelAgentRouter` refused every message on
every channel with "Link your account first". No channel answered anything - and
the whole of it was silent, because a command that always fails looks like a
command somebody typed wrong.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channel_link import CODE_TTL, ChannelLinkService, new_code
from app.services.channels.router import _as_command

pytestmark = pytest.mark.anyio


def _code_row(user_id: uuid.UUID | None = None) -> MagicMock:
    row = MagicMock()
    row.user_id = user_id or uuid.uuid4()
    return row


class TestMinting:
    async def test_a_code_is_minted_for_the_user_who_asked(self):
        user_id = uuid.uuid4()
        with (
            patch(
                "app.services.channel_link.channel_link_code_repo.delete_for_user",
                new=AsyncMock(),
            ),
            patch(
                "app.services.channel_link.channel_link_code_repo.create",
                new=AsyncMock(return_value=_code_row(user_id)),
            ) as create,
        ):
            await ChannelLinkService(MagicMock()).mint(user_id)

        assert create.call_args.kwargs["user_id"] == user_id
        assert create.call_args.kwargs["code"]

    async def test_asking_again_invalidates_the_code_that_scrolled_away(self):
        """One at a time: a person who asks twice must not leave a live bearer
        credential behind them."""
        user_id = uuid.uuid4()
        with (
            patch(
                "app.services.channel_link.channel_link_code_repo.delete_for_user",
                new=AsyncMock(),
            ) as clear,
            patch(
                "app.services.channel_link.channel_link_code_repo.create",
                new=AsyncMock(return_value=_code_row(user_id)),
            ),
        ):
            await ChannelLinkService(MagicMock()).mint(user_id)

        assert clear.call_args.kwargs["user_id"] == user_id

    async def test_a_code_expires_in_minutes_rather_than_days(self):
        """Whoever types it becomes the account, as far as every channel is
        concerned - so a code left in a chat log must stop being a way in."""
        user_id = uuid.uuid4()
        with (
            patch(
                "app.services.channel_link.channel_link_code_repo.delete_for_user",
                new=AsyncMock(),
            ),
            patch(
                "app.services.channel_link.channel_link_code_repo.create",
                new=AsyncMock(return_value=_code_row(user_id)),
            ) as create,
        ):
            await ChannelLinkService(MagicMock()).mint(user_id)

        expires_at = create.call_args.kwargs["expires_at"]
        assert timedelta(0) < expires_at - datetime.now(UTC) <= CODE_TTL
        assert timedelta(hours=1) >= CODE_TTL

    def test_the_alphabet_has_no_character_anybody_has_to_disambiguate(self):
        """It is read off one screen and typed into another, sometimes from a
        phone. `0`/`O` and `1`/`l` are a support conversation."""
        assert not set("01OIl") & set("".join(new_code() for _ in range(200)))


class TestRedeeming:
    async def _redeem(self, found: MagicMock | None, identity: MagicMock | None) -> bool:
        with (
            patch(
                "app.services.channel_link.channel_link_code_repo.get_valid",
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
                "app.services.channel_link.channel_link_code_repo.delete_for_user",
                new=AsyncMock(),
            ) as cleared,
        ):
            spent = await ChannelLinkService(MagicMock()).redeem(
                "ABCD2345", platform="mattermost", platform_user_id="u-1"
            )
        self.created, self.updated, self.cleared = created, updated, cleared
        return spent

    async def test_an_identity_that_already_exists_gains_its_user(self):
        """The common path: somebody messaged the bot, was refused, and is now
        typing the code from that same chat - so the row is already there."""
        found = _code_row()
        identity = MagicMock()
        assert await self._redeem(found, identity) is True
        assert self.updated.call_args.kwargs["update_data"] == {"user_id": found.user_id}

    async def test_an_unseen_chat_account_is_created_already_linked(self):
        found = _code_row()
        assert await self._redeem(found, None) is True
        assert self.created.call_args.kwargs["user_id"] == found.user_id

    async def test_a_code_is_spent_once(self):
        found = _code_row()
        await self._redeem(found, MagicMock())
        assert self.cleared.call_args.kwargs["user_id"] == found.user_id

    async def test_a_code_that_does_not_resolve_links_nothing(self):
        """Wrong and expired answer the same way: the difference is not
        something the person typing can act on differently."""
        assert await self._redeem(None, MagicMock()) is False
        assert self.created.call_count == 0
        assert self.updated.call_count == 0
        assert self.cleared.call_count == 0

    async def test_the_code_is_read_the_way_a_person_types_it(self):
        """Lower case and stray spaces are how it arrives from a phone."""
        with (
            patch(
                "app.services.channel_link.channel_link_code_repo.get_valid",
                new=AsyncMock(return_value=None),
            ) as lookup,
            patch(
                "app.services.channel_link.channel_identity_repo.get_by_platform_user",
                new=AsyncMock(return_value=None),
            ),
        ):
            await ChannelLinkService(MagicMock()).redeem(
                "  abcd2345 ", platform="telegram", platform_user_id="u-1"
            )

        assert lookup.call_args.kwargs["code"] == "ABCD2345"


class TestASlashAPlatformAte:
    """Mattermost parses a leading `/` itself.

    Typing `/link ABCD2345` there answers "command with a trigger of '/link' not
    found" and never delivers anything - and `/link` is the one command somebody
    has to run before any channel will answer them at all. Found on a real server
    within a minute of the integration working.
    """

    def test_the_bare_form_is_read_as_the_command(self):
        assert _as_command("link ABCD2345") == "/link ABCD2345"

    def test_case_and_spacing_do_not_matter(self):
        assert _as_command("  Link abcd2345  ") == "/Link abcd2345"

    def test_the_slash_form_still_works_where_the_platform_allows_it(self):
        assert _as_command("/link ABCD2345") == "/link ABCD2345"

    @pytest.mark.parametrize(
        "text",
        [
            "link do dokumentu?",
            "link",
            "can you send me the link ABCD2345 please",
            "linked ABCD2345",
        ],
    )
    def test_an_ordinary_sentence_is_not_a_command(self, text: str):
        """ "link" is an ordinary word in English and in Polish. Only the whole
        message being the word plus something code-shaped counts."""
        assert _as_command(text) == text.strip()

    def test_nothing_else_gains_a_bare_form(self):
        """Only `link`. The others are reachable on every platform that delivers
        a slash, and a bare `new` or `help` would swallow real messages."""
        assert _as_command("new") == "new"
        assert _as_command("help me ABCD2345") == "help me ABCD2345"
