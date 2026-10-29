"""Group mentions are opt-in and never bypass the sender's normal access policy."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.channel_bot import AccessPolicy
from app.services.channels.base import IncomingMessage, broadcast_mentioned
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.mentions import parse_mention
from app.services.channels.router import ChannelMessageRouter
from app.services.channels.slack import SlackAdapter
from app.services.channels.teams import TeamsAdapter
from app.services.channels.teams_package import teams_manifest
from app.services.channels.telegram import TelegramAdapter

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "platform,text,expected",
    [
        ("mattermost", "@all hello", True),
        ("mattermost", "@here hello", True),
        ("mattermost", "`@all` example", False),
        ("mattermost", "```\n@all\n```", False),
        ("mattermost", "email@all.example", False),
        ("mattermost", "@all-other hello", False),
        ("slack", "<!here> hello", True),
        ("slack", "<!channel|channel> hello", True),
        ("slack", "@here plain text", False),
        ("slack", "`<!everyone>` example", False),
        ("telegram", "@all hello", True),
        ("telegram", "@everyone hello", True),
        ("teams", "@everyone plain text", False),
    ],
)
def test_only_platform_broadcast_syntax_outside_code_matches(platform, text, expected):
    assert broadcast_mentioned(platform, text) is expected


@pytest.mark.parametrize("enabled", [False, True, None, "false"])
@pytest.mark.parametrize("direct", [False, True, None])
def test_broadcast_policy_keeps_direct_mentions_and_is_off_by_default(enabled, direct):
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id="b",
        platform_user_id="u",
        platform_chat_id="C",
        chat_type="group",
        text="@all hello",
        broadcast_mention=True,
        addressed=direct,
    )
    bot = SimpleNamespace(access_policy={"respond_to_broadcasts": enabled})
    ChannelMessageRouter._apply_broadcast_policy(incoming, bot)
    assert incoming.addressed is (direct is True or enabled is True)
    assert ChannelMessageRouter._is_overheard(incoming) is not (direct is True or enabled is True)


def test_ordinary_group_chatter_is_not_promoted_and_dms_still_work():
    incoming = IncomingMessage(
        platform="slack",
        bot_id="b",
        platform_user_id="u",
        platform_chat_id="C",
        chat_type="group",
        text="hello",
        addressed=False,
    )
    ChannelMessageRouter._apply_broadcast_policy(
        incoming, SimpleNamespace(access_policy={"respond_to_broadcasts": True})
    )
    assert ChannelMessageRouter._is_overheard(incoming)
    incoming.chat_type = "private"
    assert not ChannelMessageRouter._is_overheard(incoming)
    assert AccessPolicy().respond_to_broadcasts is False
    assert parse_mention("@all @support help").slug == "support"


@pytest.mark.parametrize("direct", [False, True])
def test_mattermost_distinguishes_an_expanded_room_ping_from_a_direct_mention(direct):
    adapter = MattermostAdapter()
    adapter._own_ids["b"] = "own"
    adapter._own_names["b"] = "agenticos"
    text = "@all hello" + (" @agenticos" if direct else "")
    incoming = adapter.parse_incoming(
        {
            "event": "posted",
            "data": {
                "channel_type": "O",
                "mentions": '["own"]',
                "post": json.dumps({"id": "p", "user_id": "u", "channel_id": "C", "message": text}),
            },
        },
        "b",
    )
    assert incoming is not None and incoming.broadcast_mention
    assert incoming.addressed is direct
    webhook = adapter.parse_incoming(
        {
            "text": "@all hello",
            "trigger_word": "@all",
            "user_name": "alice",
            "user_id": "u",
            "channel_id": "C",
            "post_id": "p",
        },
        "b",
    )
    assert webhook is not None and webhook.broadcast_mention and webhook.addressed is False


def test_slack_keeps_native_room_and_bot_mentions_separate():
    adapter = SlackAdapter()
    for direct in (False, True):
        incoming = adapter.parse_incoming(
            {
                "event": {
                    "type": "message",
                    "channel": "C",
                    "user": "U",
                    "ts": "1.1",
                    "text": "<!here> hello" + (" <@BOT>" if direct else ""),
                },
                "authorizations": [{"user_id": "BOT", "is_bot": True}],
            },
            "b",
        )
        assert incoming is not None and incoming.broadcast_mention
        assert incoming.addressed is direct


@pytest.mark.parametrize("structured", [False, True])
def test_teams_uses_authoritative_room_ids_not_a_person_named_everyone(structured):
    adapter = TeamsAdapter()
    raw = {
        "type": "message",
        "id": "m",
        "serviceUrl": "https://smba.trafficmanager.net/emea/",
        "from": {"id": "u"},
        "recipient": {"id": "bot"},
        "conversation": {"id": "conversation", "conversationType": "channel"},
        "channelData": {"channel": {"id": "channel"}},
        "text": "<at>Everyone</at> hello",
        "entities": [
            {
                "type": "mention",
                "text": "<at>Everyone</at>",
                "mentioned": {
                    "conversation": {"id": "channel", "conversationIdentityType": "channel"}
                }
                if structured
                else {"id": "person", "name": "Everyone"},
            }
        ],
    }
    incoming = adapter.parse_incoming(raw, "b")
    assert incoming is not None
    assert incoming.broadcast_mention is structured
    assert incoming.addressed is False


@pytest.mark.parametrize("enabled", [False, True])
def test_teams_manifest_requests_room_message_access_only_when_opted_in(enabled):
    bot = MagicMock(
        name="Support",
        teams_app_id="11111111-1111-1111-1111-111111111111",
        access_policy={"respond_to_broadcasts": enabled},
    )
    bot.name = "Support"
    manifest = teams_manifest(bot)
    if enabled:
        assert manifest["webApplicationInfo"]["resource"] == f"api://{bot.teams_app_id}"
        grants = manifest["authorization"]["permissions"]["resourceSpecific"]
        assert {grant["name"] for grant in grants} == {
            "ChannelMessage.Read.Group",
            "ChatMessage.Read.Chat",
        }
        assert "owner consent" in manifest["description"]["full"]
    else:
        assert "authorization" not in manifest


def telegram_message(text="hello", **extra):
    return {
        "message": {
            "message_id": 1,
            "chat": {"id": -1, "type": "supergroup"},
            "from": {"id": 1},
            "text": text,
            **extra,
        }
    }


async def test_telegram_resolves_own_mentions_replies_and_commands_and_refreshes_rotated_tokens():
    adapter = TelegramAdapter()
    api = MagicMock()
    api.get_me = AsyncMock(return_value=SimpleNamespace(id=42, username="helper_bot"))

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield api

    cases = [
        (telegram_message(), False),
        (
            telegram_message(
                "🧠 @helper_bot hello", entities=[{"type": "mention", "offset": 3, "length": 11}]
            ),
            True,
        ),
        (
            telegram_message(
                "@other_bot hello", entities=[{"type": "mention", "offset": 0, "length": 10}]
            ),
            False,
        ),
        (telegram_message(reply_to_message={"from": {"id": 42}}), True),
        (telegram_message(reply_to_message={"from": {"id": 99}}), False),
        (
            telegram_message("/help", entities=[{"type": "bot_command", "offset": 0, "length": 5}]),
            True,
        ),
        (
            telegram_message(
                "/help@other", entities=[{"type": "bot_command", "offset": 0, "length": 11}]
            ),
            False,
        ),
        (
            telegram_message(
                "Helper",
                entities=[{"type": "text_mention", "offset": 0, "length": 6, "user": {"id": 42}}],
            ),
            True,
        ),
        (telegram_message("code", entities=[{"type": "code", "offset": 0, "length": 4}]), False),
    ]
    with patch.object(adapter, "_bot", client):
        for raw, expected in cases:
            incoming = adapter.parse_incoming(raw, "b")
            assert incoming is not None
            assert await adapter.resolve_addressing("token-one", incoming) is expected
        api.get_me.assert_awaited_once()
        incoming = adapter.parse_incoming(telegram_message("@all help"), "b")
        assert incoming is not None and incoming.broadcast_mention
        assert await adapter.resolve_addressing("token-two", incoming) is False
        assert api.get_me.await_count == 2
        incoming.chat_type = "private"
        assert await adapter.resolve_addressing("token-two", incoming) is True


async def test_telegram_identity_cache_expires_without_token_rotation():
    adapter = TelegramAdapter()
    api = SimpleNamespace(
        get_me=AsyncMock(
            side_effect=[
                SimpleNamespace(id=42, username="helper_bot"),
                SimpleNamespace(id=42, username="renamed_bot"),
            ]
        )
    )

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield api

    now = [0.0]
    with (
        patch.object(adapter, "_bot", client),
        patch("app.services.channels.telegram.time.monotonic", side_effect=lambda: now[0]),
    ):
        incoming = adapter.parse_incoming(
            telegram_message(
                "@helper_bot", entities=[{"type": "mention", "offset": 0, "length": 11}]
            ),
            "b",
        )
        assert await adapter.resolve_addressing("same-token", incoming)
        now[0] = 301
        incoming = adapter.parse_incoming(
            telegram_message(
                "@renamed_bot", entities=[{"type": "mention", "offset": 0, "length": 12}]
            ),
            "b",
        )
        assert await adapter.resolve_addressing("same-token", incoming)
    assert api.get_me.await_count == 2
