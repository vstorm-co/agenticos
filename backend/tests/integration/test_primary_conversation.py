"""The stable private conversation per person, organization and agent (#2575)."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.primary_conversation import PrimaryConversation
from app.db.models.user import User
from app.services.primary_conversation import PrimaryConversationService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _world(db: AsyncSession):
    users = [
        User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name=n) for n in "AB"
    ]
    db.add_all(users)
    await db.flush()
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=users[0].id
    )
    db.add(org)
    await db.flush()
    for user in users:
        db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    agents = []
    for name in ("Finance", "Support"):
        agent = Agent(
            organization_id=org.id,
            name=name,
            created_by_user_id=users[0].id,
            slug=f"a-{uuid.uuid4().hex[:8]}",
        )
        db.add(agent)
        agents.append(agent)
    await db.flush()
    ctxs = [
        AuthContext(user_id=u.id, organization_id=org.id, role=OrgRoleName.OWNER) for u in users
    ]
    return org, users, agents, ctxs


async def test_the_same_person_and_agent_always_get_the_same_conversation(db: AsyncSession) -> None:
    org, users, agents, ctxs = await _world(db)
    service = PrimaryConversationService(db)

    first = await service.open(ctxs[0], agents[0].id)
    again = await service.open(ctxs[0], agents[0].id)

    assert first == again
    conversation = await db.get(Conversation, first)
    assert conversation is not None and conversation.user_id == users[0].id
    assert conversation.title == "Finance" and conversation.project_id is None


async def test_each_person_and_each_agent_has_their_own(db: AsyncSession) -> None:
    org, users, agents, ctxs = await _world(db)
    service = PrimaryConversationService(db)

    mine = await service.open(ctxs[0], agents[0].id)
    other_agent = await service.open(ctxs[0], agents[1].id)
    colleague = await service.open(ctxs[1], agents[0].id)

    assert len({mine, other_agent, colleague}) == 3


async def test_an_agent_that_is_not_there_or_not_visible_is_a_404(db: AsyncSession) -> None:
    org, users, agents, ctxs = await _world(db)
    foreign = (await _world(db))[2][0]

    with pytest.raises(NotFoundError):
        await PrimaryConversationService(db).open(ctxs[0], uuid.uuid4())
    with pytest.raises(NotFoundError):
        await PrimaryConversationService(db).open(ctxs[0], foreign.id)


async def test_clearing_the_conversation_lets_the_next_request_open_a_fresh_one(
    db: AsyncSession,
) -> None:
    org, users, agents, ctxs = await _world(db)
    service = PrimaryConversationService(db)
    first = await service.open(ctxs[0], agents[0].id)
    gone = await db.get(Conversation, first)
    await db.delete(gone)
    await db.flush()

    second = await service.open(ctxs[0], agents[0].id)

    assert second != first
    assert await db.scalar(select(func.count()).select_from(PrimaryConversation)) == 1


async def test_a_concurrent_opener_that_lost_the_race_keeps_the_winners_conversation(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, users, agents, ctxs = await _world(db)
    service = PrimaryConversationService(db)
    winner = await service.open(ctxs[1], agents[0].id)
    # Make this caller miss the existing row on its first read, as a racer would.
    real = db.scalar
    calls = {"n": 0}

    async def blind_first(statement, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real(statement, *args, **kwargs)

    # Seed the row for ctxs[0] as the "winner" the racer will find on its second read.
    seeded = await service.open(ctxs[0], agents[0].id)
    monkeypatch.setattr(db, "scalar", blind_first)

    result = await service.open(ctxs[0], agents[0].id)

    assert result == seeded and winner != seeded
    assert await db.scalar(select(func.count()).select_from(Conversation)) == 2


async def test_a_conversation_first_reached_from_a_channel_is_named_for_the_agent(
    db: AsyncSession,
) -> None:
    org, users, agents, ctxs = await _world(db)

    opened = await PrimaryConversationService(db).ensure(
        organization_id=org.id, user_id=users[0].id, agent_id=agents[1].id
    )

    conversation = await db.get(Conversation, opened)
    assert conversation is not None and conversation.title == "Support"


@pytest.mark.parametrize("private", [True, False])
async def test_imessage_keeps_private_console_history_separate_from_channel_history(
    db: AsyncSession,
    private: bool,
) -> None:
    import httpx

    from app.db.models.agent_exposure import AgentExposure
    from app.db.models.channel_bot import ChannelBot
    from app.db.models.channel_identity import ChannelIdentity
    from app.services.channels.imessage import ImessageAdapter
    from app.services.channels.router import ChannelMessageRouter

    org, users, agents, ctxs = await _world(db)
    bot = ChannelBot(
        organization_id=org.id, platform="imessage", name="Mac", token_encrypted="sealed"
    )
    identity = ChannelIdentity(
        platform="imessage", platform_user_id="ada@example.com", user_id=users[0].id
    )
    db.add_all([bot, identity])
    await db.flush()
    db.add(
        AgentExposure(
            organization_id=org.id, agent_id=agents[0].id, channel_bot_id=bot.id, surface="imessage"
        )
    )
    await db.flush()
    console = await PrimaryConversationService(db).open(ctxs[0], agents[0].id)
    adapter = ImessageAdapter(httpx.MockTransport(lambda _request: httpx.Response(200)))
    try:
        incoming = adapter.parse_incoming(
            {
                "type": "new-message",
                "data": {
                    "guid": "message",
                    "text": "Hello",
                    "isFromMe": False,
                    "handle": {"address": "ada@example.com"},
                    "chats": [
                        {"guid": "iMessage;-;ada@example.com" if private else "iMessage;+;group"}
                    ],
                },
            },
            str(bot.id),
        )
        assert incoming is not None
        chosen = await ChannelMessageRouter._first_conversation(incoming, bot, identity, db)
    finally:
        await adapter.aclose()
    assert chosen != console
    same_owner = await PrimaryConversationService(db).open(ctxs[0], agents[0].id)
    other_owner = await PrimaryConversationService(db).open(ctxs[1], agents[0].id)
    assert same_owner == console
    assert other_owner != console


def _backfill(session: Session) -> None:
    path = Path(__file__).parents[2] / "alembic/versions/0258_primary_channel_history.py"
    spec = importlib.util.spec_from_file_location("primary_channel_history", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(session.connection())):
        migration.upgrade()


@pytest.mark.parametrize(
    ("chat_type", "recorded_agent", "adopt"),
    [
        ("private", True, True),
        ("group", True, False),
        ("private", False, False),
    ],
)
async def test_only_a_verified_private_legacy_session_is_adopted(
    db: AsyncSession, chat_type: str, recorded_agent: bool, adopt: bool
) -> None:
    from app.db.models.agent_exposure import AgentExposure
    from app.db.models.channel_bot import ChannelBot
    from app.db.models.channel_identity import ChannelIdentity
    from app.db.models.channel_session import ChannelSession

    org, users, agents, ctxs = await _world(db)
    conversation = Conversation(organization_id=org.id, user_id=users[0].id, title="Existing")
    bot = ChannelBot(organization_id=org.id, platform="sms", name="Finance", token_encrypted="x")
    identity = ChannelIdentity(platform="sms", platform_user_id="+1555", user_id=users[0].id)
    db.add_all([conversation, bot, identity])
    await db.flush()
    db.add(
        AgentExposure(
            organization_id=org.id, agent_id=agents[0].id, channel_bot_id=bot.id, surface="sms"
        )
    )
    db.add(
        ChannelSession(
            bot_id=bot.id,
            identity_id=identity.id,
            platform_chat_id="+1555",
            chat_type=chat_type,
            conversation_id=conversation.id,
        )
    )
    await db.flush()
    db.add(
        AgentRun(
            organization_id=org.id,
            agent_id=agents[0 if recorded_agent else 1].id,
            conversation_id=conversation.id,
        )
    )
    await db.flush()
    await db.run_sync(_backfill)
    primary = await PrimaryConversationService(db).open(ctxs[0], agents[0].id)
    assert (primary == conversation.id) is adopt
    assert await db.get(Conversation, conversation.id) is not None

    # Reapplying cannot replace an existing choice with some other old thread.
    await db.run_sync(_backfill)
    existing = await PrimaryConversationService(db).open(ctxs[0], agents[0].id)
    assert existing == primary
    deleted = await db.get(Conversation, primary)
    assert deleted is not None
    await db.delete(deleted)
    await db.flush()
    fresh = await PrimaryConversationService(db).open(ctxs[0], agents[0].id)
    assert fresh != primary and fresh != conversation.id


async def test_rebinding_a_bot_rotates_the_previous_agents_primary_history(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models.agent_exposure import AgentExposure
    from app.db.models.channel_bot import ChannelBot
    from app.db.models.channel_identity import ChannelIdentity
    from app.services.channels.base import IncomingMessage
    from app.services.channels.router import ChannelMessageRouter

    org, users, agents, ctxs = await _world(db)
    bot = ChannelBot(
        organization_id=org.id, platform="sms", name="Phone", token_encrypted="x", is_active=True
    )
    identity = ChannelIdentity(platform="sms", platform_user_id="+15550000000", user_id=users[0].id)
    db.add_all([bot, identity])
    await db.flush()
    exposure = AgentExposure(
        organization_id=org.id, agent_id=agents[0].id, channel_bot_id=bot.id, surface="sms"
    )
    db.add(exposure)
    await db.flush()
    incoming = IncomingMessage(
        platform="sms",
        bot_id=str(bot.id),
        platform_user_id=identity.platform_user_id,
        platform_chat_id=identity.platform_user_id,
        chat_type="private",
        text="Hello",
        raw={},
    )
    from unittest.mock import AsyncMock

    from app.services.channels import sms_prompts

    forget = AsyncMock()
    monkeypatch.setattr(sms_prompts, "forget", forget)
    router = ChannelMessageRouter()
    session = await router._resolve_session(incoming, bot, identity, db)
    previous = session.conversation_id
    first_primary = await PrimaryConversationService(db).open(ctxs[0], agents[0].id)
    assert previous != first_primary
    # Simulate a session created by the legacy private-history sharing policy.
    session.conversation_id = first_primary
    await db.flush()
    await db.delete(exposure)
    await db.flush()
    db.add(
        AgentExposure(
            organization_id=org.id, agent_id=agents[1].id, channel_bot_id=bot.id, surface="sms"
        )
    )
    await db.flush()
    changed = await router._resolve_session(incoming, bot, identity, db)
    second_primary = await PrimaryConversationService(db).open(ctxs[0], agents[1].id)
    assert changed.conversation_id not in {first_primary, second_primary, previous}
    forget.assert_awaited_once_with(str(bot.id), identity.platform_user_id, platform="sms")
