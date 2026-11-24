"""Where a chat's first message lands (#2575): the person's own conversation, or a fresh one."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.channels.router import ChannelMessageRouter

pytestmark = pytest.mark.anyio

ROUTER = "app.services.channels.router"
ORG, USER, AGENT, PRIMARY, FRESH = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()


def _incoming(chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(platform="sms", chat_type=chat_type)


def _bot() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), organization_id=ORG)


async def _first(incoming, identity, *, binding):
    create = AsyncMock(return_value=SimpleNamespace(id=FRESH))
    with (
        patch(f"{ROUTER}.agent_exposure_repo.bound_to_bot", new=AsyncMock(return_value=binding)),
        patch(f"{ROUTER}.conversation_repo.create_conversation", new=create),
    ):
        result = await ChannelMessageRouter._first_conversation(
            incoming, _bot(), identity, object()
        )  # type: ignore[arg-type]
    return result, create


async def test_linked_identity_does_not_grant_a_bot_console_history() -> None:
    result, create = await _first(
        _incoming(), SimpleNamespace(user_id=USER), binding=SimpleNamespace(agent_id=AGENT)
    )
    assert result == FRESH
    assert create.await_args.kwargs["user_id"] == USER


@pytest.mark.parametrize(
    ("chat_type", "user", "binding"),
    [
        ("group", USER, SimpleNamespace(agent_id=AGENT)),
        ("private", None, SimpleNamespace(agent_id=AGENT)),
        ("private", USER, None),
    ],
    ids=["a-room", "an-unlinked-sender", "a-bot-with-no-agent"],
)
async def test_anything_else_gets_a_conversation_of_its_own(chat_type, user, binding) -> None:
    result, create = await _first(
        _incoming(chat_type), SimpleNamespace(user_id=user), binding=binding
    )

    assert result == FRESH
    assert create.await_args.kwargs["organization_id"] == ORG
    assert create.await_args.kwargs["user_id"] == user


@pytest.mark.parametrize(
    ("platform", "title"),
    [
        ("sms", "SMS Chat"),
        ("imessage", "iMessage Chat"),
        ("whatsapp", "WhatsApp Chat"),
        ("teams", "Microsoft Teams Chat"),
        ("telegram", "Telegram Chat"),
    ],
)
async def test_a_chats_conversation_is_titled_with_the_platforms_own_name(
    platform: str, title: str
) -> None:
    incoming = SimpleNamespace(platform=platform, chat_type="group")

    _, create = await _first(incoming, SimpleNamespace(user_id=USER), binding=None)

    assert create.await_args.kwargs["title"] == title


def test_every_chat_platform_has_a_name_and_an_unknown_one_is_capitalised() -> None:
    from app.services.channels.base import platform_name

    assert [
        platform_name(key)
        for key in (
            "slack",
            "telegram",
            "mattermost",
            "teams",
            "discord",
            "matrix",
            "whatsapp",
            "sms",
            "imessage",
            "email",
        )
    ] == [
        "Slack",
        "Telegram",
        "Mattermost",
        "Microsoft Teams",
        "Discord",
        "Matrix",
        "WhatsApp",
        "SMS",
        "iMessage",
        "Email",
    ]
    assert platform_name("acme") == "Acme"
