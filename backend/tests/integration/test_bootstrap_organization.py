"""Which organization `agenticos cmd bootstrap --org <name>` leaves the owner in."""

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands.bootstrap import _resolve_organization
from app.db.models.agent import Agent
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.skill import Skill
from app.db.models.user import User
from app.schemas.user import UserCreate
from app.services.organization import OrganizationService
from app.services.user import UserService

pytestmark = pytest.mark.anyio


async def _register(db: AsyncSession) -> uuid.UUID:
    user = await UserService(db).register(
        UserCreate(email=f"{uuid.uuid4().hex[:12]}@example.com", password="Secret-pass-1")
    )
    return user.id


async def _organizations(db: AsyncSession, user_id: uuid.UUID) -> list[Organization]:
    rows = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.created_at)
    )
    return list(rows.scalars())


async def _seeded(db: AsyncSession, org: Organization) -> tuple[int, int]:
    """How many system agents and bundled skills the organization was given."""
    system = await db.scalar(
        select(func.count())
        .select_from(Agent)
        .where(Agent.organization_id == org.id, Agent.kind != "agent")
    )
    skills = await db.scalar(
        select(func.count()).select_from(Skill).where(Skill.organization_id == org.id)
    )
    return int(system or 0), int(skills or 0)


async def test_a_fresh_owner_lands_in_the_organization_it_names(db: AsyncSession) -> None:
    owner = await _register(db)

    org = await _resolve_organization(db, owner, "Northwind Labs", new_owner=True)

    assert (org.name, org.slug, org.is_personal) == ("Northwind Labs", "northwind-labs", False)
    assert [o.id for o in await _organizations(db, owner)] == [org.id]
    assert (await OrganizationService(db).fallback_for(owner)).id == org.id


async def test_a_second_run_reuses_the_named_organization(db: AsyncSession) -> None:
    owner = await _register(db)
    first = await _resolve_organization(db, owner, "Northwind Labs", new_owner=True)

    again = await _resolve_organization(db, owner, "Northwind Labs", new_owner=False)

    assert again.id == first.id
    assert len(await _organizations(db, owner)) == 1


async def test_an_existing_owners_personal_organization_is_left_alone(db: AsyncSession) -> None:
    owner = await _register(db)
    (personal,) = await _organizations(db, owner)

    org = await _resolve_organization(db, owner, "Northwind Labs", new_owner=False)

    await db.refresh(personal)
    assert (personal.name, personal.is_personal) == ("Personal", True)
    assert org.id != personal.id
    assert (org.name, org.is_personal) == ("Northwind Labs", False)
    # Made the way the console makes one, so it opens with what sign-up gave Personal.
    assert await _seeded(db, org) == await _seeded(db, personal)
    assert all(await _seeded(db, org))
    again = await _resolve_organization(db, owner, "Northwind Labs", new_owner=False)
    assert again.id == org.id


async def test_a_taken_slug_gets_a_free_one_rather_than_failing(db: AsyncSession) -> None:
    first = await _register(db)
    taken = await _resolve_organization(db, first, "Northwind Labs", new_owner=True)
    second = await _register(db)

    org = await _resolve_organization(db, second, "Northwind Labs", new_owner=False)

    assert org.id != taken.id
    assert org.name == "Northwind Labs"
    assert org.slug != taken.slug and org.slug.startswith("northwind-labs")


async def test_without_a_name_a_fresh_owner_stays_in_its_personal_organization(
    db: AsyncSession,
) -> None:
    """What `make platform-bootstrap` and the e2e seed rely on: nothing renamed, nothing extra."""
    owner = await _register(db)

    org = await _resolve_organization(db, owner, None, new_owner=True)

    assert (org.name, org.is_personal) == ("Personal", True)
    assert [o.id for o in await _organizations(db, owner)] == [org.id]


async def test_a_named_organization_wins_over_one_the_owner_already_runs(db: AsyncSession) -> None:
    owner = await _register(db)
    landing = await _resolve_organization(db, owner, None, new_owner=True)

    org = await _resolve_organization(db, owner, "Northwind Labs", new_owner=False)

    assert org.id != landing.id
    assert (org.name, org.is_personal) == ("Northwind Labs", False)


@pytest.mark.parametrize("name", ["", " ", "A"])
@pytest.mark.parametrize("new_owner", [False, True])
async def test_an_invalid_explicit_name_does_not_change_the_personal_organization(
    db: AsyncSession, name: str, new_owner: bool
) -> None:
    owner = await _register(db)
    (personal,) = await _organizations(db, owner)
    original = (personal.name, personal.slug, personal.is_personal)
    with pytest.raises(ValidationError):
        await _resolve_organization(db, owner, name, new_owner=new_owner)
    await db.refresh(personal)
    assert (personal.name, personal.slug, personal.is_personal) == original
    assert [org.id for org in await _organizations(db, owner)] == [personal.id]


async def test_a_new_owner_without_a_personal_organization_gets_the_named_one(
    db: AsyncSession,
) -> None:
    owner = User(email=f"{uuid.uuid4().hex[:12]}@example.com", is_active=True)
    db.add(owner)
    await db.flush()

    org = await _resolve_organization(db, owner.id, "Northwind Labs", new_owner=True)

    assert (org.name, org.is_personal) == ("Northwind Labs", False)
    assert [owned.id for owned in await _organizations(db, owner.id)] == [org.id]
    membership = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == owner.id,
        )
    )
    assert membership is not None and membership.role == "owner"
    assert all(await _seeded(db, org))


@pytest.mark.security
async def test_an_organization_handed_over_under_that_name_is_not_reused(db: AsyncSession) -> None:
    """A name and an ownership can both be given to the account by somebody else."""
    owner = await _register(db)
    other = await _register(db)
    theirs = await _resolve_organization(db, other, "Northwind Labs", new_owner=True)
    db.add(OrganizationMember(organization_id=theirs.id, user_id=owner, role="owner"))
    await db.flush()

    org = await _resolve_organization(db, owner, "Northwind Labs", new_owner=False)

    assert org.id != theirs.id
    assert org.created_by_user_id == owner
