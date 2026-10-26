"""Late buttons must carry the original channel identity through fresh admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.channels import router as module
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter

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


@pytest.mark.parametrize("fallback", [False, True])
async def test_linked_and_unlinked_room_senders_keep_their_recorded_identity(access, fallback):
    s = access
    s.run.initiated_by_publisher_fallback = fallback
    if fallback:
        s.identity.user_id = None
    assert await ChannelMessageRouter().may_continue(s.db, s.run, s.incoming)
    s.mocks["is_still_member"].assert_awaited_once_with(s.bot, "C1", "U1")


@pytest.mark.security
@pytest.mark.parametrize(
    "refusal",
    [
        "missing_bot",
        "off",
        "tenant",
        "platform",
        "surface",
        "missing_session",
        "inactive_session",
        "chat_kind",
        "conversation",
        "no_identity_id",
        "missing_identity",
        "identity_platform",
        "identity_sender",
        "missing_exposure",
        "paused",
        "policy",
        "require_link",
        "jwt_linked",
        "linked_other_user",
        "inactive_user",
        "left_room",
    ],
)
async def test_revoked_or_mismatched_admission_never_reaches_the_helper(access, refusal):
    s = access
    if refusal.startswith("missing_"):
        name = {
            "missing_bot": "get_for_org",
            "missing_session": "get_by_bot_and_chat",
            "missing_identity": "get_by_id",
            "missing_exposure": "get_for_bot",
        }[refusal]
        s.mocks[name].return_value = None
    elif refusal == "off":
        s.bot.is_active = False
    elif refusal == "tenant":
        s.bot.organization_id = uuid4()
    elif refusal == "platform":
        s.bot.platform = "teams"
    elif refusal == "surface":
        s.run.surface = "web"
    elif refusal == "inactive_session":
        s.session.is_active = False
    elif refusal == "chat_kind":
        s.session.chat_type = "private"
    elif refusal == "conversation":
        s.session.conversation_id = uuid4()
    elif refusal == "no_identity_id":
        s.run.channel_identity_id = None
    elif refusal == "identity_platform":
        s.identity.platform = "teams"
    elif refusal == "identity_sender":
        s.identity.platform_user_id = "someone_else"
    elif refusal == "paused":
        s.exposure.is_active = False
    elif refusal == "policy":
        s.bot.access_policy = {"mode": "whitelist", "whitelist": []}
    elif refusal == "require_link":
        s.bot.access_policy = {"require_link": True}
    elif refusal == "jwt_linked":
        s.bot.access_policy = {"mode": "jwt_linked"}
    elif refusal == "linked_other_user":
        s.run.initiated_by_publisher_fallback = False
        s.identity.user_id = uuid4()
    elif refusal == "inactive_user":
        s.run.initiated_by_publisher_fallback = False
        s.mocks["get_active"].return_value = None
    elif refusal == "left_room":
        s.mocks["is_still_member"].return_value = False
    assert not await ChannelMessageRouter().may_continue(s.db, s.run, s.incoming)


async def test_private_linked_sender_does_not_need_a_room_directory(access):
    from dataclasses import replace

    s = access
    s.run.initiated_by_publisher_fallback = False
    s.session.chat_type = "private"
    incoming = replace(s.incoming, chat_type="private")
    assert await ChannelMessageRouter().may_continue(s.db, s.run, incoming)
    s.mocks["is_still_member"].assert_not_awaited()
