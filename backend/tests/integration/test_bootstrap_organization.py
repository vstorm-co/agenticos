"""Which organization `agenticos cmd bootstrap --org <name>` leaves the owner in."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands.bootstrap import _resolve_organization
from app.db.models.organization import Organization, OrganizationMember
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
    again = await _resolve_organization(db, owner, "Northwind Labs", new_owner=False)
    assert again.id == org.id
