"""The table tools an agent calls, against a real table service and Postgres (#1784).

What is proved is the boundary an agent cannot cross: a table it is not granted,
an operation its grant leaves out, a member who is no longer one, and a table it
may only create with the switch on and the permission held - plus that a
retried call replays its first write rather than making a second one.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.virtual_tables import VirtualTables
from app.agents.capabilities.virtual_tables._access import TableOperation
from app.agents.deps import AgentDeps
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTableRecord
from app.schemas.virtual_table import RecordFilter, TableRead
from app.services.virtual_tables.facade import VirtualTableService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user, orders_table

pytestmark = pytest.mark.anyio


@dataclass
class _World:
    factory: async_sessionmaker[AsyncSession]
    owner: User
    org: Organization
    orders: TableRead
    other: TableRead

    def deps(self, user: User | None = None) -> AgentDeps:
        return AgentDeps(
            organization_id=self.org.id, user_id=str((user or self.owner).id), run_id=uuid.uuid4()
        )


@pytest.fixture
async def world(engine: AsyncEngine) -> _World:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner = await make_user(db)
        org = await make_org(db, owner=owner)
        service = VirtualTableService(db)
        orders = await orders_table(service, ctx_for(owner, org))
        other = await orders_table(service, ctx_for(owner, org), name="Invoices")
        await db.commit()
    return _World(factory=factory, owner=owner, org=org, orders=orders, other=other)


def _ctx(deps: AgentDeps, *, call: str = "call-1", retry: int = 0) -> RunContext[AgentDeps]:
    return RunContext(
        deps=deps,
        model=TestModel(),
        usage=RunUsage(),
        retry=retry,
        max_retries=1,
        tool_call_id=call,
    )


def _tools(grants: dict[uuid.UUID, set[TableOperation]], *, allow_create: bool = False):
    capability: VirtualTables[AgentDeps] = VirtualTables(
        grants={table_id: frozenset(ops) for table_id, ops in grants.items()},
        allow_create=allow_create,
    )
    toolset = capability.get_toolset()

    async def call(tool: str, ctx: RunContext[AgentDeps], **arguments: Any) -> str:
        return await toolset.tools[tool].function(ctx, **arguments)

    return call, capability, toolset


ALL = {TableOperation.READ, TableOperation.CREATE, TableOperation.UPDATE, TableOperation.DELETE}


async def _count(world: _World) -> int:
    async with world.factory() as db:
        return int(await db.scalar(select(func.count()).select_from(VirtualTableRecord)) or 0)


async def test_an_agent_sees_only_the_tables_it_is_granted(world: _World):
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.READ}})

    listed = json.loads(await call("list_tables", _ctx(world.deps())))

    assert [(t["name"], t["operations"]) for t in listed] == [("Orders", ["read"])]


@pytest.mark.security
async def test_a_table_it_is_not_granted_is_refused_before_anything_is_read(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})

    answer = await call("describe_table", _ctx(world.deps()), table_id=world.other.id)

    assert "no access to table" in answer


@pytest.mark.security
async def test_a_read_only_grant_refuses_a_write_and_writes_nothing(world: _World):
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.READ}})

    answer = await call(
        "create_record", _ctx(world.deps()), table_id=world.orders.id, values={"Customer": "Ada"}
    )

    assert "may not create" in answer
    assert await _count(world) == 0


@pytest.mark.security
async def test_an_upsert_needs_create_as_well_as_update(world: _World):
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.READ, TableOperation.UPDATE}})

    answer = await call(
        "upsert_record",
        _ctx(world.deps()),
        table_id=world.orders.id,
        external_id="A-1",
        values={"Customer": "Ada"},
    )

    assert "may not create" in answer
    assert await _count(world) == 0


async def test_values_are_written_by_label_and_read_back_by_label(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = world.deps()

    created = json.loads(
        await call(
            "create_record",
            _ctx(deps),
            table_id=world.orders.id,
            values={"customer": "Ada", "Quantity": 3},
            external_id="A-1",
        )
    )
    read = json.loads(
        await call("get_record", _ctx(deps, call="c2"), table_id=world.orders.id, external_id="A-1")
    )

    assert created["revision"] == 1 and read["values"]["Customer"] == "Ada"
    assert read["values"]["Quantity"] == 3
    assert (
        await call(
            "record_exists", _ctx(deps, call="c3"), table_id=world.orders.id, external_id="A-1"
        )
        == "true"
    )


async def test_a_retried_call_replays_its_write_and_a_new_call_does_not(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = world.deps()
    arguments = {"table_id": world.orders.id, "values": {"Customer": "Ada"}}

    first = json.loads(await call("create_record", _ctx(deps, call="same"), **arguments))
    again = json.loads(await call("create_record", _ctx(deps, call="same"), **arguments))
    other = json.loads(await call("create_record", _ctx(deps, call="different"), **arguments))

    assert first["id"] == again["id"] != other["id"]
    assert await _count(world) == 2


async def test_a_stale_revision_is_refused_with_how_to_recover(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = world.deps()
    record = json.loads(
        await call("create_record", _ctx(deps), table_id=world.orders.id, values={"Quantity": 1})
    )

    stale = await call(
        "update_record",
        _ctx(deps, call="c2"),
        table_id=world.orders.id,
        record_id=uuid.UUID(record["id"]),
        expected_revision=7,
        values={"Quantity": 2},
    )
    fresh = json.loads(
        await call(
            "update_record",
            _ctx(deps, call="c3"),
            table_id=world.orders.id,
            record_id=uuid.UUID(record["id"]),
            expected_revision=1,
            values={"Quantity": 2},
        )
    )

    assert "REVISION_CONFLICT" in stale and "Read the record again" in stale
    assert fresh["revision"] == 2 and fresh["values"]["Quantity"] == 2


async def test_a_column_that_does_not_exist_is_steered_then_answered(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = world.deps()
    arguments = {"table_id": world.orders.id, "values": {"Colour": "red"}}

    with pytest.raises(ModelRetry, match="not a column of Orders"):
        await call("create_record", _ctx(deps), **arguments)
    last = await call("create_record", _ctx(deps, retry=1), **arguments)

    assert "not a column of Orders" in last
    assert await _count(world) == 0


async def test_a_value_of_the_wrong_type_is_steered(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})

    with pytest.raises(ModelRetry, match="INVALID_RECORD"):
        await call(
            "create_record",
            _ctx(world.deps()),
            table_id=world.orders.id,
            values={"Quantity": "three"},
        )


async def test_records_are_listed_filtered_sorted_and_paged(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = world.deps()
    for index, quantity in enumerate([5, 1, 9]):
        await call(
            "create_record",
            _ctx(deps, call=f"make-{index}"),
            table_id=world.orders.id,
            values={"Quantity": quantity},
        )
    quantity_id = next(str(c.id) for c in world.orders.columns if c.label == "Quantity")

    page = json.loads(
        await call(
            "list_records",
            _ctx(deps, call="list"),
            table_id=world.orders.id,
            filters=[RecordFilter(column_id=quantity_id, op="gte", value=2)],
            sort_by=quantity_id,
            descending=True,
            limit=1,
        )
    )

    assert [r["values"]["Quantity"] for r in page["records"]] == [9]
    assert page["has_more"] is True


async def test_a_record_is_deleted_at_the_revision_read(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = world.deps()
    record = json.loads(
        await call("create_record", _ctx(deps), table_id=world.orders.id, values={"Quantity": 1})
    )

    answer = await call(
        "delete_record",
        _ctx(deps, call="del"),
        table_id=world.orders.id,
        record_id=uuid.UUID(record["id"]),
        expected_revision=1,
    )

    assert answer == f"Deleted record {record['id']}."
    assert await _count(world) == 0


async def test_a_table_that_was_archived_no_longer_exists_for_the_agent(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    async with world.factory() as db:
        await VirtualTableService(db).archive_table(
            ctx_for(world.owner, world.org), world.orders.id
        )
        await db.commit()

    assert await call("table_exists", _ctx(world.deps()), table_id=world.orders.id) == "false"
    assert json.loads(await call("list_tables", _ctx(world.deps(), call="l"))) == []


@pytest.mark.security
async def test_a_member_who_left_mid_run_cannot_make_the_next_call(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = world.deps()
    async with world.factory() as db:
        await db.execute(
            delete(OrganizationMember).where(OrganizationMember.user_id == world.owner.id)
        )
        await db.commit()

    answer = await call("describe_table", _ctx(deps), table_id=world.orders.id)

    assert "no longer in the organization" in answer


@pytest.mark.security
async def test_a_run_with_no_member_behind_it_cannot_use_tables(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})

    answer = await call(
        "describe_table", _ctx(AgentDeps(organization_id=world.org.id)), table_id=world.orders.id
    )

    assert "acting for a member" in answer


@pytest.mark.security
async def test_creating_a_table_is_its_own_switch_and_its_own_permission(world: _World):
    _call, _cap, without = _tools({world.orders.id: ALL})
    assert "create_table" not in without.tools

    async with world.factory() as db:
        viewer = await make_user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=world.org.id, user_id=viewer.id, role="viewer"
            )
        )
        await db.commit()
    call, _cap, _ts = _tools({}, allow_create=True)

    answer = await call(
        "create_table",
        _ctx(world.deps(viewer)),
        name="Leads",
        columns=[{"label": "Email", "type": "text"}],
    )

    assert "cannot create tables" in answer.lower()


async def test_a_table_the_agent_creates_is_usable_for_the_rest_of_the_run(world: _World):
    call, capability, _ts = _tools({}, allow_create=True)
    deps = world.deps()

    created = json.loads(
        await call(
            "create_table",
            _ctx(deps, call="make"),
            name="Leads",
            columns=[{"label": "Email", "type": "text"}],
        )
    )
    again = json.loads(
        await call(
            "create_table",
            _ctx(deps, call="make"),
            name="Leads",
            columns=[{"label": "Email", "type": "text"}],
        )
    )
    written = json.loads(
        await call(
            "create_record",
            _ctx(deps, call="row"),
            table_id=uuid.UUID(created["id"]),
            values={"Email": "ada@example.com"},
        )
    )

    assert created["id"] == again["id"]
    assert [column["label"] for column in created["columns"]] == ["Email"]
    assert written["values"]["Email"] == "ada@example.com"
    assert set(capability.grants[uuid.UUID(created["id"])]) == set(TableOperation)


async def test_a_choice_is_written_filtered_and_read_by_its_label(world: _World):
    # The schema an agent reads names a select's options by label only, so a
    # label is what it writes, filters by and must be shown back.
    call, _capability, _ts = _tools({}, allow_create=True)
    deps = world.deps()
    table = json.loads(
        await call(
            "create_table",
            _ctx(deps, call="make"),
            name="Deals",
            columns=[
                {
                    "label": "Stage",
                    "type": "single_select",
                    "options": [{"label": "Won"}, {"label": "Lost"}],
                }
            ],
        )
    )
    table_id = uuid.UUID(table["id"])
    for index, stage in enumerate(["won", "Lost"]):
        await call(
            "create_record",
            _ctx(deps, call=f"row-{index}"),
            table_id=table_id,
            values={"Stage": stage},
        )

    page = json.loads(
        await call(
            "list_records",
            _ctx(deps, call="list"),
            table_id=table_id,
            # As the model's arguments reach the tool: validated into filters.
            filters=[RecordFilter(column_id=table["columns"][0]["id"], op="eq", value="Won")],
        )
    )
    with pytest.raises(ModelRetry, match="options: Won, Lost"):
        await call(
            "create_record", _ctx(deps, call="bad"), table_id=table_id, values={"Stage": "Maybe"}
        )

    assert [record["values"]["Stage"] for record in page["records"]] == ["Won"]


async def test_a_granted_table_that_is_gone_is_neither_listed_nor_said_to_exist(world: _World):
    gone = uuid.uuid4()
    call, _cap, _ts = _tools({gone: {TableOperation.READ}, world.orders.id: {TableOperation.READ}})

    listed = json.loads(await call("list_tables", _ctx(world.deps())))
    exists = await call("table_exists", _ctx(world.deps(), call="e"), table_id=gone)

    assert [table["name"] for table in listed] == ["Orders"]
    assert exists == "false"


async def test_a_table_is_described_by_its_columns(world: _World):
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.READ}})

    described = json.loads(
        await call("describe_table", _ctx(world.deps()), table_id=world.orders.id)
    )

    assert described["name"] == "Orders"
    assert {column["label"] for column in described["columns"]} >= {"Customer", "Quantity"}


async def test_a_record_is_looked_up_by_exactly_one_key(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})

    with pytest.raises(ModelRetry, match="exactly one"):
        await call("get_record", _ctx(world.deps()), table_id=world.orders.id)


async def test_an_upsert_creates_then_updates_the_record_its_key_names(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = world.deps()
    quantity_id = next(str(c.id) for c in world.orders.columns if c.label == "Quantity")

    created = json.loads(
        await call(
            "upsert_record",
            _ctx(deps, call="u1"),
            table_id=world.orders.id,
            external_id="A-1",
            values={quantity_id: 1},
        )
    )
    updated = json.loads(
        await call(
            "upsert_record",
            _ctx(deps, call="u2"),
            table_id=world.orders.id,
            external_id="A-1",
            values={"Quantity": 5},
            expected_revision=created["revision"],
        )
    )

    assert created["created"] is True and updated["created"] is False
    assert updated["id"] == created["id"] and updated["values"]["Quantity"] == 5
    assert await _count(world) == 1
