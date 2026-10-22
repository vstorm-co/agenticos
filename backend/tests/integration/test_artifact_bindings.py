"""Page queries against a real database: resolving them at publish, and check 1.

`check_bindings` answers in text the model reads, so every refusal here asserts the
exact sentence, and every refusal a person must not learn from asserts what it does
not say as much as what it does. What a query reaches - formula inputs, lookup and
rollup links and targets, the column a linked table names its records by - is read
from real schemas, at the revisions they hold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import GrantLevel
from app.repositories import resource_grant_repo
from app.schemas.artifact import (
    ArtifactBinding,
    BindingDisclosure,
    BindingFilter,
    BindingRequest,
    BindingSort,
)
from app.schemas.table_view import TableViewConfig, TableViewCreate, TableViewRead
from app.schemas.virtual_table import (
    ColumnDef,
    ColumnInput,
    OptionInput,
    RecordFilter,
    RecordSort,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.access import TABLE
from app.services.artifact_bindings import (
    HINT,
    NO_PERSON,
    BindingCheck,
    Refused,
    check_bindings,
    fingerprint,
    reresolve,
)
from app.services.virtual_tables import TableViewService, VirtualTableService
from tests.integration.virtual_table_support import (
    column,
    ctx_for,
    make_org,
    make_user,
    orders_table,
)

pytestmark = pytest.mark.anyio

READ = frozenset({"read"})


def _kept(existing: ColumnDef, **changes: Any) -> ColumnInput:
    """A live column sent back as it is, or with `changes`."""
    return ColumnInput(
        **{
            "id": existing.id,
            "label": existing.label,
            "type": existing.type,
            "options": [OptionInput(id=o.id, label=o.label) for o in existing.options],
            "link_table_id": existing.link_table_id,
            "link_column_id": existing.link_column_id,
            "target_column_id": existing.target_column_id,
            "aggregate": existing.aggregate,
            "formula": existing.formula,
            **changes,
        }
    )


@dataclass
class _World:
    db: AsyncSession
    org_id: UUID
    owner: AuthContext
    tables: VirtualTableService
    views: TableViewService
    table: TableRead
    known: list[UUID] = field(default_factory=list)

    def col(self, label: str, table: TableRead | None = None) -> UUID:
        return next(c.id for c in (table or self.table).columns if c.label == label)

    def option(self, label: str, choice: str) -> str:
        column_def = next(c for c in self.table.columns if c.label == label)
        return str(next(o.id for o in column_def.options if o.label == choice))

    async def new_table(self, data: TableCreate) -> TableRead:
        table = await self.tables.create_table(self.owner, data)
        self.known.append(table.id)
        return table

    async def view(
        self,
        *,
        name: str = "Open",
        by: AuthContext | None = None,
        config: TableViewConfig | None = None,
        visibility: Literal["private", "shared"] = "shared",
    ) -> TableViewRead:
        return await self.views.create_view(
            by or self.owner,
            self.table.id,
            TableViewCreate(
                name=name, kind="table", visibility=visibility, config=config or TableViewConfig()
            ),
        )

    async def check(
        self,
        requested: dict[str, BindingRequest] | None,
        *,
        previous: list[ArtifactBinding] | None = None,
        person: AuthContext | Literal["owner"] | None = "owner",
        owner: AuthContext | Literal["owner"] | None = "owner",
        grants: dict[UUID, frozenset[str]] | None = None,
    ) -> list[BindingCheck]:
        return await check_bindings(
            self.db,
            requested=requested,
            previous=previous or [],
            person=self.owner if person == "owner" else person,
            owner=self.owner if owner == "owner" else owner,
            grants=dict.fromkeys(self.known, READ) if grants is None else grants,
        )

    async def one(self, request: BindingRequest, **kwargs: Any) -> BindingCheck:
        [check] = await self.check({"tickets": request}, **kwargs)
        return check

    async def bound(self, request: BindingRequest, **kwargs: Any) -> ArtifactBinding:
        check = await self.one(request, **kwargs)
        assert check.problem is None, check.problem
        assert check.binding is not None
        return check.binding

    async def reshape(
        self,
        table: TableRead | None = None,
        *,
        by: AuthContext | None = None,
        **changes: dict[str, Any] | None,
    ) -> TableRead:
        """Change a table's schema: each label to its column's changes, `None` to archive it."""
        current = await self.tables.describe_table(self.owner, (table or self.table).id)
        columns = [
            _kept(c, **(changes.get(c.label) or {}))
            for c in current.columns
            if not c.archived and not (c.label in changes and changes[c.label] is None)
        ]
        updated = await self.tables.update_schema(
            by or self.owner,
            current.id,
            SchemaUpdate(expected_version=current.schema_version, columns=columns),
        )
        if table is None:
            self.table = updated
        return updated

    async def colleagues(self) -> tuple[AuthContext, AuthContext]:
        """An admin to save a view, and a builder editing the table who cannot manage it.

        The builder's schema change is not refused for the admin's view, which is how a
        view comes to name a column that no longer is what it was saved against.
        """
        admin = await self.member()
        builder = await self.member()
        await resource_grant_repo.upsert(
            self.db,
            organization_id=self.org_id,
            subject_user_id=builder.subject_id,
            resource_type=TABLE.key,
            resource_id=self.table.id,
            level=GrantLevel.EDIT,
        )
        return (
            AuthContext(user_id=admin.user_id, organization_id=self.org_id, role="admin"),
            AuthContext(user_id=builder.user_id, organization_id=self.org_id, role="builder"),
        )

    async def member(self, *, grant_on: list[TableRead] | None = None) -> AuthContext:
        """A member of the world's org, with a read grant on each table named, or none."""
        user = await make_user(self.db)
        self.db.add(OrganizationMember(organization_id=self.org_id, user_id=user.id, role="member"))
        await self.db.flush()
        for table in grant_on or []:
            await resource_grant_repo.upsert(
                self.db,
                organization_id=self.org_id,
                subject_user_id=user.id,
                resource_type=TABLE.key,
                resource_id=table.id,
                level=GrantLevel.READ,
            )
        return AuthContext(user_id=user.id, organization_id=self.org_id, role="member")


async def _world(db: AsyncSession) -> _World:
    user = await make_user(db)
    org = await make_org(db, owner=user)
    owner = ctx_for(user, org)
    tables = VirtualTableService(db)
    table = await orders_table(tables, owner)
    return _World(db, org.id, owner, tables, TableViewService(db), table, known=[table.id])


async def _linked(world: _World) -> tuple[TableRead, TableRead]:
    """Products, and orders reading them by link, lookup, rollups and a formula."""
    products = await world.new_table(
        TableCreate(name="Products", columns=[column("Name", "text"), column("Price", "number")])
    )
    orders = await world.new_table(
        TableCreate(
            name="Linked orders",
            columns=[column("Ref", "text"), column("Items", "link", link_table_id=products.id)],
        )
    )
    link = world.col("Items", orders)
    orders = await world.tables.update_schema(
        world.owner,
        orders.id,
        SchemaUpdate(
            expected_version=orders.schema_version,
            columns=[
                *(_kept(c) for c in orders.columns),
                column(
                    "Names",
                    "lookup",
                    link_column_id=link,
                    target_column_id=world.col("Name", products),
                ),
                column(
                    "Sum",
                    "rollup",
                    link_column_id=link,
                    target_column_id=world.col("Price", products),
                    aggregate="sum",
                ),
                column("Count", "rollup", link_column_id=link, aggregate="count"),
                column("Doubled", "formula", formula="{Sum} * 2"),
            ],
        ),
    )
    return products, orders


def _revisions(table: TableRead, *labels: str) -> dict[UUID, int]:
    return {c.id: c.revision for c in table.columns if c.label in labels}


class TestFromAView:
    async def test_a_view_s_filters_and_sort_are_copied_into_the_query(self, db):
        world = await _world(db)
        open_only = RecordFilter(
            column_id=world.col("Status"), op="eq", value=world.option("Status", "Open")
        )
        biggest = RecordSort(by=str(world.col("Quantity")), direction="desc")
        await world.view(config=TableViewConfig(filters=[open_only], sort=biggest))

        binding = await world.bound(BindingRequest(view="open", fields={"customer": "Customer"}))

        assert (binding.table_id, binding.filters, binding.sort) == (
            world.table.id,
            [open_only],
            biggest,
        )
        assert binding.limit == 1000
        # A copy: nothing stored points back at the view.
        assert "view" not in binding.model_dump()

    async def test_a_view_with_a_search_is_refused_naming_it(self, db):
        world = await _world(db)
        view = await world.view(name="Acme", config=TableViewConfig(search="acme"))

        check = await world.one(BindingRequest(view=view.id, fields={"customer": "Customer"}))

        assert check.binding is None
        assert check.problem == (
            "Binding tickets: view 'Acme' searches for 'acme', and a page can't copy a search - "
            "it matches more as columns are added. Name a view without one, or the `table` "
            "with `filters`."
        )

    async def test_a_view_whose_filter_lost_its_column_is_refused(self, db):
        """Its filter on an archived column is dropped when it is read, so it matches more
        than it was saved to: copying it would bind what nobody chose."""
        world = await _world(db)
        admin, builder = await world.colleagues()
        status = RecordFilter(
            column_id=world.col("Status"), op="eq", value=world.option("Status", "Open")
        )
        view = await world.view(by=admin, config=TableViewConfig(filters=[status]))
        await world.reshape(by=builder, Status=None)

        check = await world.one(BindingRequest(view=view.id, fields={"customer": "Customer"}))

        assert check.problem == (
            "Binding tickets: a filter of view 'Open' names a column that is no longer live, "
            "so the view matches more than it was saved to. Fix the view, or name the `table` "
            "with `filters`."
        )

    async def test_explicit_filters_are_added_and_sort_and_limit_replace_the_view_s(self, db):
        world = await _world(db)
        open_only = RecordFilter(
            column_id=world.col("Status"), op="eq", value=world.option("Status", "Open")
        )
        await world.view(
            config=TableViewConfig(filters=[open_only], sort=RecordSort(by="updated_at"))
        )

        binding = await world.bound(
            BindingRequest(
                view="Open",
                fields={"customer": "Customer"},
                filters=[BindingFilter(column="quantity", op="gt", value=2)],
                sort=BindingSort(by="Total", direction="desc"),
                limit=25,
            )
        )

        assert binding.filters == [
            open_only,
            RecordFilter(column_id=world.col("Quantity"), op="gt", value=2),
        ]
        assert binding.sort == RecordSort(by=str(world.col("Total")), direction="desc")
        assert binding.limit == 25

    async def test_a_view_the_person_cannot_see_is_not_found(self, db):
        world = await _world(db)
        view = await world.view()
        member = await world.member()

        check = await world.one(
            BindingRequest(view=view.id, fields={"customer": "Customer"}), person=member
        )

        assert check.problem == f"View {view.id} not found.{HINT}"
        assert "Customer" not in check.problem


class TestFromATable:
    async def test_a_table_by_name_starts_from_every_record(self, db):
        world = await _world(db)

        binding = await world.bound(
            BindingRequest(
                table="orders",
                fields={"status": "Status"},
                filters=[BindingFilter(column="Status", op="in", value=["open"])],
            )
        )

        assert binding.table_id == world.table.id
        assert binding.sort == RecordSort()
        # A choice is named by its label and stored as its option's id.
        assert binding.filters == [
            RecordFilter(
                column_id=world.col("Status"), op="in", value=[world.option("Status", "Open")]
            )
        ]

    @pytest.mark.parametrize(
        ("request_", "problem"),
        [
            (
                {"view": "Open", "table": "Orders"},
                "Binding tickets: name its `view` or its `table`, not both.",
            ),
            ({}, "Binding tickets: name the `view` or the `table` it reads."),
        ],
        ids=["both", "neither"],
    )
    async def test_a_query_names_exactly_one_start(self, db, request_, problem):
        world = await _world(db)
        await world.view()

        check = await world.one(BindingRequest(fields={"customer": "Customer"}, **request_))

        assert check.problem == problem

    async def test_a_filter_on_no_live_column_is_refused_naming_it(self, db):
        world = await _world(db)

        check = await world.one(
            BindingRequest(
                table=world.table.id,
                fields={"customer": "Customer"},
                filters=[BindingFilter(column="Colour", op="eq", value="red")],
            )
        )

        assert check.problem == (
            "Binding tickets: filter 1 names 'Colour', which is not a live column of table "
            "Orders; `describe_table` lists its columns."
        )

    async def test_a_filter_the_column_cannot_answer_is_refused(self, db):
        world = await _world(db)

        check = await world.one(
            BindingRequest(
                table=world.table.id,
                fields={"customer": "Customer"},
                filters=[BindingFilter(column="Paid", op="contains", value="x")],
            )
        )

        assert check.problem is not None
        assert check.problem.startswith("Binding tickets: filter 1: ")

    async def test_a_limit_over_the_cap_is_refused(self, db):
        world = await _world(db)

        check = await world.one(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"}, limit=1001)
        )

        assert check.problem == "Binding tickets: `limit` is at most 1,000."

    async def test_a_table_the_agent_is_not_granted_is_refused(self, db):
        world = await _world(db)

        check = await world.one(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"}), grants={}
        )

        assert check.problem == (
            f"Binding tickets: this agent is not granted read on table {world.table.id}."
        )


class TestCheckOne:
    """The person behind the run, and the page's owner, must read every table reached."""

    @pytest.mark.security
    async def test_a_publisher_who_cannot_read_the_table_is_told_it_is_not_found(self, db):
        world = await _world(db)
        member = await world.member()

        check = await world.one(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"}), person=member
        )

        assert check.problem == f"Table {world.table.id} not found.{HINT}"

    @pytest.mark.security
    async def test_a_publisher_who_cannot_read_a_linked_table_is_refused(self, db):
        world = await _world(db)
        _products, orders = await _linked(world)
        member = await world.member(grant_on=[orders])

        check = await world.one(
            BindingRequest(table=orders.id, fields={"ref": "Ref", "names": "Names"}),
            person=member,
            owner=member,
        )

        assert check.problem == "Binding tickets: it reads through Items a table you can't read."

    @pytest.mark.security
    async def test_a_binding_the_page_s_owner_cannot_read_is_refused(self, db):
        """Its data is read with the owner's access, so an editor cannot bind past it."""
        world = await _world(db)
        _products, orders = await _linked(world)
        owner = await world.member(grant_on=[orders])

        check = await world.one(
            BindingRequest(table=orders.id, fields={"ref": "Ref", "sum": "Sum"}), owner=owner
        )
        plain = await world.one(BindingRequest(table=orders.id, fields={"ref": "Ref"}), owner=owner)

        assert check.problem == (
            "Binding tickets: the page's owner can't read Products, and a page's data is read "
            "with its owner's access."
        )
        assert plain.problem is None

    @pytest.mark.security
    async def test_a_page_with_no_active_owner_takes_no_new_binding(self, db):
        world = await _world(db)

        check = await world.one(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"}), owner=None
        )

        assert check.problem == (
            "Binding tickets: the page's owner is no longer an active member, and a page's "
            "data is read with its owner's access."
        )

    async def test_a_binding_sent_again_unchanged_is_not_checked_against_the_owner(self, db):
        world = await _world(db)
        request = BindingRequest(table=world.table.id, fields={"customer": "Customer"})
        stored = await world.bound(request)

        check = await world.one(request, previous=[stored], owner=None)

        assert (check.binding, check.changed, check.problem) == (stored, False, None)

    async def test_a_binding_reaching_a_new_revision_is_changed(self, db):
        world = await _world(db)
        request = BindingRequest(table=world.table.id, fields={"qty": "Quantity"})
        stored = await world.bound(request)
        await world.reshape(Quantity={"type": "text"})

        check = await world.one(request, previous=[stored])

        assert check.changed is True
        assert check.binding is not None
        assert check.binding.reach != stored.reach

    @pytest.mark.security
    async def test_a_run_with_no_person_binds_nothing(self, db):
        world = await _world(db)

        check = await world.one(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"}), person=None
        )

        assert (check.binding, check.problem) == (None, NO_PERSON)

    async def test_omitted_bindings_are_carried_exactly_as_stored(self, db):
        world = await _world(db)
        stored = await world.bound(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"})
        )

        [carried] = await world.check(None, previous=[stored], person=None, owner=None)

        assert (carried.binding, carried.changed, carried.disclosure) == (stored, False, None)


class TestTheReach:
    async def test_the_reach_follows_formulas_lookups_rollups_and_link_names(self, db):
        world = await _world(db)
        products, orders = await _linked(world)

        binding = await world.bound(
            BindingRequest(
                table=orders.id,
                fields={"doubled": "Doubled", "items": "Items"},
                filters=[BindingFilter(column="Ref", op="starts_with", value="A")],
            )
        )

        assert binding.reach.tables == {
            orders.id: _revisions(orders, "Doubled", "Sum", "Items", "Ref"),
            products.id: _revisions(products, "Price", "Name"),
        }
        assert binding.reach.named_by == {products.id: world.col("Name", products)}

    async def test_a_link_read_only_through_a_lookup_takes_no_link_names(self, db):
        world = await _world(db)
        products, orders = await _linked(world)

        binding = await world.bound(BindingRequest(table=orders.id, fields={"names": "Names"}))

        assert binding.reach.tables[products.id] == _revisions(products, "Name")
        assert binding.reach.named_by == {}

    async def test_the_sort_column_is_reached(self, db):
        world = await _world(db)

        binding = await world.bound(
            BindingRequest(
                table=world.table.id,
                fields={"customer": "Customer"},
                sort=BindingSort(by="Total"),
            )
        )

        assert binding.reach.tables == {
            world.table.id: _revisions(world.table, "Customer", "Total")
        }

    async def test_the_fingerprint_follows_the_query_and_its_reach(self, db):
        world = await _world(db)
        request = BindingRequest(table=world.table.id, fields={"qty": "Quantity"})
        first = await world.bound(request)
        again = await world.bound(request)
        await world.reshape(Quantity={"type": "text"})
        moved = await world.bound(request)

        assert fingerprint([first]) == fingerprint([again])
        assert fingerprint([first]) != fingerprint([moved])
        assert fingerprint([]) is None


class TestTheDisclosure:
    async def test_derived_fields_say_what_they_are_worked_out_from(self, db):
        world = await _world(db)
        _products, orders = await _linked(world)

        check = await world.one(
            BindingRequest(
                table=orders.id,
                fields={
                    "ref": "Ref",
                    "items": "Items",
                    "names": "Names",
                    "sum": "Sum",
                    "count": "Count",
                    "doubled": "Doubled",
                },
                filters=[BindingFilter(column="Ref", op="starts_with", value="A-")],
                sort=BindingSort(by="Ref", direction="desc"),
                limit=50,
            )
        )

        assert check.disclosure == BindingDisclosure(
            table="Linked orders",
            filters=['Ref starts with "A-"'],
            sort="Ref, descending",
            limit=50,
            fields={
                "ref": "Ref (text)",
                "items": "Items: link, labels from Products -> Name",
                "names": "Names: lookup of Products -> Name",
                "sum": "Sum: rollup sum of Products -> Price",
                "count": "Count: rollup count of Products",
                "doubled": "Doubled: formula over Sum",
            },
        )

    async def test_a_choice_is_disclosed_by_its_label_and_emptiness_in_words(self, db):
        world = await _world(db)

        check = await world.one(
            BindingRequest(
                table=world.table.id,
                fields={"customer": "Customer"},
                filters=[
                    BindingFilter(column="Status", op="eq", value="Open"),
                    BindingFilter(column="Due", op="is_null", value=False),
                ],
            )
        )

        assert check.disclosure is not None
        assert check.disclosure.filters == ['Status is "Open"', "Due is not empty"]
        assert check.disclosure.sort == "when created, ascending"
        assert check.disclosure.limit == 1000


class TestReresolving:
    """A restore keeps a version's query and reads its reach again."""

    async def test_the_query_is_kept_and_its_revisions_read_again(self, db):
        world = await _world(db)
        stored = await world.bound(BindingRequest(table=world.table.id, fields={"qty": "Quantity"}))
        await world.reshape(Quantity={"type": "text"})

        restored = await reresolve(db, stored, person=world.owner, owner=world.owner)

        assert isinstance(restored, ArtifactBinding)
        assert restored.model_dump(exclude={"reach"}) == stored.model_dump(exclude={"reach"})
        assert restored.reach.tables == {world.table.id: _revisions(world.table, "Quantity")}

    async def test_an_archived_column_is_kept_in_the_reach(self, db):
        world = await _world(db)
        stored = await world.bound(BindingRequest(table=world.table.id, fields={"qty": "Quantity"}))
        await world.reshape(Quantity=None)

        restored = await reresolve(db, stored, person=world.owner, owner=world.owner)

        assert isinstance(restored, ArtifactBinding)
        assert restored.reach.tables == {world.table.id: _revisions(world.table, "Quantity")}

    async def test_a_filter_the_table_no_longer_answers_refuses_the_restore(self, db):
        """`Total` converted to text takes no `gt`: restored as it was, every load would fail."""
        world = await _world(db)
        stored = await world.bound(
            BindingRequest(
                table=world.table.id,
                fields={"customer": "Customer"},
                filters=[BindingFilter(column="Total", op="gt", value=5)],
            )
        )
        await world.reshape(Total={"type": "text"})

        refused = await reresolve(db, stored, person=world.owner, owner=world.owner)

        assert isinstance(refused, Refused) and refused.forbidden is False
        assert refused.message.startswith("Binding tickets: filter 1: ")

    @pytest.mark.security
    async def test_a_restorer_who_cannot_read_the_table_is_refused(self, db):
        world = await _world(db)
        stored = await world.bound(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"})
        )
        member = await world.member()

        refused = await reresolve(db, stored, person=member, owner=world.owner)

        assert refused == Refused("Binding tickets reads a table you can't read.", forbidden=True)

    @pytest.mark.security
    async def test_an_owner_who_cannot_read_the_table_is_refused(self, db):
        world = await _world(db)
        stored = await world.bound(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"})
        )
        owner = await world.member()

        refused = await reresolve(db, stored, person=world.owner, owner=owner)

        assert refused == Refused(
            "Binding tickets: the page's owner can't read Orders, and a page's data is read "
            "with its owner's access.",
            forbidden=True,
        )


class TestTheRequest:
    """What the model wrote, refused in words it can act on."""

    @pytest.mark.parametrize(
        ("name", "problem"),
        [
            ("Tickets", "Binding name 'Tickets' must match `^[a-z_][a-z0-9_]{0,63}$`."),
            ("__proto__", "Binding name __proto__ is reserved; choose another."),
        ],
    )
    async def test_a_binding_name_is_held_to_the_pattern(self, db, name, problem):
        world = await _world(db)

        [check] = await world.check(
            {name: BindingRequest(table=world.table.id, fields={"customer": "Customer"})}
        )

        assert check.problem == problem

    @pytest.mark.parametrize(
        ("fields", "problem"),
        [
            (
                {"2nd": "Customer"},
                "Binding tickets: field name '2nd' must be words of letters, digits and `_` "
                "with single spaces between them, at most 64 characters, not starting with a "
                "digit.",
            ),
            ({"id": "Customer"}, "Binding tickets: field name id is reserved; choose another."),
            (
                {"a": "Customer", "b": "customer"},
                "Binding tickets: fields a and b name the same column; keep one.",
            ),
        ],
        ids=["not-words", "reserved", "same-column"],
    )
    async def test_field_names_are_checked_once_they_resolve(self, db, fields, problem):
        world = await _world(db)

        check = await world.one(BindingRequest(table=world.table.id, fields=fields))

        assert check.problem == problem

    async def test_a_binding_takes_at_most_fifty_fields(self, db):
        world = await _world(db)
        fields = {f"f{number}": "Customer" for number in range(51)}

        check = await world.one(BindingRequest(table=world.table.id, fields=fields))

        assert check.problem == (
            "Binding tickets: a binding takes at most 50 fields; this one has 51."
        )

    async def test_every_field_and_the_sort_that_do_not_resolve_are_named(self, db):
        world = await _world(db)
        await world.reshape(Customer={"label": "Client"}, Paid={"label": "client"})

        check = await world.one(
            BindingRequest(
                table=world.table.id,
                fields={"who": "CLIENT", "gone": "Colour"},
                sort=BindingSort(by="Weight"),
            )
        )

        assert check.problem == (
            "Binding tickets: field who names 'CLIENT', which matches more than one column of "
            "table Orders; give the column's id. "
            "Binding tickets: field gone names 'Colour', which is not a live column of table "
            "Orders; `describe_table` lists its columns. "
            "Binding tickets: its sort names 'Weight', which is not a live column of table "
            "Orders; `describe_table` lists its columns."
        )

    async def test_a_sort_the_column_cannot_answer_is_refused(self, db):
        world = await _world(db)

        check = await world.one(
            BindingRequest(
                table=world.table.id, fields={"customer": "Customer"}, sort=BindingSort(by="Tags")
            )
        )

        assert check.problem == (
            "Binding tickets: its sort: A multi_select column cannot be sorted."
        )

    async def test_a_view_filter_the_table_no_longer_answers_is_named(self, db):
        world = await _world(db)
        admin, builder = await world.colleagues()
        await world.view(
            by=admin,
            config=TableViewConfig(
                filters=[RecordFilter(column_id=world.col("Quantity"), op="gt", value=2)]
            ),
        )
        await world.reshape(by=builder, Quantity={"type": "text"})

        check = await world.one(BindingRequest(view="Open", fields={"customer": "Customer"}))

        assert check.problem is not None
        assert check.problem.startswith("Binding tickets: the view's filter on Quantity: ")

    async def test_a_query_takes_at_most_twenty_filters_the_view_s_included(self, db):
        world = await _world(db)
        some = RecordFilter(column_id=world.col("Quantity"), op="gt", value=0)
        await world.view(config=TableViewConfig(filters=[some] * 20))

        check = await world.one(
            BindingRequest(
                view="Open",
                fields={"customer": "Customer"},
                filters=[BindingFilter(column="Total", op="gt", value=0)],
            )
        )

        assert check.problem == (
            "Binding tickets: a query takes at most 20 filters, the view's included; this one "
            "has 21."
        )


class TestNamingTheStart:
    async def test_no_view_of_that_name_says_where_ids_come_from(self, db):
        world = await _world(db)

        check = await world.one(BindingRequest(view="Closed", fields={"customer": "Customer"}))

        assert check.problem == (
            f"Binding tickets: no saved view named 'Closed' that this agent may read.{HINT}"
        )

    async def test_two_views_of_that_name_ask_for_an_id(self, db):
        world = await _world(db)
        mine = await world.view()
        colleague = await world.member(grant_on=[world.table])
        colleague = AuthContext(
            user_id=colleague.user_id, organization_id=world.org_id, role="admin"
        )
        theirs = await world.view(by=colleague)

        check = await world.one(BindingRequest(view="Open", fields={"customer": "Customer"}))

        ids = ", ".join(sorted(str(view.id) for view in (mine, theirs)))
        assert check.problem == (
            f"Binding tickets: 2 saved views are named 'Open'; pass the id of one: {ids}."
        )

    async def test_a_name_is_looked_up_only_among_tables_the_person_reads(self, db):
        world = await _world(db)
        other = await world.new_table(TableCreate(name="Other", columns=[column("A", "text")]))
        member = await world.member(grant_on=[other])

        found = await world.one(
            BindingRequest(table="other", fields={"a": "A"}), person=member, owner=member
        )
        hidden = await world.one(
            BindingRequest(table="Orders", fields={"c": "Customer"}), person=member, owner=member
        )

        assert found.binding is not None and found.binding.table_id == other.id
        assert hidden.problem == (
            f"Binding tickets: no table named 'Orders' that this agent may read.{HINT}"
        )

    async def test_an_archived_table_is_refused(self, db):
        world = await _world(db)
        await world.tables.archive_table(world.owner, world.table.id)

        by_id = await world.one(
            BindingRequest(table=world.table.id, fields={"customer": "Customer"})
        )
        by_name = await world.one(BindingRequest(table="Orders", fields={"c": "Customer"}))

        assert by_id.problem == "Binding tickets: table Orders is archived."
        assert by_name.problem == (
            f"Binding tickets: no table named 'Orders' that this agent may read.{HINT}"
        )

    async def test_a_view_on_an_archived_table_is_refused(self, db):
        world = await _world(db)
        view = await world.view()
        await world.tables.archive_table(world.owner, world.table.id)

        check = await world.one(BindingRequest(view=view.id, fields={"customer": "Customer"}))

        assert check.problem == f"Binding tickets: view {view.id} is on an archived table."


class TestLinkedTables:
    async def test_a_linked_table_the_agent_is_not_granted_is_refused(self, db):
        world = await _world(db)
        _products, orders = await _linked(world)

        check = await world.one(
            BindingRequest(table=orders.id, fields={"names": "Names"}), grants={orders.id: READ}
        )

        assert check.problem == (
            "Binding tickets: it reads through Items a linked table this agent is not granted "
            "read on."
        )

    async def test_an_archived_linked_table_is_refused_at_publish(self, db):
        world = await _world(db)
        products, orders = await _linked(world)
        await world.tables.archive_table(world.owner, products.id)

        check = await world.one(BindingRequest(table=orders.id, fields={"items": "Items"}))

        assert check.problem == (
            "Binding tickets: it reads through Items table Products, which is archived."
        )

    @pytest.mark.security
    async def test_a_restorer_who_cannot_read_a_linked_table_is_refused(self, db):
        world = await _world(db)
        _products, orders = await _linked(world)
        stored = await world.bound(BindingRequest(table=orders.id, fields={"sum": "Sum"}))
        member = await world.member(grant_on=[orders])

        refused = await reresolve(db, stored, person=member, owner=world.owner)

        assert refused == Refused(
            "Binding tickets: it reads through Items a table you can't read.", forbidden=True
        )

    async def test_a_link_to_a_table_with_no_text_column_is_labelled_by_record_ids(self, db):
        world = await _world(db)
        counts = await world.new_table(TableCreate(name="Counts", columns=[column("N", "integer")]))
        tallies = await world.new_table(
            TableCreate(
                name="Tallies",
                columns=[
                    column("Counted", "link", link_table_id=counts.id),
                    column("Fixed", "formula", formula="1 + 1"),
                ],
            )
        )

        check = await world.one(
            BindingRequest(table=tallies.id, fields={"counted": "Counted", "fixed": "Fixed"})
        )

        assert check.binding is not None
        assert check.binding.reach.named_by == {counts.id: None}
        assert check.disclosure is not None
        assert check.disclosure.fields == {
            "counted": "Counted: link, labels from Counts -> record ids",
            "fixed": "Fixed: formula",
        }
