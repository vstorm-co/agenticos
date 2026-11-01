"""The stable private conversation per person, organization and agent (#2575)."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
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
