"""A run that began before an erasure writes nothing back into the erased memory.

The tools are driven as a run reaches them - with its `run_id` - after "forget me"
or a cleared agent, which is what a run parked on an approval and then resumed does.
Each memory call opens its own session; here it is the test's, so the rows the
erasure left are the ones the assertions read.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.agents.audience import RunAudience
from app.agents.capabilities.memory_files._toolset import MemoryToolset
from app.agents.deps import AgentDeps
from app.core.memory_keys import person_owner_key, room_owner_key
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.memory import AgentMemoryFile
from app.db.models.memory_claim import MemoryClaim
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services import memory as memory_store
from app.services.access import member_context
from app.services.memory import MemoryService, _native, _runtime

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture(autouse=True)
def _own_session(monkeypatch: pytest.MonkeyPatch, db: AsyncSession) -> None:
    @asynccontextmanager
    async def reuse():
        yield db

    monkeypatch.setattr(_native, "get_db_context", reuse)
    monkeypatch.setattr(_runtime, "get_db_context", reuse)


async def _world(db: AsyncSession, *, started: timedelta = timedelta(hours=-1)):
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    agent = Agent(
        organization_id=org.id,
        name="Helper",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        started_at=datetime.now(UTC) + started,
    )
    db.add(run)
    await db.flush()
    return user, org, agent, run


def _ctx(user: User, org: Organization, agent: Agent, run: AgentRun, *, room: str | None = None):
    deps = AgentDeps(
        organization_id=org.id,
        agent_id=agent.id,
        conversation_id=None,
        run_id=run.id,
        run_person=user.id,
        user_id=str(user.id),
        audience=RunAudience(user_id=user.id, room_key=room, writes_memory=True),
    )
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), retry=0, max_retries=1)


async def _forget(db: AsyncSession, user: User, org: Organization) -> None:
    ctx = await member_context(db, organization_id=org.id, user_id=user.id)
    assert ctx is not None
    await MemoryService(db).forget_person(ctx, user.id)


async def _notes(db: AsyncSession, owner_key: str) -> int:
    return await db.scalar(select(func.count()).where(AgentMemoryFile.owner_key == owner_key)) or 0


async def _claims(db: AsyncSession, scope_key: str) -> int:
    return await db.scalar(select(func.count()).where(MemoryClaim.scope_key == scope_key)) or 0


async def test_remember_after_forget_me_records_nothing_and_says_why(db: AsyncSession) -> None:
    user, org, agent, run = await _world(db)
    await _forget(db, user, org)

    said = await MemoryToolset().remember(_ctx(user, org, agent, run), "Prefers short answers")

    assert "erased after this conversation began" in said
    assert await _claims(db, person_owner_key(user.id)) == 0


async def test_write_memory_after_forget_me_saves_nothing_and_says_why(db: AsyncSession) -> None:
    user, org, agent, run = await _world(db)
    await _forget(db, user, org)

    said = await MemoryToolset().write_memory(_ctx(user, org, agent, run), "prefs", "Short")

    assert "erased after this conversation began" in said
    assert await _notes(db, person_owner_key(user.id)) == 0


async def test_edit_memory_after_forget_me_changes_nothing_and_says_why(db: AsyncSession) -> None:
    user, org, agent, run = await _world(db)
    ctx = _ctx(user, org, agent, run)
    tools = MemoryToolset()
    assert await tools.write_memory(ctx, "prefs", "Short") == "Saved note 'prefs'."
    # A note written after the erasure, by a run that began after it, is the one
    # an older run must not overwrite with what it read before.
    await _forget(db, user, org)
    later = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        started_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    db.add(later)
    await db.flush()
    assert await tools.write_memory(_ctx(user, org, agent, later), "prefs", "New") == (
        "Saved note 'prefs'."
    )

    said = await tools.edit_memory(ctx, "prefs", "Short, as before the erasure")

    assert "erased after this conversation began" in said
    note = await db.scalar(
        select(AgentMemoryFile.content).where(
            AgentMemoryFile.owner_key == person_owner_key(user.id)
        )
    )
    assert note == "New"


async def test_a_run_begun_after_the_erasure_writes_as_usual(db: AsyncSession) -> None:
    user, org, agent, _ = await _world(db)
    await _forget(db, user, org)
    _, _, _, later = await _world(db, started=timedelta(minutes=1))
    later.organization_id, later.agent_id, later.user_id = org.id, agent.id, user.id
    await db.flush()
    ctx = _ctx(user, org, agent, later)

    assert (await MemoryToolset().remember(ctx, "Prefers short answers")).startswith("Recorded")
    assert await MemoryToolset().write_memory(ctx, "prefs", "Short") == "Saved note 'prefs'."
    assert await _claims(db, person_owner_key(user.id)) == 1


async def test_a_room_note_after_its_agent_was_cleared_is_refused(db: AsyncSession) -> None:
    user, org, agent, run = await _world(db)
    room = room_owner_key("slack", "C1")
    ctx = await member_context(db, organization_id=org.id, user_id=user.id)
    assert ctx is not None
    await MemoryService(db).clear_agent(ctx, agent.id)

    with pytest.raises(memory_store.ErasedDuringRun):
        await memory_store.write_file(
            organization_id=org.id,
            agent_id=agent.id,
            owner_key=room,
            name="prefs",
            content="Short",
            description=None,
            kind="note",
            run_id=run.id,
        )
    assert await _notes(db, room) == 0


async def test_forgetting_someone_else_does_not_stop_a_room_note(db: AsyncSession) -> None:
    user, org, agent, run = await _world(db)
    await _forget(db, user, org)
    room = room_owner_key("slack", "C1")

    assert await memory_store.write_file(
        organization_id=org.id,
        agent_id=agent.id,
        owner_key=room,
        name="prefs",
        content="Short",
        description=None,
        kind="note",
        run_id=run.id,
    )


async def test_a_run_that_cannot_be_found_is_not_refused(db: AsyncSession) -> None:
    user, org, agent, _ = await _world(db)
    await _forget(db, user, org)

    assert await memory_store.write_file(
        organization_id=org.id,
        agent_id=agent.id,
        owner_key=person_owner_key(user.id),
        name="prefs",
        content="Short",
        description=None,
        kind="note",
        run_id=uuid.uuid4(),
    )


async def test_a_delegate_is_held_to_the_agent_whose_store_it_writes(db: AsyncSession) -> None:
    user, org, parent, run = await _world(db)
    specialist = Agent(
        organization_id=org.id,
        name="Specialist",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(specialist)
    await db.flush()
    ctx = await member_context(db, organization_id=org.id, user_id=user.id)
    assert ctx is not None
    room = room_owner_key("slack", "C1")

    async def write(agent: Agent, name: str) -> bool:
        return await memory_store.write_file(
            organization_id=org.id,
            agent_id=agent.id,
            owner_key=room,
            name=name,
            content="Short",
            description=None,
            kind="note",
            run_id=run.id,
        )

    await MemoryService(db).clear_agent(ctx, parent.id)
    assert await write(specialist, "kept")
    await MemoryService(db).clear_agent(ctx, specialist.id)
    with pytest.raises(memory_store.ErasedDuringRun):
        await write(specialist, "refused")


async def test_a_cleared_agent_does_not_refuse_a_profile_claim_no_agent_holds(
    db: AsyncSession,
) -> None:
    user, org, agent, run = await _world(db)
    ctx = await member_context(db, organization_id=org.id, user_id=user.id)
    assert ctx is not None
    await MemoryService(db).clear_agent(ctx, agent.id)

    said = await MemoryToolset().remember(
        _ctx(user, org, agent, run), "Prefers short answers", profile=True
    )

    assert said.startswith("Recorded")


async def test_asking_about_no_person_and_no_agent_finds_no_erasure(db: AsyncSession) -> None:
    from app.repositories import audit_log_repo

    _, org, _, run = await _world(db)

    assert not await audit_log_repo.memory_erased_since(
        db, organization_id=org.id, user_id=None, agent_id=None, since=run.started_at
    )


async def _agent_lock_free_elsewhere(engine: AsyncEngine, agent: Agent) -> bool:
    from app.db.locks import LockScope, try_hold_subject

    async with AsyncSession(engine) as other:
        return await try_hold_subject(other, LockScope.MEMORY_PER_AGENT, agent.id)


async def test_a_write_to_an_agents_memory_holds_off_clearing_it(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    _, org, agent, _ = await _world(db)
    assert await _agent_lock_free_elsewhere(engine, agent)

    await memory_store.write_file(
        organization_id=org.id,
        agent_id=agent.id,
        owner_key=room_owner_key("slack", "C1"),
        name="prefs",
        content="Short",
        description=None,
        kind="note",
        run_id=None,
    )

    assert not await _agent_lock_free_elsewhere(engine, agent)


async def test_clearing_an_agents_memory_holds_off_writes_to_it(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    user, org, agent, _ = await _world(db)
    ctx = await member_context(db, organization_id=org.id, user_id=user.id)
    assert ctx is not None

    await MemoryService(db).clear_agent(ctx, agent.id)

    assert not await _agent_lock_free_elsewhere(engine, agent)
