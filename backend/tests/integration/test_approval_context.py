"""What a parked table call is called on its approval card, against real tables (#1974).

The describers answer a call's ids as names, and they answer as the run's
person: a table that person may not see comes back as no context, never as its
name. Proved here against the real access checks, because a mocked
service would prove only that the mock was asked.
"""

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.virtual_tables._describe import describe_record_write
from app.agents.deps import AgentDeps
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.virtual_table import RecordCreate, TableRead
from app.services.virtual_tables.facade import VirtualTableService
from tests.integration.virtual_table_support import (
    cid,
    ctx_for,
    make_org,
    make_user,
    orders_table,
)

# What an approver is shown, and whether a held call is described: approval-gate behaviour.
pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class _World:
    factory: async_sessionmaker[AsyncSession]
    owner: User
    org: Organization
    orders: TableRead


@pytest.fixture
async def world(engine: AsyncEngine) -> _World:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner = await make_user(db)
        org = await make_org(db, owner=owner)
        orders = await orders_table(VirtualTableService(db), ctx_for(owner, org))
        await db.commit()
    return _World(factory=factory, owner=owner, org=org, orders=orders)


def _deps(world: _World, person: User | None) -> AgentDeps:
    return AgentDeps(
        organization_id=world.org.id,
        user_id=str(world.owner.id),
        run_id=uuid.uuid4(),
        run_person=None if person is None else person.id,
    )


async def _member(world: _World, role: str) -> User:
    async with world.factory() as db:
        user = await make_user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=world.org.id, user_id=user.id, role=role
            )
        )
        await db.commit()
    return user


async def _record(world: _World, values: dict[str, str], external_id: str | None = None):
    async with world.factory() as db:
        written = await VirtualTableService(db).create_record(
            ctx_for(world.owner, world.org),
            world.orders.id,
            RecordCreate(external_id=external_id, values=values),
        )
        await db.commit()
    return written.record


@pytest.mark.security
async def test_a_run_acting_for_nobody_names_nothing(world: _World):
    assert await describe_record_write(_deps(world, None), {"table_id": world.orders.id}) is None


@pytest.mark.security
async def test_a_table_the_person_may_not_see_is_not_named(world: _World):
    """A private table is a 404 to a member without a grant, and so is its name here."""
    member = await _member(world, "member")

    context = await describe_record_write(
        _deps(world, member), {"table_id": world.orders.id, "values": {"Customer": "Ada"}}
    )

    assert context is None


@pytest.mark.security
async def test_a_record_write_names_its_table_and_nothing_of_the_record(world: _World):
    """The context outlives the record and reaches approvers who may not read the
    table, so a cell's text - often a person's name - is never copied into it."""
    stored = await _record(world, {cid(world.orders, "Customer"): "Grace"}, external_id="B-7")
    deps = _deps(world, world.owner)

    new = await describe_record_write(
        deps,
        {
            "table_id": world.orders.id,
            "external_id": "A-1",
            "values": {"Customer": "Ada Lovelace", "Quantity": 2},
        },
    )
    by_id = await describe_record_write(
        deps, {"table_id": world.orders.id, "record_id": stored.id, "expected_revision": 1}
    )

    assert new == by_id == {"table": "Orders"}
