"""Knowledge gaps against Postgres - what is kept, for how long, and for whom.

The claims a mocked session cannot make:

- a run's knowledge searches are stored with their best similarity, and go
  with the run and with the conversation they came from;
- a person's export carries the searches made while answering them, and their
  erasure removes them, a run with no conversation included;
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import KnowledgeSearch
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import knowledge_gap_repo
from app.schemas.knowledge_gap import KnowledgeSearchRecord
from app.services.personal_data import PersonalDataService
from app.services.user import UserService

pytestmark = pytest.mark.anyio

_START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _owner(db) -> AuthContext:
    person = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=person.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=person.id, role="owner")
    )
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


async def _knowledge_base(db, ctx: AuthContext, name: str = "handbook") -> KnowledgeBase:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        name=name,
        collection_name=f"{name}_{uuid.uuid4().hex[:8]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
    )
    db.add(kb)
    await db.flush()
    return kb


async def _agent(db, ctx: AuthContext) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _turn(
    db, ctx: AuthContext, agent: Agent, *, question: str = "Where do I park?"
) -> tuple[AgentRun, Message]:
    """A conversation with one question and the agent's answer to it."""
    conversation = Conversation(
        id=uuid.uuid4(), user_id=ctx.user_id, organization_id=ctx.organization_id, title="Office"
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        conversation_id=conversation.id,
        status="completed",
        started_at=_START,
        ended_at=_START + timedelta(minutes=1),
    )
    db.add(run)
    await db.flush()
    answer = None
    for role, content in (("user", question), ("assistant", "I could not find that.")):
        answer = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            run_id=run.id,
            role=role,
            content=content,
        )
        db.add(answer)
        await db.flush()
    assert answer is not None
    return run, answer


async def _searched(
    db,
    ctx: AuthContext,
    run: AgentRun,
    kb: KnowledgeBase,
    *,
    query: str = "parking",
    top_similarity: float | None = 0.12,
) -> None:
    await knowledge_gap_repo.record_searches(
        db,
        [
            KnowledgeSearchRecord(
                agent_id=run.agent_id,
                knowledge_base_ids=(kb.id,),
                query=query,
                result_count=0 if top_similarity is None else 3,
                top_similarity=top_similarity,
            )
        ],
        organization_id=ctx.organization_id,
        run_id=run.id,
        conversation_id=run.conversation_id,
    )


async def _search_count(db, run_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeSearch)
            .where(KnowledgeSearch.run_id == run_id)
        )
    ).scalar_one()


async def test_a_runs_searches_are_stored_with_their_best_similarity(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))

    await _searched(db, ctx, run, kb, query="visitor parking", top_similarity=0.21)

    stored = (
        await db.execute(select(KnowledgeSearch).where(KnowledgeSearch.run_id == run.id))
    ).scalar_one()
    assert stored.organization_id == ctx.organization_id
    assert stored.conversation_id == run.conversation_id
    assert stored.knowledge_base_ids == [kb.id]
    assert stored.query == "visitor parking"
    assert stored.top_similarity == pytest.approx(0.21)


async def test_deleting_the_run_takes_its_searches(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb)
    run_id = run.id

    await db.execute(delete(Message).where(Message.run_id == run_id))
    await db.execute(delete(AgentRun).where(AgentRun.id == run_id))

    assert await _search_count(db, run_id) == 0


async def test_deleting_the_conversation_takes_its_searches(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb)
    run_id = run.id

    await db.execute(delete(Conversation).where(Conversation.id == run.conversation_id))

    assert await _search_count(db, run_id) == 0


async def _api_run(db, ctx: AuthContext, agent: Agent, user_id: uuid.UUID) -> AgentRun:
    """A run somebody started over the HTTP API, which keeps no conversation."""
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=user_id,
        status="completed",
        surface="api",
        started_at=_START,
    )
    db.add(run)
    await db.flush()
    return run


async def test_a_persons_export_carries_the_searches_made_for_them_and_nobody_elses(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    person = await _user(db)
    person_id = person.id
    await _searched(db, ctx, await _api_run(db, ctx, agent, person_id), kb, query="their query")
    await _searched(db, ctx, await _api_run(db, ctx, agent, ctx.user_id), kb, query="not theirs")

    export = await PersonalDataService(db).export(person_id, actor_user_id=person_id)

    assert [row["query"] for row in export.knowledge_searches] == ["their query"]


async def test_erasing_a_person_removes_the_searches_of_their_api_runs(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    person = await _user(db)
    person_id = person.id
    theirs = await _api_run(db, ctx, agent, person_id)
    others = await _api_run(db, ctx, agent, ctx.user_id)
    theirs_id, others_id = theirs.id, others.id
    await _searched(db, ctx, theirs, kb)
    await _searched(db, ctx, others, kb)

    await UserService(db).delete(person_id)

    assert await _search_count(db, theirs_id) == 0
    assert await _search_count(db, others_id) == 1
