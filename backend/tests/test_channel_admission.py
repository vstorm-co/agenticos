"""Whether a chat definitely refuses somebody, as opposed to being unable to say (#2656)."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.core.exceptions import AuthorizationError
from app.services.channels import membership
from app.services.channels import router as module
from app.services.channels.base import ChannelDirectoryUnsupported, IncomingMessage
from app.services.channels.router import Admission, ChannelMessageRouter

pytestmark = pytest.mark.anyio


@pytest.fixture
def access(monkeypatch):
    org, conversation, user, identity_id, agent, bot_id = [uuid4() for _ in range(6)]
    run = SimpleNamespace(
        organization_id=org,
        conversation_id=conversation,
        user_id=user,
        channel_identity_id=identity_id,
        agent_id=agent,
        surface="slack",
        initiated_by_publisher_fallback=True,
    )
    bot = SimpleNamespace(
        id=bot_id,
        organization_id=org,
        platform="slack",
        is_active=True,
        access_policy={"mode": "open"},
    )
    session = SimpleNamespace(is_active=True, conversation_id=conversation, chat_type="group")
    identity = SimpleNamespace(platform="slack", platform_user_id="U1", user_id=user)
    exposure = SimpleNamespace(is_active=True)
    incoming = IncomingMessage(
        platform="slack",
        bot_id=str(bot_id),
        platform_chat_id="C1:1.0",
        platform_user_id="U1",
        chat_type="group",
        text="",
    )
    mocks = {}
    for repo, name, result in [
        (module.channel_bot_repo, "get_for_org", bot),
        (module.channel_session_repo, "get_by_bot_and_chat", session),
        (module.channel_identity_repo, "get_by_id", identity),
        (module.agent_exposure_repo, "get_for_bot", exposure),
        (module.member_repo, "get_active", SimpleNamespace(role="member")),
        (module.membership, "is_still_member", True),
        (module.membership, "platform_says_member", True),
        (module.membership, "platform_server", "111"),
    ]:
        mock = AsyncMock(return_value=result)
        monkeypatch.setattr(repo, name, mock)
        mocks[name] = mock
    return SimpleNamespace(
        run=run,
        bot=bot,
        session=session,
        identity=identity,
        exposure=exposure,
        incoming=incoming,
        mocks=mocks,
        db=AsyncMock(),
    )


def _break(s, refusal: str) -> None:
    match refusal:
        case "missing_bot":
            s.mocks["get_for_org"].return_value = None
        case "off":
            s.bot.is_active = False
        case "tenant":
            s.bot.organization_id = uuid4()
        case "platform":
            s.bot.platform = "teams"
        case "surface":
            s.run.surface = "web"
        case "missing_session":
            s.mocks["get_by_bot_and_chat"].return_value = None
        case "inactive_session":
            s.session.is_active = False
        case "chat_kind":
            s.session.chat_type = "private"
        case "conversation":
            s.session.conversation_id = uuid4()
        case "no_identity_id":
            s.run.channel_identity_id = None
        case "missing_identity":
            s.mocks["get_by_id"].return_value = None
        case "identity_platform":
            s.identity.platform = "teams"
        case "identity_sender":
            s.identity.platform_user_id = "someone_else"
        case "missing_exposure":
            s.mocks["get_for_bot"].return_value = None
        case "paused":
            s.exposure.is_active = False
        case "policy":
            s.bot.access_policy = {"mode": "whitelist", "whitelist": []}
        case "require_link":
            s.bot.access_policy = {"require_link": True}
        case "linked_other_user":
            s.run.initiated_by_publisher_fallback = False
            s.identity.user_id = uuid4()
        case "inactive_user":
            s.run.initiated_by_publisher_fallback = False
            s.mocks["get_active"].return_value = None


_REASONS = {
    "missing_bot": "bot",
    "off": "bot",
    "tenant": "bot",
    "platform": "bot",
    "surface": "bot",
    "missing_session": "session",
    "inactive_session": "session",
    "chat_kind": "session",
    "conversation": "session",
    "no_identity_id": "identity",
    "missing_identity": "identity",
    "identity_platform": "identity",
    "identity_sender": "identity",
    "missing_exposure": "binding",
    "paused": "binding",
    "policy": "access_policy",
    "require_link": "unlinked_not_admitted",
    "linked_other_user": "not_a_member",
    "inactive_user": "not_a_member",
}


@pytest.mark.parametrize(("refusal", "reason"), list(_REASONS.items()))
async def test_a_definite_policy_refusal_is_refused_and_names_its_reason(access, refusal, reason):
    _break(access, refusal)

    admission = await ChannelMessageRouter().admission(access.db, access.run, access.incoming)

    assert admission == Admission("refused", reason)
    access.mocks["platform_says_member"].assert_not_awaited()


async def test_a_private_chat_is_admitted_without_asking_the_platform(access):
    access.run.initiated_by_publisher_fallback = False
    access.session.chat_type = "private"
    incoming = replace(access.incoming, chat_type="private")

    admission = await ChannelMessageRouter().admission(access.db, access.run, incoming)

    assert admission.verdict == "admitted"
    access.mocks["platform_says_member"].assert_not_awaited()


async def test_a_room_member_the_platform_confirms_is_admitted(access):
    admission = await ChannelMessageRouter().admission(access.db, access.run, access.incoming)

    assert admission.verdict == "admitted"
    access.mocks["platform_says_member"].assert_awaited_once_with(access.bot, "C1", "U1")
    access.mocks["platform_server"].assert_not_awaited()


async def test_one_the_platform_says_has_left_is_refused(access):
    access.mocks["platform_says_member"].return_value = False

    admission = await ChannelMessageRouter().admission(access.db, access.run, access.incoming)

    assert admission == Admission("refused", "left_channel")


async def test_a_platform_that_answers_nothing_is_unconfirmed_not_refused(access):
    access.mocks["platform_says_member"].return_value = None

    admission = await ChannelMessageRouter().admission(access.db, access.run, access.incoming)

    assert admission == Admission("unconfirmed", "membership_unconfirmed")


async def test_may_continue_still_fails_closed_for_follow_ups(access):
    access.mocks["is_still_member"].return_value = False

    assert not await ChannelMessageRouter().may_continue(access.db, access.run, access.incoming)


def _discord(s, *, raw: dict[str, str]) -> IncomingMessage:
    """A Discord server channel, as `incoming_for_run` rebuilds it unless `raw` says more."""
    s.bot.platform = s.run.surface = s.identity.platform = "discord"
    s.bot.access_policy = {"mode": "open", "discord_guild_ids": ["111"]}
    return replace(s.incoming, platform="discord", raw=raw)


@pytest.mark.security
async def test_a_rebuilt_discord_sender_is_admitted_when_its_resolved_server_is_approved(access):
    incoming = _discord(access, raw={})

    admission = await ChannelMessageRouter().admission(access.db, access.run, incoming)

    assert admission == Admission("admitted", "member")
    access.mocks["platform_server"].assert_awaited_once_with(access.bot, "C1")


@pytest.mark.security
async def test_a_server_removed_from_the_allowlist_is_refused_even_though_the_run_was_parked(
    access,
):
    incoming = _discord(access, raw={})
    access.mocks["platform_server"].return_value = "222"

    admission = await ChannelMessageRouter().admission(access.db, access.run, incoming)

    assert admission == Admission("refused", "access_policy")
    access.mocks["platform_says_member"].assert_not_awaited()


@pytest.mark.security
async def test_a_server_that_cannot_be_looked_up_is_refused_not_trusted(access):
    incoming = _discord(access, raw={})
    access.mocks["platform_server"].return_value = None

    admission = await ChannelMessageRouter().admission(access.db, access.run, incoming)

    assert admission == Admission("refused", "server_unconfirmed")
    access.mocks["platform_says_member"].assert_not_awaited()


@pytest.mark.security
async def test_a_bot_that_approves_no_discord_server_refuses_a_server_channel_for_certain(access):
    incoming = _discord(access, raw={})
    access.bot.access_policy = {"mode": "open", "discord_guild_ids": []}

    admission = await ChannelMessageRouter().admission(access.db, access.run, incoming)

    assert admission == Admission("refused", "access_policy")


async def test_a_discord_server_channel_the_platform_says_was_left_is_still_refused(access):
    incoming = _discord(access, raw={})
    access.mocks["platform_says_member"].return_value = False

    admission = await ChannelMessageRouter().admission(access.db, access.run, incoming)

    assert admission == Admission("refused", "left_channel")


@pytest.mark.security
async def test_a_live_discord_message_from_an_unapproved_server_is_still_refused(access):
    incoming = _discord(access, raw={"guild_id": "222"})

    admission = await ChannelMessageRouter().admission(access.db, access.run, incoming)

    assert admission == Admission("refused", "access_policy")
    with pytest.raises(AuthorizationError):
        ChannelMessageRouter()._check_access(incoming, access.bot)


@pytest.mark.security
async def test_a_live_discord_message_from_an_approved_server_is_admitted(access):
    incoming = _discord(access, raw={"guild_id": "111"})

    admission = await ChannelMessageRouter().admission(access.db, access.run, incoming)

    assert admission == Admission("admitted", "member")
    access.mocks["platform_server"].assert_not_awaited()


@pytest.mark.security
async def test_may_continue_still_fails_closed_for_a_discord_server_it_cannot_name(access):
    incoming = _discord(access, raw={})

    assert not await ChannelMessageRouter().may_continue(access.db, access.run, incoming)


class _Redis:
    def __init__(self, cached: str | None = None) -> None:
        self.set = AsyncMock()
        self.get = AsyncMock(return_value=cached)


@pytest.fixture
def asked(monkeypatch):
    bot = SimpleNamespace(id=uuid4(), platform="slack", api_base_url=None)
    redis = _Redis()
    monkeypatch.setattr(membership, "_redis", redis)
    monkeypatch.setattr(membership, "unseal_bot_token", lambda _bot: "tok")
    return SimpleNamespace(bot=bot, redis=redis)


@pytest.mark.parametrize("answer", [True, False])
async def test_a_definite_platform_answer_is_returned_and_remembered(monkeypatch, asked, answer):
    adapter = SimpleNamespace(is_channel_member=AsyncMock(return_value=answer))
    monkeypatch.setattr(membership, "get_adapter", lambda _platform: adapter)

    assert await membership.platform_says_member(asked.bot, "C1", "U1") is answer

    adapter.is_channel_member.assert_awaited_once_with("tok", "C1", "U1", api_base_url=None)
    asked.redis.set.assert_awaited_once()


@pytest.mark.parametrize(
    "failure", [ChannelDirectoryUnsupported("no"), httpx.HTTPError("boom"), KeyError("slack")]
)
async def test_a_membership_check_the_platform_cannot_answer_is_unconfirmed(
    monkeypatch, asked, failure
):
    adapter = SimpleNamespace(is_channel_member=AsyncMock(side_effect=failure))
    monkeypatch.setattr(
        membership,
        "get_adapter",
        (lambda _platform: (_ for _ in ()).throw(failure))
        if isinstance(failure, KeyError)
        else (lambda _platform: adapter),
    )

    assert await membership.platform_says_member(asked.bot, "C1", "U1") is None

    asked.redis.set.assert_not_awaited()


async def test_a_cached_failed_check_does_not_turn_into_a_definite_answer(monkeypatch, asked):
    """`is_still_member` caches a failed check as "0" for a minute; this asks the platform."""
    asked.redis.get = AsyncMock(return_value="0")
    adapter = SimpleNamespace(is_channel_member=AsyncMock(return_value=True))
    monkeypatch.setattr(membership, "get_adapter", lambda _platform: adapter)

    assert await membership.platform_says_member(asked.bot, "C1", "U1") is True

    asked.redis.get.assert_not_awaited()
    adapter.is_channel_member.assert_awaited_once()


class _ServerAdapter:
    def __init__(self, result: str | BaseException | None) -> None:
        self.channel_server = AsyncMock(
            side_effect=result if isinstance(result, BaseException) else None,
            return_value=None if isinstance(result, BaseException) else result,
        )


async def test_the_platform_names_the_server_of_a_channel(monkeypatch, asked):
    adapter = _ServerAdapter("111")
    monkeypatch.setattr(membership, "get_adapter", lambda _platform: adapter)

    assert await membership.platform_server(asked.bot, "C1") == "111"

    adapter.channel_server.assert_awaited_once_with("tok", "C1")


@pytest.mark.parametrize("failure", [httpx.HTTPError("boom"), KeyError("discord")])
async def test_a_server_lookup_that_fails_names_nothing(monkeypatch, asked, failure):
    adapter = _ServerAdapter(failure)
    monkeypatch.setattr(
        membership,
        "get_adapter",
        (lambda _platform: (_ for _ in ()).throw(failure))
        if isinstance(failure, KeyError)
        else (lambda _platform: adapter),
    )

    assert await membership.platform_server(asked.bot, "C1") is None
