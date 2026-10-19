"""A remote caller reading an A2A task gets what the run said last.

The answer was read off the run's turns oldest first and capped at 200, so a
run that wrote more than that answered with something it said early on. Turn
order is the database's identity column, which only a real database allocates.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

pytestmark = pytest.mark.anyio


async def _run(db) -> AgentRun:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(
        id=uuid.uuid4(), user_id=user.id, organization_id=organization.id, title="A2A"
    )
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add_all([conversation, agent])
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=organization.id,
        agent_id=agent.id,
        user_id=user.id,
        conversation_id=conversation.id,
        surface=RunSurface.A2A.value,
        status=RunStatus.COMPLETED.value,
    )
    db.add(run)
    await db.flush()
    return run


async def test_the_latest_answer_is_read_however_long_the_run(db) -> None:
    run = await _run(db)
    turns = [("user", "Review clause 7")]
    turns += [("assistant", f"step {n}") for n in range(205)]
    turns += [("assistant", "Clause 7 caps liability at 2x fees."), ("assistant", "")]
    for role, content in turns:
        db.add(
            Message(conversation_id=run.conversation_id, run_id=run.id, role=role, content=content)
        )
        await db.flush()

    answer = await conversation_repo.last_answer_of_run(db, run.id)

    assert answer == "Clause 7 caps liability at 2x fees."
    assert await conversation_repo.last_answer_of_run(db, uuid.uuid4()) is None
