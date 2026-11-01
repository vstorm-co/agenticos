"""The person's own view of the ledger, through the service, against Postgres (#2090)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.memory_keys import person_owner_key
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import memory_claim as claim_repo
from app.repositories.memory_claim import ClaimScope
from app.schemas.memory import MemoryClaimCorrect
from app.services.memory import MemoryService, claims

pytestmark = [pytest.mark.anyio, pytest.mark.security]


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
