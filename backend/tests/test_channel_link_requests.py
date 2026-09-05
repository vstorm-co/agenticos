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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.schemas.channel_bot import LinkedPlace
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


def _db() -> MagicMock:
    """A session stand-in whose savepoint is a no-op async context manager."""
    db = MagicMock()
    savepoint = MagicMock()
    savepoint.__aenter__ = AsyncMock(return_value=savepoint)
    savepoint.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=savepoint)
    return db


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
            url = await ChannelLinkService(_db()).request(_incoming())

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
            await ChannelLinkService(_db()).request(_incoming())

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
            await ChannelLinkService(_db()).request(_incoming())

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
            await ChannelLinkService(_db()).request(_incoming())

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
            await ChannelLinkService(_db()).request(_incoming())

        expires_at = create.call_args.kwargs["expires_at"]
        assert timedelta(0) < expires_at - datetime.now(UTC) <= REQUEST_TTL
        assert timedelta(hours=1) >= REQUEST_TTL

    async def test_a_racing_first_message_answers_with_the_request_that_won(self):
        """Two first messages from one account both delete and both insert; the
        loser hits the unique constraint. It must re-read the survivor and
        answer with a URL, not bubble a 500 that leaves the bot silent."""
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_for_identity",
                new=AsyncMock(),
            ),
            patch(
                "app.services.channel_link.channel_link_request_repo.create",
                new=AsyncMock(side_effect=IntegrityError("insert", {}, Exception("conflict"))),
            ),
            patch(
                "app.services.channel_link.channel_link_request_repo.get_for_identity",
                new=AsyncMock(return_value=_request(token="winner")),
            ),
        ):
            url = await ChannelLinkService(_db()).request(_incoming())

        assert url.endswith("/link/winner")

    async def test_a_conflict_with_no_survivor_propagates(self):
        """If the constraint fired but nothing is there to re-read, the error is
        real and must not be swallowed into a bogus URL."""
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_for_identity",
                new=AsyncMock(),
            ),
            patch(
                "app.services.channel_link.channel_link_request_repo.create",
                new=AsyncMock(side_effect=IntegrityError("insert", {}, Exception("conflict"))),
            ),
            patch(
                "app.services.channel_link.channel_link_request_repo.get_for_identity",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(IntegrityError),
        ):
            await ChannelLinkService(_db()).request(_incoming())


class TestConfirming:
    async def _confirm(
        self, found: MagicMock | None, resolved: MagicMock | None, *, claimed: bool = True
    ) -> object:
        with (
            patch(
                "app.services.channel_link.channel_link_request_repo.get_valid",
                new=AsyncMock(return_value=found),
            ),
            patch(
                "app.services.channel_link.channel_identity_repo.get_or_create",
                new=AsyncMock(return_value=resolved),
            ) as resolved_call,
            patch(
                "app.services.channel_link.channel_identity_repo.update", new=AsyncMock()
            ) as updated,
            patch(
                "app.services.channel_link.channel_link_request_repo.delete_by_id",
                new=AsyncMock(return_value=claimed),
            ) as spent,
        ):
            result = await ChannelLinkService(MagicMock()).confirm("tok", self.user_id)
        self.resolved, self.updated, self.spent = resolved_call, updated, spent
        return result

    def setup_method(self) -> None:
        self.user_id = uuid.uuid4()

    async def test_confirm_resolves_through_the_upsert_not_get_then_create(self):
        """The whole of #1113: the identity is resolved with the same SELECT-first
        `get_or_create` the router uses, so a confirm racing an inbound message
        cannot collide on the identity's unique key and 500."""
        await self._confirm(_request(), MagicMock(user_id=None))
        self.resolved.assert_awaited_once()

    async def test_a_chat_account_linked_to_no_one_gains_its_person(self):
        """The row the upsert returns carries no user_id - a fresh insert the
        router won, or a never-linked one - so linking it is an explicit update."""
        assert await self._confirm(_request(), MagicMock(user_id=None)) is not None
        assert self.updated.call_args.kwargs["update_data"] == {"user_id": self.user_id}

    async def test_the_row_the_confirm_itself_inserted_is_not_rewritten(self):
        """On the miss, `get_or_create` inserts already carrying this user_id, so
        there is nothing left to update."""
        assert await self._confirm(_request(), MagicMock(user_id=self.user_id)) is not None
        assert self.resolved.call_args.kwargs["user_id"] == self.user_id
        assert self.updated.call_count == 0

    async def test_a_link_is_spent_once(self):
        await self._confirm(_request(), MagicMock(user_id=None))
        assert self.spent.call_count == 1

    async def test_a_token_that_does_not_resolve_links_nothing(self):
        """Unknown and expired answer the same way: the difference is not
        something the person clicking can act on differently."""
        assert await self._confirm(None, MagicMock()) is None
        assert self.resolved.call_count == 0
        assert self.updated.call_count == 0
        assert self.spent.call_count == 0

    async def test_a_second_confirm_of_the_same_token_links_nothing(self):
        """The token is single-use: a confirm whose claim of the request loses the
        race - its DELETE removes no row - must not go on to relink the identity
        and overwrite the winner's link (#1132)."""
        assert await self._confirm(_request(), MagicMock(user_id=None), claimed=False) is None
        assert self.resolved.call_count == 0
        assert self.updated.call_count == 0


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


class TestWhoIsAskedToLinkAtAll:
    """A room stopped asking (#639).

    The instruction above is what a channel used to get *instead of* an answer,
    for every sender who had never linked - which made a channel a dead end,
    since the refusal cannot carry the link and nothing in the channel could
    change that. It is now reached only by a bot whose policy asks for a link.
    """

    @staticmethod
    def _bot(**policy) -> MagicMock:
        return MagicMock(access_policy=policy or {})

    def test_a_direct_message_is_still_a_conversation_with_a_person(self):
        assert ChannelMessageRouter()._admits_unlinked(_incoming(), self._bot()) is False

    def test_a_channel_answers_somebody_who_never_linked(self):
        assert ChannelMessageRouter()._admits_unlinked(_incoming("group"), self._bot()) is True

    def test_a_supergroup_is_a_room_like_any_other(self):
        """Telegram's own name for a large group, and it arrives verbatim."""
        assert ChannelMessageRouter()._admits_unlinked(_incoming("supergroup"), self._bot()) is True

    def test_require_link_is_the_way_back_to_refusing(self):
        bot = self._bot(mode="open", require_link=True)

        assert ChannelMessageRouter()._admits_unlinked(_incoming("group"), bot) is False

    def test_require_link_is_read_from_a_policy_stored_as_a_string(self):
        """SQLite keeps `access_policy` as JSON text, so a setting that decides a
        refusal must not depend on which database answered."""
        bot = MagicMock(access_policy='{"mode":"open","require_link":true}')

        assert ChannelMessageRouter()._admits_unlinked(_incoming("group"), bot) is False

    def test_a_policy_that_says_nothing_admits_the_room(self):
        """The default is the answer here, and the default is `false`."""
        bot = self._bot(mode="open")

        assert ChannelMessageRouter()._admits_unlinked(_incoming("group"), bot) is True

    def test_jwt_linked_mode_requires_a_link_even_without_require_link(self):
        """A mode named for a linked account is a request for one. It used to
        decide nothing on its own - `mode="jwt_linked", require_link=False` admitted
        a room exactly as `open` did, a gate that read as applied and was inert."""
        bot = self._bot(mode="jwt_linked")

        assert ChannelMessageRouter()._admits_unlinked(_incoming("group"), bot) is False
        assert ChannelMessageRouter()._admits_unlinked(_incoming(), bot) is False

    def test_jwt_linked_is_read_from_a_policy_stored_as_a_string(self):
        bot = MagicMock(access_policy='{"mode":"jwt_linked","require_link":false}')

        assert ChannelMessageRouter()._admits_unlinked(_incoming("group"), bot) is False

    async def test_identity_resolution_no_longer_refuses_on_its_own(self):
        """The refusal belonged in one place. A second one here, reached only when
        both switches were set, answered a bare sentence where the invite path
        answers with the link in a direct message."""
        with patch(
            "app.services.channels.router.channel_identity_repo.get_or_create",
            new=AsyncMock(return_value=MagicMock(user_id=None)),
        ):
            identity = await ChannelMessageRouter()._resolve_identity(
                _incoming(), self._bot(mode="jwt_linked", require_link=True), MagicMock()
            )

        assert identity.user_id is None

    def test_jwt_linked_with_both_switches_is_refused_at_the_admission_gate(self):
        """The refusal `_resolve_identity` used to carry was reachable only with
        both switches set. Removing it must not have been the only barrier for
        that combination: the admission gate refuses it too, in a room and in a
        direct message, so the invite path is what answers and nothing runs."""
        bot = self._bot(mode="jwt_linked", require_link=True)

        assert ChannelMessageRouter()._admits_unlinked(_incoming("group"), bot) is False
        assert ChannelMessageRouter()._admits_unlinked(_incoming(), bot) is False


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


class TestWhereAConnectedAccountHasBeenUsed:
    """ "Mattermost" is the whole of what a chat account can say about itself.

    It is keyed on the platform and the account, never on a bot - so on a
    deployment with two Mattermost servers the row does not say which company's
    chat somebody just connected, and the agents it can reach are the reason
    they connected it at all. Both come from the sessions hanging off the
    identity, which are the only record of where the account has been used.
    """

    @staticmethod
    def _bot(*, organization_id=None, name="Acme Support", api_base_url=None) -> MagicMock:
        bot = MagicMock(
            id=uuid.uuid4(),
            organization_id=organization_id or uuid.uuid4(),
            api_base_url=api_base_url,
        )
        bot.name = name
        return bot

    @staticmethod
    def _agent(name: str = "Support", slug: str = "support") -> MagicMock:
        agent = MagicMock(id=uuid.uuid4(), slug=slug, has_avatar=False)
        agent.name = name
        return agent

    async def _places(
        self,
        *,
        bots: list,
        exposed: list | None = None,
        member: bool = True,
        may_see: bool = True,
    ) -> dict:
        identity = MagicMock(id=uuid.uuid4())
        with (
            patch(
                "app.services.channel_link.channel_session_repo.bots_by_identity",
                new=AsyncMock(return_value={identity.id: bots}),
            ),
            patch(
                "app.services.channel_link.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="owner") if member else None),
            ),
            patch(
                "app.services.channel_link.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=exposed or []),
            ),
            patch(
                "app.services.channel_link.resolve_access",
                new=AsyncMock(return_value=may_see),
            ),
        ):
            found = await ChannelLinkService(MagicMock()).places(uuid.uuid4(), [identity])
        return {"identity_id": identity.id, "places": found.get(identity.id, [])}

    async def test_a_self_hosted_bot_names_the_server_it_lives_on(self):
        answer = await self._places(bots=[self._bot(api_base_url="https://mattermost.acme.com/")])

        (place,) = answer["places"]
        assert (place.bot_name, place.host) == ("Acme Support", "mattermost.acme.com")

    async def test_only_the_hostname_reaches_the_page(self):
        """The configured URL is an operator's: it may carry a port, a path, or
        credentials behind a proxy, and none of that belongs under a name."""
        answer = await self._places(
            bots=[self._bot(api_base_url="https://bot:hunter2@mm.acme.com:8443/chat")]
        )

        assert answer["places"][0].host == "mm.acme.com"

    async def test_a_platform_with_no_server_of_its_own_says_nothing(self):
        """Every Slack bot is on the same SaaS; there the bot's name is the place."""
        answer = await self._places(bots=[self._bot(api_base_url=None)])

        assert answer["places"][0].host is None

    async def test_a_half_typed_address_is_not_rendered_as_one(self):
        answer = await self._places(bots=[self._bot(api_base_url="mattermost.acme.com")])

        assert answer["places"][0].host is None

    async def test_the_agents_that_answer_there_are_named(self):
        agent = self._agent()
        answer = await self._places(bots=[self._bot()], exposed=[(MagicMock(), agent)])

        (found,) = answer["places"][0].agents
        assert (found.id, found.name, found.slug) == (agent.id, "Support", "support")

    async def test_an_agent_the_reader_may_not_see_is_not_named(self):
        """Their own profile page must not be an enumeration endpoint for the
        agents somebody was deliberately not given."""
        answer = await self._places(
            bots=[self._bot()], exposed=[(MagicMock(), self._agent())], may_see=False
        )

        assert answer["places"][0].agents == []

    async def test_a_bot_in_an_organization_they_left_is_not_shown_at_all(self):
        """A chat account is not scoped to a tenant. One used at two companies
        must not tell either about the other."""
        answer = await self._places(bots=[self._bot()], member=False)

        assert answer["places"] == []

    async def test_an_account_used_nowhere_has_no_places(self):
        identity = MagicMock(id=uuid.uuid4())
        with patch(
            "app.services.channel_link.channel_session_repo.bots_by_identity",
            new=AsyncMock(return_value={}),
        ):
            found = await ChannelLinkService(MagicMock()).places(uuid.uuid4(), [identity])

        assert found == {}

    async def test_one_membership_lookup_per_organization_not_per_bot(self):
        """A person with six bots in one organization is one query, not six."""
        organization = uuid.uuid4()
        identity = MagicMock(id=uuid.uuid4())
        bots = [self._bot(organization_id=organization, name=f"Bot {n}") for n in range(3)]
        with (
            patch(
                "app.services.channel_link.channel_session_repo.bots_by_identity",
                new=AsyncMock(return_value={identity.id: bots}),
            ),
            patch(
                "app.services.channel_link.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="owner")),
            ) as membership,
            patch(
                "app.services.channel_link.agent_exposure_repo.list_active_for_bot",
                new=AsyncMock(return_value=[]),
            ),
        ):
            found = await ChannelLinkService(MagicMock()).places(uuid.uuid4(), [identity])

        assert len(found[identity.id]) == 3
        assert membership.await_count == 1


class TestTheListingRoute:
    """The two halves of a row arrive together or the page shows one of them."""

    async def test_each_row_carries_the_places_resolved_for_it(self):
        from app.api.routes.v1.me_channel_link import list_linked_accounts

        identity = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            platform="mattermost",
            platform_user_id="u-1",
            platform_username="kacper.wlodarczyk",
            platform_display_name="Kacper",
            is_active=True,
            created_at=datetime.now(UTC),
        )
        place = LinkedPlace(bot_id=uuid.uuid4(), bot_name="Acme Support", host="mm.acme.com")
        service = MagicMock()
        service.linked = AsyncMock(return_value=[identity])
        service.places = AsyncMock(return_value={identity.id: [place]})

        listed = await list_linked_accounts(service, MagicMock(id=uuid.uuid4()))

        assert listed.total == 1
        assert listed.items[0].places == [place]

    async def test_the_identities_are_read_once_and_handed_on(self):
        """Two queries for one answer is how a page comes to show a row the
        panel beside it does not have."""
        from app.api.routes.v1.me_channel_link import list_linked_accounts

        service = MagicMock()
        service.linked = AsyncMock(return_value=[])
        service.places = AsyncMock(return_value={})

        await list_linked_accounts(service, MagicMock(id=uuid.uuid4()))

        assert service.linked.await_count == 1
        assert service.places.await_args.args[1] == []
