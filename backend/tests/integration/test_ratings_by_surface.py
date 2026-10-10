"""Which surface a rated answer was given on, and a chat rating counted as its rater's (#2084).

A thumbs pressed in Slack rates an answer in a conversation that belongs to
nobody - a channel conversation has no user - so "the ratings I gave" can no
longer be read as "the ratings in my conversations".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import message_rating as rating_repo

pytestmark = pytest.mark.anyio

_NOW = datetime.now(UTC)


async def _user(db) -> User:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _setup(db) -> tuple[Organization, User, Agent]:
    owner = await _user(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    agent = Agent(
        organization_id=organization.id,
        owner_user_id=owner.id,
        name="Helper",
        slug=f"helper-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Helper").model_dump(mode="json"),
        visibility=Visibility.ORG.value,
    )
    db.add(agent)
    await db.flush()
    return organization, owner, agent


async def _rated(
    db,
    organization: Organization,
    agent: Agent,
    rater: User,
    *,
    surface: str | None,
    rating: int,
    owner: User | None,
) -> None:
    conversation = Conversation(organization_id=organization.id, user_id=owner and owner.id)
    db.add(conversation)
    await db.flush()
    run_id = None
    if surface is not None:
        run = AgentRun(
            organization_id=organization.id,
            agent_id=agent.id,
            conversation_id=conversation.id,
            status="completed",
            surface=surface,
        )
        db.add(run)
        await db.flush()
        run_id = run.id
    message = Message(
        conversation_id=conversation.id, role="assistant", content="ok", run_id=run_id
    )
    db.add(message)
    await db.flush()
    db.add(MessageRating(message_id=message.id, user_id=rater.id, rating=rating))
    await db.flush()


async def test_ratings_are_counted_per_surface_and_a_chat_rating_is_its_rater_s(db) -> None:
    organization, owner, agent = await _setup(db)
    colleague = await _user(db)
    await _rated(db, organization, agent, owner, surface="web", rating=1, owner=owner)
    await _rated(db, organization, agent, owner, surface=None, rating=-1, owner=owner)
    await _rated(db, organization, agent, owner, surface="slack", rating=1, owner=None)
    await _rated(db, organization, agent, colleague, surface="slack", rating=-1, owner=None)

    window = {"start": _NOW - timedelta(days=1), "end": _NOW + timedelta(days=1)}
    org = await rating_repo.get_rating_summary_scoped(db, organization_id=organization.id, **window)
    mine = await rating_repo.get_rating_summary_scoped(
        db, organization_id=organization.id, user_id=owner.id, **window
    )
    everywhere = await rating_repo.get_rating_summary(db, **window)

    assert org["ratings_by_surface"] == [
        {"surface": "slack", "likes": 1, "dislikes": 1},
        {"surface": "web", "likes": 1, "dislikes": 1},
    ]
    assert mine["total_ratings"] == 3
    assert {"surface": "slack", "likes": 1, "dislikes": 0} in mine["ratings_by_surface"]
    assert any(row["surface"] == "slack" for row in everywhere["ratings_by_surface"])


async def test_a_person_s_recent_chats_with_a_bot_are_newest_first_and_titled(db) -> None:
    from app.db.models.channel_bot import ChannelBot
    from app.db.models.channel_identity import ChannelIdentity
    from app.db.models.channel_session import ChannelSession
    from app.repositories import channel_session_repo

    organization, _owner, _agent = await _setup(db)
    bot = ChannelBot(
        organization_id=organization.id,
        platform="slack",
        name="Helper",
        token_encrypted="sealed",
        secret_key_version=1,
    )
    asker = ChannelIdentity(platform="slack", platform_user_id=f"U{uuid.uuid4().hex[:8]}")
    other = ChannelIdentity(platform="slack", platform_user_id=f"U{uuid.uuid4().hex[:8]}")
    db.add_all([bot, asker, other])
    await db.flush()
    titled = Conversation(organization_id=organization.id, title="Refund for order 42")
    db.add(titled)
    await db.flush()
    db.add_all(
        [
            ChannelSession(
                bot_id=bot.id,
                identity_id=asker.id,
                platform_chat_id="C1:1.1",
                last_message_at=_NOW - timedelta(hours=2),
            ),
            ChannelSession(
                bot_id=bot.id,
                identity_id=asker.id,
                conversation_id=titled.id,
                platform_chat_id="C1:2.2",
                last_message_at=_NOW,
            ),
            ChannelSession(bot_id=bot.id, identity_id=other.id, platform_chat_id="C1:3.3"),
        ]
    )
    await db.flush()

    recent = await channel_session_repo.recent_for_identity(db, bot_id=bot.id, identity_id=asker.id)

    assert [(session.platform_chat_id, title) for session, title in recent] == [
        ("C1:2.2", "Refund for order 42"),
        ("C1:1.1", None),
    ]
