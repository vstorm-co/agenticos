"""Which surface a rated answer was given on, and a chat rating counted as its rater's (#2084).

A thumbs pressed in Slack rates an answer in a conversation that belongs to
nobody - a channel conversation has no user - so "the ratings I gave" can no
longer be read as "the ratings in my conversations".
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message
from app.db.models.group import Group, GroupMember
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import message_rating as rating_repo
from app.repositories import personal_data

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


async def test_channel_participants_keep_one_vote_each_and_comments_survive_vote_changes(
    db: AsyncSession,
) -> None:
    organization, owner, agent = await _setup(db)
    conversation = Conversation(organization_id=organization.id)
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        organization_id=organization.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        status="completed",
        surface="mattermost",
    )
    db.add(run)
    await db.flush()
    message = Message(
        conversation_id=conversation.id, role="assistant", content="answer", run_id=run.id
    )
    identities = [
        ChannelIdentity(platform="mattermost", platform_user_id=uuid.uuid4().hex) for _ in range(2)
    ]
    db.add_all([message, *identities])
    await db.flush()
    first = await rating_repo.upsert_channel_rating(
        db, message_id=message.id, channel_identity_id=identities[0].id, rating=1
    )
    await rating_repo.upsert_channel_rating(
        db, message_id=message.id, channel_identity_id=identities[1].id, rating=-1
    )
    await rating_repo.upsert_channel_rating(
        db,
        message_id=message.id,
        channel_identity_id=identities[0].id,
        rating=None,
        comment="Check the dates",
    )
    changed = await rating_repo.upsert_channel_rating(
        db, message_id=message.id, channel_identity_id=identities[0].id, rating=-1
    )
    assert changed.id == first.id
    assert changed.user_id is None
    assert changed.comment == "Check the dates"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MessageRating)
            .where(MessageRating.message_id == message.id)
        )
        == 2
    )
    counts = await rating_repo.get_rating_counts_for_messages(db, message_ids=[message.id])
    assert counts[message.id] == {"likes": 0, "dislikes": 2}
    # Linking transfers the vote to the same author the console uses.
    identities[0].user_id = owner.id
    await db.flush()
    await rating_repo.adopt_channel_ratings(db, identity_id=identities[0].id, user_id=owner.id)
    owned = await rating_repo.get_rating_by_message_and_user(db, message.id, owner.id)
    assert owned is not None
    assert owned.comment == "Check the dates"
    assert owned.channel_identity_id is None
    mine = await rating_repo.get_rating_summary_scoped(
        db,
        organization_id=organization.id,
        user_id=owner.id,
        start=_NOW - timedelta(days=1),
        end=_NOW + timedelta(days=1),
    )
    assert mine["total_ratings"] == 1
    assert [row.id for row in await personal_data.ratings_of(db, owner.id)] == [owned.id]
    group = Group(organization_id=organization.id, name="Engineering")
    db.add(group)
    await db.flush()
    db.add(GroupMember(group_id=group.id, user_id=owner.id))
    await db.flush()
    window = {"start": _NOW - timedelta(days=1), "end": _NOW + timedelta(days=1)}
    grouped = await rating_repo.ratings_by_group(db, organization_id=organization.id, **window)
    assert grouped == [(group.id, 0, 1)]
    down_rated = await rating_repo.group_down_rated(
        db, organization_id=organization.id, group_id=group.id, limit=10, **window
    )
    assert len(down_rated) == 1
    assert down_rated[0][1:4] == ("Check the dates", run.id, agent.id)
    stranger, _, _ = await _setup(db)
    other = await rating_repo.get_rating_summary_scoped(
        db,
        organization_id=stranger.id,
        start=_NOW - timedelta(days=1),
        end=_NOW + timedelta(days=1),
    )
    assert other["total_ratings"] == 0


@pytest.mark.parametrize("channel_is_newer", [False, True])
async def test_linking_unifies_channel_and_console_ratings(
    db: AsyncSession, channel_is_newer: bool
) -> None:
    organization, owner, _ = await _setup(db)
    conversation = Conversation(organization_id=organization.id)
    db.add(conversation)
    await db.flush()
    message = Message(conversation_id=conversation.id, role="assistant", content="answer")
    identity = ChannelIdentity(platform="mattermost", platform_user_id=uuid.uuid4().hex)
    db.add_all([message, identity])
    await db.flush()
    channel_vote = await rating_repo.upsert_channel_rating(
        db,
        message_id=message.id,
        channel_identity_id=identity.id,
        rating=-1,
        comment="Channel opinion",
    )
    web_vote = await rating_repo.create_rating(
        db, message_id=message.id, user_id=owner.id, rating=1, comment="Web opinion"
    )
    channel_vote.updated_at = (
        _NOW + timedelta(minutes=1) if channel_is_newer else _NOW - timedelta(minutes=1)
    )
    web_vote.updated_at = _NOW
    identity.user_id = owner.id
    await db.flush()
    await rating_repo.adopt_channel_ratings(db, identity_id=identity.id, user_id=owner.id)
    db.expire(web_vote)
    owned = await rating_repo.get_rating_by_message_and_user(db, message.id, owner.id)
    assert owned is not None
    assert owned.rating == (-1 if channel_is_newer else 1)
    assert owned.comment == ("Channel opinion" if channel_is_newer else "Web opinion")
    assert await rating_repo.get_user_ratings_for_messages(
        db, message_ids=[message.id], user_id=owner.id
    ) == {message.id: owned.rating}
    changed = await rating_repo.upsert_channel_rating(
        db, message_id=message.id, channel_identity_id=identity.id, rating=-1
    )
    assert changed.id == owned.id
    assert changed.user_id == owner.id
    counts = await rating_repo.get_rating_counts_for_messages(db, message_ids=[message.id])
    assert counts[message.id] == {"likes": 0, "dislikes": 1}
    await rating_repo.update_rating(db, changed, new_rating=1, comment="Changed in console")
    assert changed.comment == "Changed in console"
    await rating_repo.delete_rating(db, changed)
    assert await rating_repo.get_rating_by_message_and_user(db, message.id, owner.id) is None


async def test_channel_vote_refreshes_an_identity_cached_before_account_link(
    db: AsyncSession,
) -> None:
    organization, owner, _ = await _setup(db)
    conversation = Conversation(organization_id=organization.id)
    db.add(conversation)
    await db.flush()
    message = Message(conversation_id=conversation.id, role="assistant", content="answer")
    identity = ChannelIdentity(platform="mattermost", platform_user_id=uuid.uuid4().hex)
    db.add_all([message, identity])
    await db.flush()
    await rating_repo.create_rating(db, message_id=message.id, user_id=owner.id, rating=1)
    await db.execute(
        update(ChannelIdentity)
        .where(ChannelIdentity.id == identity.id)
        .values(user_id=owner.id)
        .execution_options(synchronize_session=False)
    )
    assert identity.user_id is None
    vote = await rating_repo.upsert_channel_rating(
        db, message_id=message.id, channel_identity_id=identity.id, rating=-1
    )
    assert vote.user_id == owner.id
    assert vote.channel_identity_id is None
    assert await rating_repo.get_rating_counts_for_messages(db, message_ids=[message.id]) == {
        message.id: {"likes": 0, "dislikes": 1}
    }
