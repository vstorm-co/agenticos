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
    ensure = AsyncMock(return_value=PRIMARY)
    create = AsyncMock(return_value=SimpleNamespace(id=FRESH))
    with (
        patch(f"{ROUTER}.agent_exposure_repo.bound_to_bot", new=AsyncMock(return_value=binding)),
        patch(f"{ROUTER}.PrimaryConversationService") as service,
        patch(f"{ROUTER}.conversation_repo.create_conversation", new=create),
    ):
        service.return_value.ensure = ensure
        result = await ChannelMessageRouter._first_conversation(
            incoming, _bot(), identity, object()
        )  # type: ignore[arg-type]
    return result, ensure, create


async def test_a_linked_person_texting_a_bot_with_an_agent_continues_their_conversation() -> None:
    result, ensure, create = await _first(
        _incoming(), SimpleNamespace(user_id=USER), binding=SimpleNamespace(agent_id=AGENT)
    )

    assert result == PRIMARY and not create.await_count
    assert ensure.await_args.kwargs == {
        "organization_id": ORG,
        "user_id": USER,
        "agent_id": AGENT,
        "title": "Sms Chat",
    }


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
    result, ensure, create = await _first(
        _incoming(chat_type), SimpleNamespace(user_id=user), binding=binding
    )

    assert result == FRESH and not ensure.await_count
    assert create.await_args.kwargs["organization_id"] == ORG
    assert create.await_args.kwargs["user_id"] == user
