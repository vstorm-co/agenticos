"""What a parked table call is called on its approval card, against real tables (#1974).

The describers answer a call's ids as names, and they answer as the run's
person: a table that person may not see comes back as no context, never as its
name. Proved here against the real access checks, because a mocked
service would prove only that the mock was asked.
"""

import uuid
from dataclasses import dataclass, replace

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.approval import ApprovalGate
from app.agents.capabilities.virtual_tables import VirtualTables
from app.agents.capabilities.virtual_tables._access import TableOperation
from app.agents.capabilities.virtual_tables._describe import describe_record_write
from app.agents.deps import AgentDeps
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.virtual_table import RecordCreate, TableCreate, TableRead
from app.services.virtual_tables.facade import VirtualTableService
from tests.integration.virtual_table_support import (
    cid,
    column,
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


def _agent_deps(world: _World) -> AgentDeps:
    return AgentDeps(
        organization_id=world.org.id,
        user_id=None,
        agent_id=uuid.uuid4(),
        acts_as_agent=True,
        run_id=uuid.uuid4(),
    )


@pytest.mark.security
async def test_an_agent_runs_table_write_is_described_by_name(world: _World):
    describers = VirtualTables(
        grants={world.orders.id: frozenset({TableOperation.CREATE})}
    ).describers()

    context = await describers["create_record"](
        _agent_deps(world), {"table_id": world.orders.id, "values": {"Customer": "Ada"}}
    )

    assert context == {"table": "Orders"}


@pytest.mark.security
async def test_an_ungranted_table_is_not_named(world: _World):
    """An org-visible table the spec does not grant: any member may see it, the agent's
    card must still not name it."""
    async with world.factory() as db:
        invoices = await VirtualTableService(db).create_table(
            ctx_for(world.owner, world.org),
            TableCreate(name="Invoices", visibility="org", columns=[column("Customer", "text")]),
        )
        await db.commit()
    describers = VirtualTables(
        grants={world.orders.id: frozenset({TableOperation.CREATE})}
    ).describers()

    named = await describers["update_record"](_agent_deps(world), {"table_id": invoices.id})
    as_member = await describers["update_record"](
        _deps(world, world.owner), {"table_id": invoices.id}
    )

    assert named is None
    assert as_member is None


@pytest.mark.security
async def test_a_run_with_no_agent_names_nothing(world: _World):
    describers = VirtualTables(
        grants={world.orders.id: frozenset({TableOperation.UPDATE})}
    ).describers()
    deps = replace(_agent_deps(world), agent_id=None)

    assert await describers["delete_record"](deps, {"table_id": world.orders.id}) is None


@pytest.mark.security
async def test_a_members_run_names_a_granted_table_as_that_member(world: _World):
    describers = VirtualTables(
        grants={world.orders.id: frozenset({TableOperation.UPDATE})}
    ).describers()

    named = await describers["update_record"](
        _deps(world, world.owner), {"table_id": world.orders.id}
    )
    unseen = await describers["update_record"](
        _deps(world, await _member(world, "member")), {"table_id": world.orders.id}
    )

    assert named == {"table": "Orders"}
    assert unseen is None


@pytest.mark.security
async def test_a_granted_table_that_is_gone_is_not_named(world: _World):
    gone = uuid.uuid4()
    describers = VirtualTables(grants={gone: frozenset({TableOperation.UPDATE})}).describers()

    assert await describers["update_record"](_agent_deps(world), {"table_id": gone}) is None


def _gate_describers(world: _World, grants: dict[uuid.UUID, list[str]]):
    """The describers the factory installs on a gate for a spec that renames `update_record`."""
    spec = AgentSpec(
        name="Clerk",
        capabilities=[
            {
                "id": "virtual_tables",
                "config": {
                    "tables": [
                        {"table_id": str(table_id), "operations": operations}
                        for table_id, operations in grants.items()
                    ]
                },
                "tool_overrides": {"update_record": {"name": "change_record"}},
            }
        ],
    )
    built = build_agent(
        spec,
        ModelRequestSpec(
            profile_id=uuid.uuid4(),
            label="GPT-4.1",
            provider="openai",
            model="gpt-4.1",
            params={},
            credential=ResolvedCredential(
                provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
            ),
            fallbacks=[],
        ),
        organization_id=world.org.id,
    )
    attached: list[object] = []
    built.agent.root_capability.apply(attached.append)
    return next(one for one in attached if isinstance(one, ApprovalGate)).describers


@pytest.mark.security
async def test_a_renamed_tools_card_names_only_a_granted_table_in_a_member_run(world: _World):
    async with world.factory() as db:
        invoices = await VirtualTableService(db).create_table(
            ctx_for(world.owner, world.org),
            TableCreate(name="Invoices", visibility="org", columns=[column("Customer", "text")]),
        )
        await db.commit()
    describers = _gate_describers(world, {world.orders.id: ["update"]})

    granted = await describers["change_record"](
        _deps(world, world.owner), {"table_id": world.orders.id}
    )
    ungranted = await describers["change_record"](
        _deps(world, world.owner), {"table_id": invoices.id}
    )

    assert granted == {"table": "Orders"}
    assert ungranted is None


@pytest.mark.security
async def test_a_renamed_tools_card_names_the_granted_table_in_an_agent_run(world: _World):
    describers = _gate_describers(world, {world.orders.id: ["update"]})

    named = await describers["change_record"](_agent_deps(world), {"table_id": world.orders.id})

    assert named == {"table": "Orders"}
