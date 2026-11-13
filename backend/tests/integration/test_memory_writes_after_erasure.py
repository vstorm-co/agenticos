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
from app.db.models.audit_log import AppAdminAuditLog
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
    await db.commit()
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
    await db.commit()
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
    kept = await write(specialist, "kept")
    assert kept
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


async def _claim_id(db: AsyncSession, scope_key: str) -> uuid.UUID:
    return (
        await db.scalars(
            select(MemoryClaim.id).where(
                MemoryClaim.scope_key == scope_key, MemoryClaim.status == "current"
            )
        )
    ).one()


async def test_a_correction_after_its_agent_was_cleared_changes_nothing_and_says_why(
    db: AsyncSession,
) -> None:
    user, org, agent, run = await _world(db)
    ctx = await member_context(db, organization_id=org.id, user_id=user.id)
    assert ctx is not None
    await MemoryService(db).clear_agent(ctx, agent.id)
    await db.commit()
    # A claim recorded after the clear, by a run that began after it, is the one an
    # older run must not supersede with what it read before.
    later = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        started_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    db.add(later)
    await db.flush()
    tools = MemoryToolset()
    assert (await tools.remember(_ctx(user, org, agent, later), "Prefers tea")).startswith(
        "Recorded"
    )
    claim_id = await _claim_id(db, person_owner_key(user.id))

    said = await tools.correct_memory(_ctx(user, org, agent, run), str(claim_id), "Coffee")

    assert "erased after this conversation began" in said
    assert await _claim_id(db, person_owner_key(user.id)) == claim_id
    assert await _claims(db, person_owner_key(user.id)) == 1


async def test_a_correction_holds_off_clearing_its_agents_memory(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    from app.repositories.memory_claim import ClaimScope
    from app.services.memory import _claims as claims

    user, org, agent, run = await _world(db)
    await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(user.id), agent.id),
        statement="Prefers tea",
        author_user_id=user.id,
    )
    claim_id = await _claim_id(db, person_owner_key(user.id))
    assert await _agent_lock_free_elsewhere(engine, agent)

    said = await MemoryToolset().correct_memory(
        _ctx(user, org, agent, run), str(claim_id), "Prefers coffee"
    )

    assert said.startswith("Corrected")
    assert not await _agent_lock_free_elsewhere(engine, agent)


async def test_a_run_admitted_while_an_erasure_commits_is_still_refused(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    user, org, agent, _ = await _world(db)
    await db.commit()

    async with AsyncSession(engine) as erasing:
        ctx = await member_context(erasing, organization_id=org.id, user_id=user.id)
        assert ctx is not None
        await MemoryService(erasing).forget_person(ctx, user.id)
        # Admitted after the erasure's entry is dated but before it commits, so the run
        # reads memory the erasure has not removed yet.
        async with AsyncSession(engine) as admitting:
            run = AgentRun(
                organization_id=org.id,
                agent_id=agent.id,
                user_id=user.id,
                started_at=datetime.now(UTC),
            )
            admitting.add(run)
            await admitting.flush()
            run_id = run.id
            await admitting.commit()
        await erasing.commit()

    erased_at = await db.scalar(
        select(AppAdminAuditLog.created_at).where(
            AppAdminAuditLog.action == "memory.person.forgotten",
            AppAdminAuditLog.target_id == str(user.id),
        )
    )
    started_at = await db.scalar(select(AgentRun.started_at).where(AgentRun.id == run_id))
    assert erased_at is not None and started_at is not None and erased_at < started_at
    with pytest.raises(memory_store.ErasedDuringRun):
        await _native.refuse_if_erased_during_run(
            db, owner_key=person_owner_key(user.id), agent_id=None, run_id=run_id
        )


async def test_an_erasure_from_another_cluster_is_judged_by_its_date_alone(
    db: AsyncSession,
) -> None:
    from app.repositories import audit_log_repo

    user, org, _, _ = await _world(db)
    await _forget(db, user, org)
    snapshot = await audit_log_repo.current_snapshot(db)
    assert snapshot is not None
    cluster = snapshot.partition("/")[0]
    later_than_it = datetime.now(UTC) + timedelta(hours=1)

    async def erased(snapshot: str) -> bool:
        return await audit_log_repo.memory_erased_since(
            db,
            organization_id=org.id,
            user_id=user.id,
            agent_id=None,
            since=later_than_it,
            snapshot=snapshot,
        )

    # A snapshot older than every transaction: in this cluster the erasure is later.
    assert await erased(f"{cluster}/1:1:")
    # Restored from another cluster, the ids mean nothing here; its date says earlier.
    assert not await erased("1/1:1:")


async def test_a_briefing_counts_what_was_written_during_an_erasure_as_before_it(
    db: AsyncSession,
) -> None:
    from app.repositories import audit_log_repo

    user, org, _, _ = await _world(db)
    await _forget(db, user, org)
    entry = await db.scalar(
        select(AppAdminAuditLog).where(
            AppAdminAuditLog.action == "memory.person.forgotten",
            AppAdminAuditLog.target_id == str(user.id),
        )
    )
    assert entry is not None and entry.details is not None

    latest = await audit_log_repo.latest_memory_erasure(db, organization_id=org.id, user_id=user.id)

    # The database's clock once the deletes were done, which a message's date is read on;
    # the entry's own date comes from the app's clock, and the later of the two counts.
    finished = datetime.fromisoformat(entry.details[audit_log_repo.ERASURE_FINISHED])
    assert latest == max(finished, entry.created_at)


async def test_without_the_clusters_identifier_time_alone_decides(db: AsyncSession) -> None:
    from sqlalchemy import text

    from app.repositories import audit_log_repo

    # What the identifier's lookup leaves for the connection where the database
    # refuses it, as a managed service may.
    await db.execute(text("SELECT set_config('agenticos.memory_cluster', '-', false)"))
    user, org, agent, run = await _world(db)
    await db.refresh(run)
    assert run.memory_snapshot is None
    assert await audit_log_repo.current_snapshot(db) is None

    await _forget(db, user, org)

    entry = await db.scalar(
        select(AppAdminAuditLog.details).where(
            AppAdminAuditLog.action == "memory.person.forgotten",
            AppAdminAuditLog.target_id == str(user.id),
        )
    )
    assert entry is not None and audit_log_repo.ERASURE_TRANSACTION not in entry
    said = await MemoryToolset().remember(_ctx(user, org, agent, run), "Prefers short answers")
    assert "erased after this conversation began" in said


async def test_a_database_that_refuses_the_cluster_identifier_still_admits_runs(
    db: AsyncSession,
) -> None:
    from sqlalchemy import text

    from app.repositories import audit_log_repo

    user, org, agent, _ = await _world(db)
    # PL/pgSQL keeps an expression it has already run for the rest of the transaction,
    # permission checked, so the refusal has to meet its first call in a new one.
    await db.commit()
    # A role that may not read the control data, as on a managed service; all of
    # it is rolled back with the test's transaction.
    role = f"no_control_{uuid.uuid4().hex[:8]}"
    await db.execute(text("REVOKE EXECUTE ON FUNCTION pg_control_system() FROM PUBLIC"))
    await db.execute(text(f"CREATE ROLE {role}"))
    await db.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}"))
    # Forgets what this connection looked up, so the next call asks again.
    await db.execute(text("SELECT set_config('agenticos.memory_cluster', '', false)"))
    await db.execute(text(f"SET LOCAL ROLE {role}"))

    assert await audit_log_repo.current_snapshot(db) is None
    looked_up = await db.scalar(text("SELECT current_setting('agenticos.memory_cluster')"))
    assert looked_up == "-"
    run = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        started_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    assert run.memory_snapshot is None

    await db.execute(text("RESET ROLE"))
    await _forget(db, user, org)
    said = await MemoryToolset().remember(_ctx(user, org, agent, run), "Prefers short answers")
    assert "erased after this conversation began" in said


async def test_a_lookup_rolled_back_is_asked_again_on_the_same_connection(
    engine: AsyncEngine,
) -> None:
    from sqlalchemy import text

    snapshot = text("SELECT agenticos_memory_snapshot()")
    setting = text("SELECT current_setting('agenticos.memory_cluster', true)")
    async with engine.connect() as connection:
        # The connection as one that has not looked the cluster up yet.
        await connection.execute(text("SELECT set_config('agenticos.memory_cluster', '', false)"))
        await connection.commit()

        assert await connection.scalar(snapshot) is not None
        await connection.rollback()
        # The rollback takes the cached cluster with it and leaves '' - not a refusal.
        assert await connection.scalar(setting) == ""
        await connection.rollback()

        assert await connection.scalar(snapshot) is not None
