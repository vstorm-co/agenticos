"""The page bindings check against a real database: views, columns, the person and the grants.

`check_bindings` answers in text the model reads, so every refusal here asserts the
exact sentence, and every refusal a person must not learn from asserts what it does
not say as much as what it does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.resource_grant import GrantLevel
from app.repositories import resource_grant_repo
from app.schemas.artifact import ArtifactBinding, BindingRequest
from app.schemas.table_view import TableViewCreate, TableViewRead
from app.schemas.virtual_table import (
    ColumnDef,
    ColumnInput,
    OptionInput,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.access import TABLE
from app.services.artifact_bindings import BindingCheck, check_bindings
from app.services.virtual_tables import TableViewService, VirtualTableService
from tests.integration.virtual_table_support import (
    column,
    ctx_for,
    make_org,
    make_user,
    orders_table,
)

pytestmark = pytest.mark.anyio

NO_PERSON = "Only a run acting for a member can bind a page to a view."
READ = frozenset({"read"})


@dataclass
class _World:
    db: AsyncSession
    org_id: UUID
    owner: AuthContext
    tables: VirtualTableService
    views: TableViewService
    table: TableRead
    view: TableViewRead

    def col(self, label: str, table: TableRead | None = None) -> UUID:
        return next(c.id for c in (table or self.table).columns if c.label == label)

    def stored(
        self,
        fields: dict[str, str],
        *,
        name: str = "tickets",
        view: TableViewRead | None = None,
        table: TableRead | None = None,
        status: Literal["ok", "unavailable"] = "ok",
        reason: str | None = None,
    ) -> ArtifactBinding:
        """A binding as a version stores it, its fields given by column label."""
        table = table or self.table
        return ArtifactBinding(
            name=name,
            view_id=(view or self.view).id,
            table_id=table.id,
            fields={field: self.col(label, table) for field, label in fields.items()},
            status=status,
            reason=reason,
        )

    async def check(
        self,
        requested: dict[str, BindingRequest] | None,
        *,
        previous: list[ArtifactBinding] | None = None,
        person: AuthContext | Literal["owner"] | None = "owner",
        grants: dict[UUID, frozenset[str]] | None = None,
        recheck_person: bool = False,
    ) -> list[BindingCheck]:
        return await check_bindings(
            self.db,
            organization_id=self.org_id,
            requested=requested,
            previous=previous or [],
            person=self.owner if person == "owner" else person,
            grants={self.table.id: READ} if grants is None else grants,
            recheck_person=recheck_person,
        )

    async def one(
        self,
        requested: dict[str, BindingRequest] | None,
        *,
        previous: list[ArtifactBinding] | None = None,
        person: AuthContext | Literal["owner"] | None = "owner",
        grants: dict[UUID, frozenset[str]] | None = None,
        recheck_person: bool = False,
    ) -> BindingCheck:
        [check] = await self.check(
            requested,
            previous=previous,
            person=person,
            grants=grants,
            recheck_person=recheck_person,
        )
        return check

    async def archive_column(self, label: str, table: TableRead | None = None) -> None:
        table = await self.tables.describe_table(self.owner, (table or self.table).id)
        await self.tables.update_schema(
            self.owner,
            table.id,
            SchemaUpdate(
                expected_version=table.schema_version,
                columns=[_kept(c) for c in table.columns if c.label != label and not c.archived],
            ),
        )


def _kept(existing: ColumnDef) -> ColumnInput:
    return ColumnInput(
        id=existing.id,
        label=existing.label,
        type=existing.type,
        options=[OptionInput(id=o.id, label=o.label) for o in existing.options],
        link_table_id=existing.link_table_id,
        link_column_id=existing.link_column_id,
        target_column_id=existing.target_column_id,
        aggregate=existing.aggregate,
        formula=existing.formula,
    )


async def _world(
    db: AsyncSession, *, visibility: Literal["private", "shared"] = "shared"
) -> _World:
    user = await make_user(db)
    org = await make_org(db, owner=user)
    owner = ctx_for(user, org)
    tables = VirtualTableService(db)
    views = TableViewService(db)
    table = await orders_table(tables, owner)
    view = await views.create_view(
        owner, table.id, TableViewCreate(name="Open", kind="table", visibility=visibility)
    )
    return _World(db, org.id, owner, tables, views, table, view)


def _ask(view: TableViewRead | UUID, **fields: str) -> BindingRequest:
    return BindingRequest(view=view if isinstance(view, UUID) else view.id, fields=fields)


async def _a_member(world: _World, *, grant: bool) -> AuthContext:
    """A member of the world's org, holding a read grant on its table or none."""
    user = await make_user(world.db)
    if grant:
        await resource_grant_repo.upsert(
            world.db,
            organization_id=world.org_id,
            subject_user_id=user.id,
            resource_type=TABLE.key,
            resource_id=world.table.id,
            level=GrantLevel.READ,
        )
    return AuthContext(user_id=user.id, organization_id=world.org_id, role="member")


async def _linked(world: _World) -> tuple[TableRead, TableRead, TableViewRead]:
    """A products table, and an orders table reading it by link, lookup, rollup and formula."""
    products = await world.tables.create_table(
        world.owner,
        TableCreate(name="Products", columns=[column("Name", "text"), column("Price", "number")]),
    )
    orders = await world.tables.create_table(
        world.owner,
        TableCreate(
            name="Linked orders",
            columns=[column("Ref", "text"), column("Items", "link", link_table_id=products.id)],
        ),
    )
    link = next(c.id for c in orders.columns if c.label == "Items")
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
                    target_column_id=next(c.id for c in products.columns if c.label == "Name"),
                ),
                column(
                    "Sum",
                    "rollup",
                    link_column_id=link,
                    target_column_id=next(c.id for c in products.columns if c.label == "Price"),
                    aggregate="sum",
                ),
                column("Doubled", "formula", formula="{Sum} * 2"),
                column("Shout", "formula", formula="{Ref}"),
            ],
        ),
    )
    view = await world.views.create_view(
        world.owner, orders.id, TableViewCreate(name="All", kind="table", visibility="shared")
    )
    return products, orders, view


class TestTheRequest:
    """Rule 1: the names and the cap, before anything is read."""

    @pytest.mark.security
    async def test_a_binding_name_must_match_the_pattern(self, db):
        world = await _world(db)

        check = await world.one({"Tickets": _ask(world.view, status="Status")})

        assert check.name == "Tickets"
        assert check.binding is None
        assert check.problem == "Binding name 'Tickets' must match `^[a-z_][a-z0-9_]{0,63}$`."

    @pytest.mark.security
    async def test_a_page_takes_at_most_five_bindings(self, db):
        world = await _world(db)
        requested = {f"b{index}": _ask(world.view, status="Status") for index in range(6)}

        checks = await world.check(requested)

        assert [c.name for c in checks] == list(requested)
        assert {c.problem for c in checks} == {"A page takes at most 5 bindings; this one has 6."}
        assert all(c.binding is None for c in checks)


class TestResolving:
    """Rule 2: fields resolve against the live columns, then their names are checked."""

    async def test_a_label_and_an_id_resolve_to_the_same_binding(self, db):
        world = await _world(db)
        status = world.col("Status")

        by_label, by_id = await world.check(
            {
                "by_label": _ask(world.view, status="sTaTuS"),
                "by_id": _ask(world.view, status=str(status).upper()),
            }
        )

        assert by_label.problem is by_id.problem is None
        assert by_label.changed is by_id.changed is True
        assert by_label.binding == ArtifactBinding(
            name="by_label",
            view_id=world.view.id,
            table_id=world.table.id,
            fields={"status": status},
        )
        assert by_id.binding is not None
        assert by_id.binding.fields == by_label.binding.fields

    async def test_an_unknown_label_names_the_field_and_the_view(self, db):
        world = await _world(db)

        check = await world.one({"tickets": _ask(world.view, status="Stat")})

        assert check.binding is None
        assert check.problem == (
            f"Binding tickets: field status names 'Stat', which is not a live column of view "
            f"{world.view.id}; `list_views` lists its columns."
        )

    async def test_an_archived_column_resolves_by_neither_label_nor_id(self, db):
        world = await _world(db)
        quantity = world.col("Quantity")
        await world.archive_column("Quantity")

        by_id, by_label = await world.check(
            {
                "by_id": _ask(world.view, qty=str(quantity)),
                "by_label": _ask(world.view, qty="Quantity"),
            }
        )

        assert by_id.problem == (
            f"Binding by_id: field qty names '{quantity}', which is not a live column of view "
            f"{world.view.id}; `list_views` lists its columns."
        )
        assert by_label.problem is not None
        assert "'Quantity', which is not a live column" in by_label.problem

    async def test_a_label_matching_two_columns_asks_for_an_id(self, db):
        world = await _world(db)
        table = await world.tables.update_schema(
            world.owner,
            world.table.id,
            SchemaUpdate(
                expected_version=world.table.schema_version,
                columns=[*(_kept(c) for c in world.table.columns), column("STATUS", "text")],
            ),
        )
        world.table = table

        check = await world.one({"tickets": _ask(world.view, status="status")})

        assert check.binding is None
        assert check.problem == (
            f"Binding tickets: field status names 'status', which matches more than one column "
            f"of view {world.view.id}; give the column's id."
        )

    async def test_every_field_that_does_not_resolve_is_named(self, db):
        world = await _world(db)

        check = await world.one({"tickets": _ask(world.view, a="Nope", b="Status", c="Gone")})

        assert check.problem == (
            f"Binding tickets: field a names 'Nope', which is not a live column of view "
            f"{world.view.id}; `list_views` lists its columns. "
            f"Binding tickets: field c names 'Gone', which is not a live column of view "
            f"{world.view.id}; `list_views` lists its columns."
        )

    @pytest.mark.security
    async def test_a_field_name_must_match_the_pattern(self, db):
        world = await _world(db)

        check = await world.one({"tickets": _ask(world.view, Status="Status")})

        assert check.problem == (
            "Binding tickets: field name 'Status' must match `^[a-z_][a-z0-9_]{0,63}$`."
        )

    @pytest.mark.security
    @pytest.mark.parametrize("reserved", ["id", "__proto__", "constructor", "prototype"])
    async def test_a_reserved_field_name_is_refused(self, db, reserved):
        world = await _world(db)

        check = await world.one({"tickets": _ask(world.view, **{reserved: "Status"})})

        assert check.problem == (
            f"Binding tickets: field name {reserved} is reserved; choose another."
        )

    async def test_a_binding_takes_at_most_fifty_fields(self, db):
        world = await _world(db)
        fields = {f"f{index}": "Customer" for index in range(51)}

        check = await world.one({"tickets": _ask(world.view, **fields)})

        assert (
            check.problem == "Binding tickets: a binding takes at most 50 fields; this one has 51."
        )

    async def test_two_field_names_for_one_column_are_refused(self, db):
        world = await _world(db)

        check = await world.one(
            {"tickets": _ask(world.view, state="Status", status=str(world.col("Status")))}
        )

        assert check.problem == (
            "Binding tickets: fields state and status name the same column; keep one."
        )

    async def test_requested_bindings_replace_the_previous_ones(self, db):
        world = await _world(db)

        checks = await world.check(
            {"orders": _ask(world.view, total="Total")},
            previous=[world.stored({"status": "Status"})],
        )

        assert [(c.name, c.problem) for c in checks] == [("orders", None)]

    async def test_a_view_that_does_not_resolve_has_no_resolved_binding(self, db):
        world = await _world(db)
        missing = uuid.uuid4()

        check = await world.one({"tickets": _ask(missing, status="Status")})

        assert check.binding is None
        assert check.problem == f"View {missing} not found."
        assert check.changed is True


class TestThePerson:
    """Rules 3 and 4: a changed binding needs a person, and is checked as them."""

    async def test_an_identical_binding_sent_again_is_not_changed_and_needs_no_person(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status", "total": "Total"})

        by_label, by_id = await world.check(
            {
                "tickets": _ask(world.view, status="status", total="TOTAL"),
                "same": _ask(
                    world.view, status=str(world.col("Status")), total=str(world.col("Total"))
                ),
            },
            previous=[stored, world.stored({"status": "Status", "total": "Total"}, name="same")],
            person=None,
        )

        assert (by_label.problem, by_label.changed, by_label.binding) == (None, False, stored)
        assert (by_id.problem, by_id.changed) == (None, False)

    async def test_a_renamed_field_is_a_changed_binding(self, db):
        world = await _world(db)

        check = await world.one(
            {"tickets": _ask(world.view, state="Status")},
            previous=[world.stored({"status": "Status"})],
        )

        assert (check.problem, check.changed) == (None, True)

    @pytest.mark.security
    async def test_a_changed_binding_with_no_person_is_refused_without_naming_anything(self, db):
        world = await _world(db)

        checks = await world.check(
            {
                "fine": _ask(world.view, status="Status"),
                "bad_label": _ask(world.view, status="Nope"),
                "no_view": _ask(uuid.uuid4(), status="Status"),
                "renamed": _ask(world.view, state="Status"),
            },
            previous=[world.stored({"status": "Status"}, name="renamed")],
            person=None,
        )

        assert [c.problem for c in checks] == [NO_PERSON] * 4
        assert all(c.changed for c in checks)

    @pytest.mark.security
    async def test_a_view_id_from_another_org_is_refused(self, db):
        world = await _world(db)
        elsewhere = await _world(db)

        check = await world.one({"tickets": _ask(elsewhere.view, status="Status")})

        assert check.binding is None
        assert check.problem == f"View {elsewhere.view.id} not found."

    @pytest.mark.security
    async def test_a_view_from_another_org_and_a_missing_view_read_the_same(self, db):
        world = await _world(db)
        elsewhere = await _world(db)
        missing = uuid.uuid4()

        foreign, absent = await world.check(
            {
                "foreign": _ask(elsewhere.view, status="Nope"),
                "absent": _ask(missing, status="Nope"),
            }
        )

        assert foreign.problem == f"View {elsewhere.view.id} not found."
        assert absent.problem == f"View {missing} not found."

    @pytest.mark.security
    async def test_a_colleague_s_private_view_reveals_no_columns(self, db):
        world = await _world(db, visibility="private")
        colleague = await _a_member(world, grant=True)
        stranger = await _a_member(world, grant=False)
        shared = await world.views.create_view(
            world.owner,
            world.table.id,
            TableViewCreate(name="Team", kind="table", visibility="shared"),
        )

        private = await world.one(
            {"tickets": _ask(world.view, status="Nope", id="Status")}, person=colleague
        )
        unreachable = await world.one(
            {"tickets": _ask(shared, status="Nope", id="Status")}, person=stranger
        )

        assert private.problem == f"View {world.view.id} not found."
        assert unreachable.problem == f"View {shared.id} not found."

    async def test_the_owner_of_a_private_view_may_bind_it(self, db):
        world = await _world(db, visibility="private")

        check = await world.one({"tickets": _ask(world.view, status="Status")})

        assert check.problem is None

    @pytest.mark.security
    async def test_a_visible_view_on_an_archived_table_is_refused(self, db):
        world = await _world(db)
        await world.tables.archive_table(world.owner, world.table.id)

        check = await world.one({"tickets": _ask(world.view, status="Status")})

        assert check.binding is None
        assert check.problem == f"View {world.view.id} is on an archived table."


class TestTheGrants:
    """Rules 5 and 6: the spec grants read on the table, and on every table read through a link."""

    @pytest.mark.security
    async def test_a_table_the_agent_is_not_granted_is_refused(self, db):
        world = await _world(db)

        for grants in ({}, {world.table.id: frozenset({"create"})}):
            check = await world.one({"tickets": _ask(world.view, status="Status")}, grants=grants)

            assert check.binding is not None
            assert check.problem == (
                f"Binding tickets: this agent is not granted read on the table of view "
                f"{world.view.id}."
            )

    @pytest.mark.security
    async def test_a_lookup_through_an_ungranted_table_is_refused(self, db):
        world = await _world(db)
        products, orders, view = await _linked(world)

        refused = await world.one(
            {"tickets": _ask(view, ref="Ref", names="Names")}, grants={orders.id: READ}
        )
        allowed = await world.one(
            {"tickets": _ask(view, ref="Ref", names="Names")},
            grants={orders.id: READ, products.id: READ},
        )

        assert refused.problem == (
            "Binding tickets: field names reads a linked table this agent is not granted read on."
        )
        assert allowed.problem is None

    @pytest.mark.security
    async def test_a_formula_over_an_ungranted_rollup_is_refused(self, db):
        world = await _world(db)
        _products, orders, view = await _linked(world)

        refused = await world.one(
            {"tickets": _ask(view, doubled="Doubled", shout="Shout")}, grants={orders.id: READ}
        )

        assert refused.problem == (
            "Binding tickets: field doubled reads a linked table this agent is not granted read on."
        )

    @pytest.mark.security
    async def test_every_field_read_through_an_ungranted_link_is_named(self, db):
        world = await _world(db)
        _products, orders, view = await _linked(world)

        refused = await world.one(
            {"tickets": _ask(view, items="Items", total="Sum")}, grants={orders.id: READ}
        )

        assert refused.problem == (
            "Binding tickets: fields items, total read a linked table this agent is not granted "
            "read on."
        )


class TestCarriedForward:
    """Bindings carried forward unchanged: rules 2, 5 and 6 only, with no person and no labels."""

    async def test_carried_forward_bindings_need_no_person(self, db):
        world = await _world(db, visibility="private")
        stored = world.stored({"status": "Status"})

        check = await world.one(None, previous=[stored], person=None)

        assert (check.name, check.binding, check.problem, check.changed) == (
            "tickets",
            stored,
            None,
            False,
        )

    @pytest.mark.security
    async def test_carried_bindings_skip_the_person_check(self, db):
        world = await _world(db, visibility="private")
        stranger = await _a_member(world, grant=False)

        check = await world.one(
            None, previous=[world.stored({"status": "Status"})], person=stranger
        )

        assert check.problem is None

    async def test_a_carried_forward_field_since_archived_is_a_problem(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status", "total": "Total"})
        await world.archive_column("Status")

        check = await world.one(None, previous=[stored], person=None)

        assert check.binding is None
        assert check.problem == (
            "Binding tickets: field status points at a column that was archived; "
            "pass `bindings` to replace them."
        )

    async def test_every_carried_field_since_archived_is_named(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status", "total": "Total"})
        await world.archive_column("Status")
        await world.archive_column("Total")

        check = await world.one(None, previous=[stored])

        assert check.problem == (
            "Binding tickets: fields status, total point at columns that were archived; "
            "pass `bindings` to replace them."
        )

    async def test_a_carried_binding_whose_view_was_deleted_is_a_problem(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status"})
        await world.views.delete_view(world.owner, world.table.id, world.view.id)

        check = await world.one(None, previous=[stored])

        assert check.binding is None
        assert check.problem == (
            "Binding tickets: its view was deleted; pass `bindings` to replace them."
        )

    async def test_a_carried_binding_whose_table_was_archived_is_a_problem(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status"})
        await world.tables.archive_table(world.owner, world.table.id)

        check = await world.one(None, previous=[stored])

        assert check.problem == (
            "Binding tickets: its view's table was archived; pass `bindings` to replace them."
        )

    @pytest.mark.security
    async def test_a_carried_binding_on_an_ungranted_table_is_a_problem(self, db):
        world = await _world(db)

        check = await world.one(None, previous=[world.stored({"status": "Status"})], grants={})

        assert check.binding is not None
        assert check.problem == (
            "Binding tickets: this agent is not granted read on its view's table; "
            "pass `bindings` to replace them."
        )

    @pytest.mark.security
    async def test_a_carried_lookup_through_an_ungranted_table_is_a_problem(self, db):
        world = await _world(db)
        _products, orders, view = await _linked(world)
        stored = world.stored({"names": "Names"}, view=view, table=orders)

        check = await world.one(None, previous=[stored], grants={orders.id: READ})

        assert check.problem == (
            "Binding tickets: field names reads a linked table this agent is not granted read on; "
            "pass `bindings` to replace them."
        )


class TestRecheckingAsThePerson:
    """Restore: every binding checked as the person restoring, and failures marked, never refused."""

    async def test_a_binding_the_person_can_see_stays_ok(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status"})

        check = await world.one(None, previous=[stored], recheck_person=True)

        assert (check.binding, check.problem, check.changed) == (stored, None, False)

    @pytest.mark.security
    async def test_recheck_as_the_person_marks_a_view_they_cannot_see_unavailable(self, db):
        world = await _world(db, visibility="private")
        colleague = await _a_member(world, grant=True)
        stored = world.stored({"status": "Status"})

        check = await world.one(None, previous=[stored], person=colleague, recheck_person=True)

        assert check.binding == stored.model_copy(
            update={"status": "unavailable", "reason": "view_missing"}
        )
        assert check.problem == f"View {world.view.id} not found."

    @pytest.mark.security
    async def test_recheck_with_no_person_marks_it_unavailable(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status"})

        check = await world.one(None, previous=[stored], person=None, recheck_person=True)

        assert check.binding == stored.model_copy(
            update={"status": "unavailable", "reason": "no_person"}
        )
        assert check.problem == NO_PERSON

    async def test_recheck_marks_an_archived_field_unavailable(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status"})
        await world.archive_column("Status")

        check = await world.one(None, previous=[stored], recheck_person=True)

        assert check.binding is not None
        assert (check.binding.status, check.binding.reason) == ("unavailable", "field_missing")

    async def test_recheck_marks_an_archived_table_unavailable(self, db):
        world = await _world(db)
        stored = world.stored({"status": "Status"})
        await world.tables.archive_table(world.owner, world.table.id)

        check = await world.one(None, previous=[stored], recheck_person=True)

        assert check.binding is not None
        assert (check.binding.status, check.binding.reason) == ("unavailable", "table_archived")
        assert check.problem == (
            "Binding tickets: its view's table was archived; pass `bindings` to replace them."
        )

    @pytest.mark.security
    async def test_recheck_marks_an_ungranted_table_unavailable(self, db):
        world = await _world(db)
        _products, orders, view = await _linked(world)
        on_orders = world.stored({"names": "Names"}, view=view, table=orders, name="orders")

        ungranted, linked = await world.check(
            None,
            previous=[world.stored({"status": "Status"}), on_orders],
            grants={orders.id: READ},
            recheck_person=True,
        )

        assert ungranted.binding is not None and linked.binding is not None
        assert (ungranted.binding.status, ungranted.binding.reason) == (
            "unavailable",
            "table_not_granted",
        )
        assert (linked.binding.status, linked.binding.reason) == (
            "unavailable",
            "linked_table_not_granted",
        )


class TestAStoredUnavailableBinding:
    """A binding a restore left `unavailable`: kept by a restore, rechecked by a person's publish."""

    def _unavailable(self, world: _World) -> ArtifactBinding:
        return world.stored({"status": "Status"}, status="unavailable", reason="table_not_granted")

    async def test_a_stored_unavailable_binding_stays_unavailable_on_restore(self, db):
        world = await _world(db)
        stored = self._unavailable(world)

        check = await world.one(None, previous=[stored], recheck_person=True)

        assert (check.binding, check.problem, check.changed) == (stored, None, False)

    async def test_a_stored_unavailable_binding_comes_back_ok_on_a_republish_by_a_person_who_can_see_it(
        self, db
    ):
        world = await _world(db)
        stored = self._unavailable(world)

        check = await world.one(None, previous=[stored])

        assert check.problem is None
        assert check.changed is False
        assert check.binding == stored.model_copy(update={"status": "ok", "reason": None})
        assert check.binding != stored

    @pytest.mark.security
    async def test_a_stored_unavailable_binding_that_still_fails_refuses_the_republish(self, db):
        world = await _world(db)
        stored = self._unavailable(world)

        ungranted = await world.one(None, previous=[stored], grants={})
        await world.tables.archive_table(world.owner, world.table.id)
        archived = await world.one(None, previous=[stored])

        assert ungranted.problem == (
            "Binding tickets is unavailable (table_not_granted); pass `bindings` to replace or "
            "drop it."
        )
        assert archived.problem == (
            "Binding tickets is unavailable (table_archived); pass `bindings` to replace or drop it."
        )

    @pytest.mark.security
    async def test_a_stored_unavailable_binding_on_a_view_the_person_cannot_see_is_not_found(
        self, db
    ):
        world = await _world(db, visibility="private")
        colleague = await _a_member(world, grant=True)
        stored = self._unavailable(world)
        await world.archive_column("Status")

        check = await world.one(None, previous=[stored], person=colleague)

        assert check.problem == f"View {world.view.id} not found."

    async def test_a_stored_unavailable_binding_resent_identically_is_rechecked(self, db):
        world = await _world(db)
        stored = self._unavailable(world)

        passing = await world.one({"tickets": _ask(world.view, status="Status")}, previous=[stored])
        failing = await world.one(
            {"tickets": _ask(world.view, status=str(world.col("Status")))},
            previous=[stored],
            grants={},
        )

        assert (passing.problem, passing.changed) == (None, False)
        assert passing.binding is not None and passing.binding.status == "ok"
        assert failing.problem == (
            "Binding tickets is unavailable (table_not_granted); pass `bindings` to replace or "
            "drop it."
        )

    async def test_a_stored_unavailable_binding_carried_by_a_run_with_no_person_stays_unavailable(
        self, db
    ):
        world = await _world(db)
        stored = self._unavailable(world)
        await world.archive_column("Status")

        omitted = await world.one(None, previous=[stored], person=None)
        resent = await world.one(
            {"tickets": _ask(world.view, status=str(world.col("Status")))},
            previous=[stored],
            person=None,
        )

        assert (omitted.binding, omitted.problem, omitted.changed) == (stored, None, False)
        assert (resent.binding, resent.problem, resent.changed) == (stored, None, False)
