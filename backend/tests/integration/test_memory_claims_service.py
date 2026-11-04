"""The person's own view of the ledger, through the service, against Postgres (#2090)."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import NotFoundError
from app.core.memory_keys import person_owner_key
from app.core.permissions import AuthContext, OrgRoleName
from app.db.locks import LockScope, hold_subject
from app.db.models.agent import Agent
from app.db.models.memory_claim import MemoryClaim
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import memory_claim as claim_repo
from app.repositories.memory_claim import ClaimScope
from app.schemas.memory import MemoryClaimCorrect
from app.services.memory import MemoryService, claims, facade

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_erasure_waits_for_an_admitted_writer_and_removes_its_claim(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, agent, ctx, _ = await _setup(db)
    await db.commit()
    locked, erasing = asyncio.Event(), asyncio.Event()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def erasure_lock(session: AsyncSession, scope: LockScope, subject: uuid.UUID) -> None:
        erasing.set()
        await hold_subject(session, scope, subject)

    monkeypatch.setattr(facade, "hold_subject", erasure_lock)

    async def writer() -> None:
        async with sessions() as session:
            await hold_subject(session, LockScope.PERSONAL_DATA_PER_USER, user.id)
            locked.set()
            await erasing.wait()
            await claims.remember(
                session,
                organization_id=org.id,
                scope=ClaimScope(person_owner_key(user.id), agent.id),
                statement="Prefers tea",
            )
            await session.commit()

    async def erase() -> None:
        await locked.wait()
        async with sessions() as session:
            result = await MemoryService(session).forget_person(ctx, user.id)
            await session.commit()
            assert result.claims_deleted == 1

    async with asyncio.timeout(10), asyncio.TaskGroup() as tasks:
        tasks.create_task(writer())
        tasks.create_task(erase())
    assert await db.scalar(select(func.count()).select_from(MemoryClaim)) == 0


async def _setup(db: AsyncSession):
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    other = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Bo")
    db.add_all([user, other])
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(
        organization_id=org.id,
        name="Finance",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.VIEWER)
    stranger = AuthContext(user_id=other.id, organization_id=org.id, role=OrgRoleName.VIEWER)
    return user, org, agent, ctx, stranger


async def _say(db, org, key, agent, statement, subject):
    return (
        await claims.remember(
            db,
            organization_id=org.id,
            scope=ClaimScope(key, agent.id if agent else None),
            statement=statement,
            subject=subject,
        )
    ).claim


async def test_a_person_lists_only_their_own_claims_and_asks_for_history(db: AsyncSession) -> None:
    user, org, agent, ctx, stranger = await _setup(db)
    key = person_owner_key(user.id)
    old = await _say(db, org, key, agent, "Anna handles invoices", "owner")
    await claims.correct(db, claim=old, statement="Piotr handles invoices", author_user_id=user.id)
    await _say(db, org, key, None, "Prefers short answers", "style")
    service = MemoryService(db)

    now = await service.my_claims(ctx, skip=0, limit=50, history=False)
    everything = await service.my_claims(ctx, skip=0, limit=50, history=True)
    theirs = await service.my_claims(stranger, skip=0, limit=50, history=True)

    assert {item.statement for item in now.items} == {
        "Piotr handles invoices",
        "Prefers short answers",
    }
    assert everything.total == 3 and {item.status for item in everything.items} >= {"superseded"}
    profile = next(item for item in now.items if item.statement == "Prefers short answers")
    related = next(item for item in now.items if item.statement == "Piotr handles invoices")
    assert profile.scope == "profile" and profile.agent_name is None
    assert related.scope == "agent" and related.agent_name == "Finance"
    assert theirs.total == 0


async def test_a_claim_detail_shows_what_it_replaced_and_hides_what_is_not_theirs(
    db: AsyncSession,
) -> None:
    user, org, agent, ctx, stranger = await _setup(db)
    key = person_owner_key(user.id)
    old = await _say(db, org, key, agent, "Anna handles invoices", "owner")
    new = await claims.correct(
        db, claim=old, statement="Piotr handles invoices", author_user_id=user.id
    )
    foreign = await claim_repo.create(
        db,
        organization_id=org.id,
        scope_key="org:elsewhere",
        agent_id=None,
        subject="x",
        statement="Restricted",
        kind="fact",
        origin="agent",
        status="current",
        observed_at=datetime.now(UTC),
    )
    derived = await claim_repo.create(
        db,
        organization_id=org.id,
        scope_key=key,
        agent_id=None,
        subject="mix",
        statement="Mixed",
        kind="fact",
        origin="consolidation",
        status="current",
        observed_at=datetime.now(UTC),
        derived_from=[str(foreign.id), str(new.id)],
        consolidation_key="a" * 64,
    )
    service = MemoryService(db)

    corrected = await service.claim_detail(ctx, new.id)
    mixed = await service.claim_detail(ctx, derived.id)

    assert corrected.superseded is not None and corrected.superseded.id == old.id
    assert [item.id for item in mixed.sources] == [new.id] and mixed.withheld == 1
    with pytest.raises(NotFoundError):
        await service.claim_detail(stranger, new.id)


async def test_a_person_corrects_and_retracts_through_the_service_and_it_is_audited(
    db: AsyncSession,
) -> None:
    user, org, agent, ctx, stranger = await _setup(db)
    key = person_owner_key(user.id)
    claim = await _say(db, org, key, agent, "Anna handles invoices", "owner")
    service = MemoryService(db)

    fixed = await service.correct_claim(
        ctx, claim.id, MemoryClaimCorrect(statement="Piotr handles invoices")
    )
    gone = await service.retract_claim(ctx, fixed.id)

    assert fixed.origin == "person" and fixed.agent_name == "Finance"
    assert gone.status == "retracted"
    with pytest.raises(NotFoundError):
        await service.correct_claim(stranger, claim.id, MemoryClaimCorrect(statement="x"))
    with pytest.raises(NotFoundError):
        await service.retract_claim(stranger, claim.id)


async def test_the_history_is_read_only(db: AsyncSession) -> None:
    from app.core.exceptions import ConflictError

    user, org, agent, ctx, stranger = await _setup(db)
    key = person_owner_key(user.id)
    old = await _say(db, org, key, agent, "Anna handles invoices", "owner")
    await claims.correct(db, claim=old, statement="Piotr handles invoices", author_user_id=user.id)
    service = MemoryService(db)

    with pytest.raises(ConflictError, match="history"):
        await service.retract_claim(ctx, old.id)
    with pytest.raises(ConflictError):
        await service.correct_claim(ctx, old.id, MemoryClaimCorrect(statement="Marta"))
    live = await service.my_claims(ctx, skip=0, limit=10, history=False)
    assert [item.statement for item in live.items] == ["Piotr handles invoices"]


async def test_current_inventory_excludes_ended_and_not_yet_effective_claims(
    db: AsyncSession,
) -> None:
    from datetime import timedelta

    from app.core.exceptions import ConflictError

    user, org, agent, ctx, _ = await _setup(db)
    key = person_owner_key(user.id)
    ended = await _say(db, org, key, agent, "Anna handles invoices", "owner")
    ended.effective_to = datetime.now(UTC) - timedelta(days=1)
    future = await _say(db, org, key, agent, "Piotr handles invoices", "next_owner")
    future.effective_from = datetime.now(UTC) + timedelta(days=1)
    current = await _say(db, org, key, agent, "Prefers short answers", "style")
    await db.flush()
    service = MemoryService(db)
    active = await service.my_claims(ctx, skip=0, limit=50, history=False)
    history = await service.my_claims(ctx, skip=0, limit=50, history=True)
    assert active.total == 1 and active.items[0].id == current.id
    assert history.total == 3
    with pytest.raises(ConflictError):
        await service.correct_claim(
            ctx, ended.id, MemoryClaimCorrect(statement="An obsolete correction")
        )
    with pytest.raises(ConflictError):
        await service.retract_claim(ctx, ended.id)


async def test_browser_filters_before_paging_and_preserves_person_and_tenant_scope(
    db: AsyncSession,
) -> None:
    user, org, agent, ctx, stranger = await _setup(db)
    key = person_owner_key(user.id)
    for index in range(3):
        await _say(db, org, key, agent, f"LATARNIA invoice {index}", f"invoice-{index}")
    await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(key, None),
        statement="LATARNIA reports first",
        subject="report-style",
        kind="preference",
    )
    await _say(db, org, person_owner_key(stranger.subject_id), agent, "LATARNIA private", "private")
    _, other_org, other_agent, _, _ = await _setup(db)
    await _say(db, other_org, key, other_agent, "LATARNIA another tenant", "another")
    service = MemoryService(db)
    result = await service.my_claims(
        ctx, skip=1, limit=1, history=False, q="LATARNIA", kind="fact", scope="agent"
    )
    assert result.total == 3 and len(result.items) == 1
    profile = await service.my_claims(
        ctx, skip=0, limit=10, history=False, q="LATARNIA", scope="profile"
    )
    assert profile.total == 1 and profile.items[0].kind == "preference"
    named = await service.my_claims(ctx, skip=0, limit=10, history=False, q="Finance")
    assert named.total == 3
    await _say(db, org, key, agent, "Discount 50%", "percent")
    literal = await service.my_claims(ctx, skip=0, limit=10, history=False, q="50%")
    assert literal.total == 1 and literal.items[0].statement == "Discount 50%"


async def test_note_browser_searches_all_pages_without_exposing_other_stores(
    db: AsyncSession,
) -> None:
    user, org, agent, ctx, stranger = await _setup(db)
    from app.repositories import memory_repo

    for owner in [user.id, stranger.subject_id]:
        for index in range(3):
            await memory_repo.create(
                db,
                organization_id=org.id,
                agent_id=agent.id,
                owner_key=person_owner_key(owner),
                name=f"checklist-{index}.md",
                description="LATARNIA checklist",
                content="A 50% test",
                content_format="md",
                kind="note",
            )
    service = MemoryService(db)
    page = await service.mine(ctx, skip=1, limit=1, q="checklist")
    assert page.total == 3 and len(page.items) == 1
    assert (await service.mine(ctx, skip=0, limit=10, q="Finance")).total == 3
    assert (await service.mine(ctx, skip=0, limit=10, q="50%")).total == 3
    assert (await service.mine(ctx, skip=0, limit=10, q="missing")).total == 0
