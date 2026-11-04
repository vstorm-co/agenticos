"""The table tools an agent calls, against a real table service and Postgres (#1784).

What is proved is the boundary an agent cannot cross: a table it is not granted,
an operation its grant leaves out, a member who is no longer one, and a table it
may only create with the switch on and the permission held - plus that a
retried call replays its first write rather than making a second one.
"""

import json
import uuid
from dataclasses import dataclass, replace
from typing import Any, Literal

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.audience import acting_decider
from app.agents.capabilities.virtual_tables import VirtualTables
from app.agents.capabilities.virtual_tables._access import (
    WRITE_TOOLS,
    Mistake,
    Refused,
    TableOperation,
    run_authority,
    schema_authority,
)
from app.agents.capabilities.virtual_tables._toolset import _call_as_person
from app.agents.deps import AgentDeps
from app.core.exceptions import ValidationError
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTableRecord, VirtualTableRecordHistory
from app.repositories import resource_grant_repo
from app.schemas.table_view import TableViewConfig, TableViewCreate
from app.schemas.virtual_table import (
    ColumnInput,
    RecordCreate,
    RecordFilter,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.access import TABLE, agent_context
from app.services.virtual_tables import TableViewService
from app.services.virtual_tables.facade import VirtualTableService
from tests.integration.virtual_table_support import (
    cid,
    column,
    ctx_for,
    make_org,
    make_user,
    orders_table,
)

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


async def _make_view(
    world: _World,
    *,
    owner: User | None = None,
    name: str = "Mine",
    visibility: Literal["private", "shared"] = "private",
    config: TableViewConfig | None = None,
):
    async with world.factory() as db:
        maker = owner or world.owner
        view = await TableViewService(db).create_view(
            ctx_for(maker, world.org, "owner" if maker is world.owner else "admin"),
            world.orders.id,
            TableViewCreate(
                name=name, kind="table", visibility=visibility, config=config or TableViewConfig()
            ),
        )
        await db.commit()
    return view


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


def _person_deps(world: _World, user: User | None = None) -> AgentDeps:
    person = (user or world.owner).id
    return AgentDeps(
        organization_id=world.org.id, user_id=str(person), run_id=uuid.uuid4(), run_person=person
    )


async def test_list_views_shows_shared_and_own_private_views_marked(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    colleague = await _member(world, "admin")
    await _make_view(world, name="Mine")
    await _make_view(world, owner=colleague, name="Theirs private")
    await _make_view(world, owner=colleague, name="Theirs shared", visibility="shared")

    answer = json.loads(
        await call("list_views", _ctx(_person_deps(world)), table_id=world.orders.id)
    )

    assert answer["table"]["id"] == str(world.orders.id)
    seen = {view["name"]: view for view in answer["views"]}
    assert set(seen) == {"Mine", "Theirs shared"}
    assert (seen["Mine"]["yours"], seen["Mine"]["visibility"]) == (True, "private")
    assert (seen["Theirs shared"]["yours"], seen["Theirs shared"]["visibility"]) == (
        False,
        "shared",
    )


async def test_list_views_describes_filters_by_column_and_option_label(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    status = next(c for c in world.orders.columns if c.label == "Status")
    shipped = next(o for o in status.options if o.label == "Shipped")
    await _make_view(
        world,
        config=TableViewConfig(
            filters=[RecordFilter(column_id=status.id, op="eq", value=str(shipped.id))],
            search="acme",
        ),
    )

    answer = json.loads(
        await call("list_views", _ctx(_person_deps(world)), table_id=world.orders.id)
    )

    [view] = answer["views"]
    assert view["filters"] == [{"column": "Status", "op": "eq", "value": "Shipped"}]
    assert view["search"] == "acme"
    assert view["sort"] == {"by": "created_at", "direction": "asc"}


@pytest.mark.security
async def test_list_views_on_an_ungranted_table_is_refused_before_anything_is_read(world: _World):
    call, _cap, _ts = _tools({world.other.id: ALL})
    await _make_view(world)

    answer = await call("list_views", _ctx(_person_deps(world)), table_id=world.orders.id)

    assert "no access to table" in answer and "Mine" not in answer


async def test_list_views_on_a_table_that_does_not_exist_is_refused_in_words(world: _World):
    missing = uuid.uuid4()
    call, _cap, _ts = _tools({missing: ALL})

    answer = await call("list_views", _ctx(_person_deps(world)), table_id=missing)

    assert answer.startswith("Refused (NOT_FOUND)")


@pytest.mark.security
async def test_a_widget_run_cannot_list_views(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    await _make_view(world)

    answer = await call("list_views", _ctx(world.deps()), table_id=world.orders.id)

    assert answer == "Only a run acting for a member can use saved views."


@pytest.mark.security
async def test_a_public_webhook_run_cannot_list_views(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    await _make_view(world)
    # A step in a public workflow chain runs as the workflow's owner, with no person.
    deps = AgentDeps(
        organization_id=world.org.id,
        user_id=str(world.owner.id),
        run_id=uuid.uuid4(),
        run_person=None,
    )

    answer = await call("list_views", _ctx(deps), table_id=world.orders.id)

    assert answer == "Only a run acting for a member can use saved views."


@pytest.mark.security
async def test_a_member_who_left_mid_run_cannot_list_views(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = _person_deps(world)
    async with world.factory() as db:
        await db.execute(
            delete(OrganizationMember).where(OrganizationMember.user_id == world.owner.id)
        )
        await db.commit()

    answer = await call("list_views", _ctx(deps), table_id=world.orders.id)

    assert answer == "The member this agent acts for is no longer in the organization."


@pytest.mark.parametrize(
    "raised",
    [Mistake("Name the column by its label."), ValidationError("Name the column by its label")],
    ids=["mistake", "validation-error"],
)
async def test_a_view_tool_steers_a_call_the_model_composed_wrongly(world: _World, raised):
    # list_views raises neither today; the wrapper it shares with every view tool
    # still steers one rather than refusing it.
    async def work(*_args: object) -> str:
        raise raised

    with pytest.raises(ModelRetry, match="Name the column by its label"):
        await _call_as_person(_ctx(_person_deps(world)), work)


AGENT = uuid.uuid4()


def _agent_deps(world: _World) -> AgentDeps:
    return AgentDeps(
        organization_id=world.org.id,
        user_id=None,
        agent_id=AGENT,
        acts_as_agent=True,
        run_id=uuid.uuid4(),
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


async def _linked_to_a_private_table(world: _World) -> tuple[TableRead, str]:
    """An org-visible table whose lookup column reads a private table's name.

    The private table is the owner's alone; its one record is called Classified.
    """
    async with world.factory() as db:
        service = VirtualTableService(db)
        ctx = ctx_for(world.owner, world.org)
        private = await service.create_table(
            ctx, TableCreate(name="Private stock", columns=[column("Name", "text")])
        )
        secret = await service.create_record(
            ctx, private.id, RecordCreate(values={cid(private, "Name"): "Classified"})
        )
        mixed = await service.create_table(
            ctx,
            TableCreate(
                name="Mixed",
                visibility="org",
                columns=[column("Ref", "text"), column("Items", "link", link_table_id=private.id)],
            ),
        )
        link = uuid.UUID(cid(mixed, "Items"))
        mixed = await service.update_schema(
            ctx,
            mixed.id,
            SchemaUpdate(
                expected_version=mixed.schema_version,
                columns=[
                    *(
                        ColumnInput(
                            id=item.id,
                            label=item.label,
                            type=item.type,
                            link_table_id=item.link_table_id,
                        )
                        for item in mixed.columns
                    ),
                    column(
                        "Names",
                        "lookup",
                        link_column_id=link,
                        target_column_id=uuid.UUID(cid(private, "Name")),
                    ),
                ],
            ),
        )
        written = await service.create_record(
            ctx, mixed.id, RecordCreate(values={cid(mixed, "Items"): [str(secret.record.id)]})
        )
        await db.commit()
    return mixed, str(written.record.id)


@pytest.mark.security
async def test_an_agent_run_reads_a_granted_table_as_the_agent(world: _World):
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.READ}})
    async with world.factory() as db:
        await VirtualTableService(db).create_record(
            ctx_for(world.owner, world.org),
            world.orders.id,
            RecordCreate(values={cid(world.orders, "Customer"): "Ada"}),
        )
        await db.commit()
    deps = _agent_deps(world)

    listed = json.loads(await call("list_records", _ctx(deps), table_id=world.orders.id))
    refused = await call("list_records", _ctx(deps, call="c2"), table_id=world.other.id)

    assert [row["values"]["Customer"] for row in listed["records"]] == ["Ada"]
    assert "no access to table" in refused


@pytest.mark.security
async def test_a_table_the_grant_names_is_read_even_when_it_is_private(world: _World):
    call, _cap, _ts = _tools({world.other.id: {TableOperation.READ}})

    described = json.loads(
        await call("describe_table", _ctx(_agent_deps(world)), table_id=world.other.id)
    )

    assert described["name"] == "Invoices"


@pytest.mark.security
async def test_an_agent_run_lists_only_the_tables_it_is_granted(world: _World):
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.READ}})

    listed = json.loads(await call("list_tables", _ctx(_agent_deps(world))))

    assert [item["name"] for item in listed] == ["Orders"]


@pytest.mark.security
async def test_a_linked_table_the_spec_does_not_grant_is_hidden(world: _World):
    mixed, record_id = await _linked_to_a_private_table(world)
    call, _cap, _ts = _tools({mixed.id: {TableOperation.READ}})

    answer = await call(
        "get_record", _ctx(_agent_deps(world)), table_id=mixed.id, record_id=uuid.UUID(record_id)
    )

    assert "Classified" not in answer


@pytest.mark.security
async def test_a_read_inside_an_approved_call_still_acts_as_the_agent(world: _World):
    mixed, record_id = await _linked_to_a_private_table(world)
    decider = await _member(world, "owner")
    call, _cap, _ts = _tools({mixed.id: {TableOperation.READ}})

    with acting_decider("c1", decider.id):
        answer = await call(
            "get_record",
            _ctx(_agent_deps(world), call="c1"),
            table_id=mixed.id,
            record_id=uuid.UUID(record_id),
        )

    assert "Classified" not in answer


@pytest.mark.security
async def test_a_nested_call_gets_no_decider(world: _World):
    decider = await _member(world, "owner")
    call, _cap, _ts = _tools({world.orders.id: ALL})

    with acting_decider("c1", decider.id):
        answer = await call(
            "create_record",
            _ctx(_agent_deps(world), call="c2"),
            table_id=world.orders.id,
            values={"Customer": "Ada"},
        )

    assert answer.startswith("Refused")
    assert await _count(world) == 0


@pytest.mark.security
async def test_an_agent_run_cannot_write_without_a_decider(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})

    answer = await call(
        "create_record",
        _ctx(_agent_deps(world)),
        table_id=world.orders.id,
        values={"Customer": "Ada"},
    )

    assert answer.startswith("Refused")
    assert await _count(world) == 0


@pytest.mark.security
async def test_an_approved_write_runs_as_its_decider(world: _World):
    decider = await _member(world, "admin")
    call, _cap, _ts = _tools({world.orders.id: ALL})
    async with world.factory() as db:
        await resource_grant_repo.upsert(
            db,
            organization_id=world.org.id,
            subject_user_id=decider.id,
            resource_type=TABLE.key,
            resource_id=world.orders.id,
            level=GrantLevel.EDIT,
        )
        await db.commit()

    with acting_decider("c1", decider.id):
        answer = await call(
            "create_record",
            _ctx(_agent_deps(world), call="c1"),
            table_id=world.orders.id,
            values={"Customer": "Ada"},
        )

    created = json.loads(answer)
    async with world.factory() as db:
        record = (await db.execute(select(VirtualTableRecord))).scalar_one()
        history = (await db.execute(select(VirtualTableRecordHistory))).scalar_one()
    assert created["revision"] == 1
    assert (record.created_by, record.updated_by) == (decider.id, decider.id)
    assert record.created_source is not None
    assert (record.created_source["kind"], record.created_source["id"]) == ("agent", str(AGENT))
    assert history.actor_user_id == decider.id


@pytest.mark.security
async def test_a_decider_who_left_cannot_write(world: _World):
    decider = await _member(world, "owner")
    call, _cap, _ts = _tools({world.orders.id: ALL})
    async with world.factory() as db:
        await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == decider.id))
        await db.commit()

    with acting_decider("c1", decider.id):
        answer = await call(
            "create_record",
            _ctx(_agent_deps(world), call="c1"),
            table_id=world.orders.id,
            values={"Customer": "Ada"},
        )

    assert answer == "The person who approved this is no longer a member."
    assert await _count(world) == 0


@pytest.mark.security
async def test_a_decider_without_edit_rights_cannot_write(world: _World):
    decider = await _member(world, "viewer")
    call, _cap, _ts = _tools({world.orders.id: ALL})

    with acting_decider("c1", decider.id):
        answer = await call(
            "create_record",
            _ctx(_agent_deps(world), call="c1"),
            table_id=world.orders.id,
            values={"Customer": "Ada"},
        )

    assert answer.startswith("Refused")
    assert await _count(world) == 0


@pytest.mark.security
async def test_a_member_run_still_writes_as_its_member(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})

    with acting_decider("c1", uuid.uuid4()):
        await call(
            "create_record",
            _ctx(world.deps(), call="c1"),
            table_id=world.orders.id,
            values={"Customer": "Ada"},
        )

    async with world.factory() as db:
        record = (await db.execute(select(VirtualTableRecord))).scalar_one()
    assert record.created_by == world.owner.id


@pytest.mark.security
async def test_an_agent_run_with_no_agent_behind_it_cannot_use_tables(world: _World):
    call, _cap, _ts = _tools({world.orders.id: ALL})
    deps = replace(_agent_deps(world), agent_id=None)

    answer = await call("list_tables", _ctx(deps))

    assert answer == "Tables can only be used by a run acting for an agent of an organization."


@pytest.mark.security
async def test_a_lookup_into_a_table_granted_only_for_writing_stays_hidden(world: _World):
    """The agent holds `read` only where its spec grants it: a table it may only create in
    is not readable through another table's lookup either."""
    mixed, record_id = await _linked_to_a_private_table(world)
    private_id = next(c.link_table_id for c in mixed.columns if c.type == "link")
    call, _cap, _ts = _tools({mixed.id: {TableOperation.READ}, private_id: {TableOperation.CREATE}})

    answer = await call(
        "get_record", _ctx(_agent_deps(world)), table_id=mixed.id, record_id=uuid.UUID(record_id)
    )

    assert "Classified" not in answer


@pytest.mark.security
async def test_a_table_granted_only_for_writing_is_listed_and_described(world: _World):
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.CREATE}})
    deps = _agent_deps(world)

    listed = json.loads(await call("list_tables", _ctx(deps)))
    described = json.loads(
        await call("describe_table", _ctx(deps, call="c2"), table_id=world.orders.id)
    )

    assert [(item["id"], item["name"], item["operations"]) for item in listed] == [
        (str(world.orders.id), "Orders", ["create"])
    ]
    customer = next(c for c in described["columns"] if c["label"] == "Customer")
    status = next(c for c in described["columns"] if c["label"] == "Status")
    assert customer["type"] == "text" and customer["nullable"] is True
    assert status["options"] == ["Open", "Shipped"]


@pytest.mark.security
async def test_a_table_granted_only_for_writing_cannot_be_read(world: _World):
    mixed, record_id = await _linked_to_a_private_table(world)
    call, _cap, _ts = _tools({mixed.id: {TableOperation.CREATE}})
    deps = _agent_deps(world)

    refusals = [
        await call("list_records", _ctx(deps, call="a"), table_id=mixed.id),
        await call(
            "get_record", _ctx(deps, call="b"), table_id=mixed.id, record_id=uuid.UUID(record_id)
        ),
        await call("table_exists", _ctx(deps, call="c"), table_id=mixed.id),
        await call("record_exists", _ctx(deps, call="d"), table_id=mixed.id, external_id="x"),
    ]

    assert all("may not read" in text for text in refusals)
    assert "Classified" not in "".join(refusals)


@pytest.mark.security
async def test_an_agent_run_keeps_to_the_tables_its_spec_granted_after_creating_one(
    world: _World,
):
    decider = await _member(world, "owner")
    call, capability, _ts = _tools({world.orders.id: {TableOperation.READ}}, allow_create=True)

    with acting_decider("c1", decider.id):
        made = json.loads(
            await call(
                "create_table",
                _ctx(_agent_deps(world), call="c1"),
                name="Scratch",
                columns=[ColumnInput(label="Note", type="text")],
            )
        )

    assert "id" in made
    assert set(capability.grants) == {world.orders.id}


async def test_a_member_run_keeps_the_table_it_created(world: _World):
    call, capability, _ts = _tools({world.orders.id: {TableOperation.READ}}, allow_create=True)

    made = json.loads(
        await call(
            "create_table",
            _ctx(world.deps()),
            name="Scratch",
            columns=[ColumnInput(label="Note", type="text")],
        )
    )

    assert uuid.UUID(made["id"]) in capability.grants


@pytest.mark.security
async def test_an_approved_update_without_read_echoes_no_cells(world: _World):
    decider = await _member(world, "owner")
    async with world.factory() as db:
        stored = await VirtualTableService(db).create_record(
            ctx_for(world.owner, world.org),
            world.orders.id,
            RecordCreate(external_id="A-1", values={cid(world.orders, "Customer"): "Ada"}),
        )
        await db.commit()
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.CREATE, TableOperation.UPDATE}})

    with acting_decider("c1", decider.id):
        updated = json.loads(
            await call(
                "update_record",
                _ctx(_agent_deps(world), call="c1"),
                table_id=world.orders.id,
                record_id=stored.record.id,
                expected_revision=1,
                values={"Customer": "Grace"},
            )
        )
    with acting_decider("c2", decider.id):
        upserted = json.loads(
            await call(
                "upsert_record",
                _ctx(_agent_deps(world), call="c2"),
                table_id=world.orders.id,
                external_id="A-1",
                expected_revision=2,
                values={"Customer": "Hedy"},
            )
        )

    assert updated == {"id": str(stored.record.id), "revision": 2}
    assert upserted == {"created": False, "id": str(stored.record.id), "revision": 3}


_TOOL_ARGUMENTS: dict[str, dict[str, Any]] = {
    "list_tables": {},
    "table_exists": {"table_id": uuid.uuid4()},
    "describe_table": {"table_id": uuid.uuid4()},
    "record_exists": {"table_id": uuid.uuid4(), "external_id": "x"},
    "list_records": {"table_id": uuid.uuid4()},
    "get_record": {"table_id": uuid.uuid4(), "external_id": "x"},
    "create_record": {"table_id": uuid.uuid4(), "values": {}},
    "upsert_record": {"table_id": uuid.uuid4(), "external_id": "x", "values": {}},
    "update_record": {
        "table_id": uuid.uuid4(),
        "record_id": uuid.uuid4(),
        "expected_revision": 1,
        "values": {},
    },
    "delete_record": {"table_id": uuid.uuid4(), "record_id": uuid.uuid4(), "expected_revision": 1},
    "create_table": {"name": "T", "columns": []},
}


@pytest.mark.security
@pytest.mark.parametrize("tool", sorted(_TOOL_ARGUMENTS))
async def test_every_table_tool_asks_for_its_authority_under_its_own_name(
    world: _World, monkeypatch: pytest.MonkeyPatch, tool: str
):
    asked: list[str] = []

    async def recording(_db: Any, _ctx: Any, _grants: Any, *, tool: str) -> Any:
        asked.append(tool)
        raise Refused("stop here")

    monkeypatch.setattr("app.agents.capabilities.virtual_tables._toolset.run_authority", recording)
    call, _cap, _ts = _tools({}, allow_create=True)

    await call(tool, _ctx(_agent_deps(world)), **_TOOL_ARGUMENTS[tool])

    assert asked == [tool]


@pytest.mark.security
@pytest.mark.parametrize(
    "tool", ["create_record", "upsert_record", "update_record", "delete_record", "create_table"]
)
async def test_an_approved_write_tool_acts_as_its_decider(world: _World, tool: str):
    decider = await _member(world, "owner")
    async with world.factory() as db:
        with acting_decider("c1", decider.id):
            auth = await run_authority(
                db, _ctx(_agent_deps(world), call="c1"), {world.orders.id: ALL}, tool=tool
            )

    assert auth.user_id == decider.id
    assert auth.principal_agent_id is None
    assert tool in WRITE_TOOLS


@pytest.mark.security
@pytest.mark.parametrize(
    "tool",
    [
        "list_tables",
        "table_exists",
        "describe_table",
        "record_exists",
        "list_records",
        "get_record",
    ],
)
async def test_an_approved_calls_read_tool_acts_as_the_agent(world: _World, tool: str):
    decider = await _member(world, "owner")
    async with world.factory() as db:
        with acting_decider("c1", decider.id):
            auth = await run_authority(
                db, _ctx(_agent_deps(world), call="c1"), {world.orders.id: ALL}, tool=tool
            )

    assert auth.user_id is None
    assert auth.principal_agent_id == AGENT


@pytest.mark.security
async def test_an_agent_run_cannot_describe_a_table_its_spec_does_not_grant(world: _World):
    """An organization-visible table, so any member could read it: the agent still gets nothing."""
    async with world.factory() as db:
        invoices = await VirtualTableService(db).create_table(
            ctx_for(world.owner, world.org),
            TableCreate(name="Ledger", visibility="org", columns=[column("Payee", "text")]),
        )
        await db.commit()
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.CREATE}})

    answer = await call("describe_table", _ctx(_agent_deps(world)), table_id=invoices.id)

    assert "no access to table" in answer
    assert "Ledger" not in answer and "Payee" not in answer


@pytest.mark.security
def test_schema_authority_lends_nothing_for_a_table_the_spec_does_not_grant():
    granted, other = uuid.uuid4(), uuid.uuid4()
    agent = agent_context(organization_id=uuid.uuid4(), agent_id=AGENT)

    lent = schema_authority(agent, {granted: frozenset({TableOperation.CREATE})}, granted)
    withheld = schema_authority(agent, {granted: frozenset({TableOperation.CREATE})}, other)

    assert any(resource_id == granted for _kind, resource_id, _level in lent.agent_grants)
    assert withheld is agent
    assert not any(resource_id == other for _kind, resource_id, _level in withheld.agent_grants)


@pytest.mark.security
async def test_a_member_run_with_only_a_create_grant_may_not_describe_the_table(world: _World):
    call, _cap, _ts = _tools({world.orders.id: {TableOperation.CREATE}})

    answer = await call("describe_table", _ctx(world.deps()), table_id=world.orders.id)

    assert "may not read" in answer
