"""A table created for a department reaches that department, and nobody else.

The create dialog chooses who a new table reaches (#2072): naming groups or
people creates it private and shares it with each, in the same request.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.group import Group, GroupMember
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import ResourceGrant
from app.db.models.user import User
from app.schemas.virtual_table import TableCreate
from app.services.virtual_tables import VirtualTableService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


async def _member(db: AsyncSession, org: Organization) -> User:
    user = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="member"))
    await db.flush()
    return user


async def _names(db: AsyncSession, ctx: AuthContext) -> list[str]:
    listed = await VirtualTableService(db).list_tables(ctx)
    return [item.name for item in listed.items]


async def test_a_table_for_a_group_is_private_and_shared_with_it(db: AsyncSession) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    accountant = await _member(db, org)
    seller = await _member(db, org)
    finance = Group(organization_id=org.id, name=f"Finance {uuid.uuid4().hex[:6]}")
    db.add(finance)
    await db.flush()
    db.add(GroupMember(group_id=finance.id, user_id=accountant.id))
    await db.flush()

    table = await VirtualTableService(db).create_table(
        ctx_for(owner, org), TableCreate(name="Invoices", visibility="org", group_ids=[finance.id])
    )

    assert table.visibility == "private"
    grants = (
        await db.scalars(select(ResourceGrant).where(ResourceGrant.resource_id == table.id))
    ).all()
    assert [(grant.subject_group_id, grant.level) for grant in grants] == [(finance.id, "read")]
    assert await _names(db, ctx_for(accountant, org, "member")) == ["Invoices"]
    assert await _names(db, ctx_for(seller, org, "member")) == []


async def test_a_table_shared_with_a_person_reaches_them(db: AsyncSession) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    colleague = await _member(db, org)

    await VirtualTableService(db).create_table(
        ctx_for(owner, org), TableCreate(name="Leads", user_ids=[colleague.id, owner.id])
    )

    assert await _names(db, ctx_for(colleague, org, "member")) == ["Leads"]


async def test_a_group_from_another_organization_is_refused(db: AsyncSession) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    other = await make_org(db, owner=await make_user(db))
    foreign = Group(organization_id=other.id, name="Elsewhere")
    db.add(foreign)
    await db.flush()

    with pytest.raises(BadRequestError) as refused:
        await VirtualTableService(db).create_table(
            ctx_for(owner, org), TableCreate(name="Leak", group_ids=[foreign.id])
        )

    assert refused.value.details["fields"][0]["field"] == "group_ids"
