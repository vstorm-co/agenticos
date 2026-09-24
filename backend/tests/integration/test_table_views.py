"""Table Views against a real database: visibility, ownership, tenant isolation,

and the dependency checker that refuses archiving a column a view still uses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.db.models.resource_grant import GrantLevel
from app.repositories import resource_grant_repo, table_view_repo
from app.schemas.table_view import TableViewConfig, TableViewCreate, TableViewUpdate
from app.schemas.virtual_table import RecordFilter, RecordSort, SchemaUpdate
from app.services.access import TABLE
from app.services.virtual_tables import TableViewService, VirtualTableService
from app.services.virtual_tables.exceptions import SchemaDependencyError
from tests.integration.virtual_table_support import (
    column,
    ctx_for,
    make_org,
    make_user,
    orders_table,
)

pytestmark = pytest.mark.anyio


class _FakeDbApiError(Exception):
    """Stands in for the asyncpg exception `IntegrityError.orig` wraps.

    asyncpg's own `PostgresError` subclasses carry `constraint_name` from the
    server's diagnostics, which is exactly what the service inspects to tell a
    genuine name clash from some other constraint reaching the same `except`.
    """

    def __init__(self, constraint_name: str) -> None:
        super().__init__(f"constraint {constraint_name!r} violated")
        self.constraint_name = constraint_name


async def _setup(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    tables = VirtualTableService(db)
    views = TableViewService(db)
    ctx = ctx_for(owner, org)
    table = await orders_table(tables, ctx)
    return views, tables, ctx, owner, org, table


async def test_a_view_is_created_and_read_back(db):
    views, _tables, ctx, _owner, _org, table = await _setup(db)

    created = await views.create_view(
        ctx,
        table.id,
        TableViewCreate(name="Open orders", kind="table", config=TableViewConfig()),
    )

    assert created.name == "Open orders"
    assert created.kind == "table"
    assert created.visibility == "private"
    assert created.can_manage is True
    fetched = await views.get_view(ctx, table.id, created.id)
    assert fetched == created


async def test_two_views_of_the_same_name_under_one_table_are_refused(db):
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))

    with pytest.raises(AlreadyExistsError):
        await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="kanban"))


async def test_a_duplicate_name_racing_past_the_check_is_still_a_409(db, monkeypatch):
    # The get-by-name check above is not atomic: two concurrent creates of the
    # same name both pass it, and `UniqueConstraint(table_id, owner_user_id,
    # name)` refuses the second insert. That `IntegrityError` must become the
    # same 409 the check raises, not an unhandled 500.
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    monkeypatch.setattr(
        table_view_repo,
        "create",
        AsyncMock(
            side_effect=IntegrityError("insert", {}, _FakeDbApiError("uq_table_view_owner_name"))
        ),
    )

    with pytest.raises(AlreadyExistsError):
        await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))


async def test_a_different_constraint_violation_on_create_is_not_mistaken_for_a_name_clash(
    db, monkeypatch
):
    # A create that hits some other constraint must not be reported as "this
    # name is taken" just because it reached the same `except IntegrityError`.
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    monkeypatch.setattr(
        table_view_repo,
        "create",
        AsyncMock(
            side_effect=IntegrityError("insert", {}, _FakeDbApiError("table_views_org_table_fkey"))
        ),
    )

    with pytest.raises(IntegrityError):
        await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))


async def test_a_duplicate_rename_racing_past_the_check_is_still_a_409(db, monkeypatch):
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    view = await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))
    monkeypatch.setattr(
        table_view_repo,
        "update",
        AsyncMock(
            side_effect=IntegrityError("update", {}, _FakeDbApiError("uq_table_view_owner_name"))
        ),
    )

    with pytest.raises(AlreadyExistsError):
        await views.update_view(ctx, table.id, view.id, TableViewUpdate(name="Taken"))


async def test_an_integrity_error_on_a_non_rename_update_is_not_mistaken_for_a_name_clash(
    db, monkeypatch
):
    # Only a concurrent rename can legitimately hit the unique constraint here;
    # translating every `IntegrityError` into "name already exists" would
    # misreport a different failure as one about a name this caller never
    # asked to change.
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    view = await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))
    monkeypatch.setattr(
        table_view_repo,
        "update",
        AsyncMock(
            side_effect=IntegrityError("update", {}, _FakeDbApiError("uq_table_view_owner_name"))
        ),
    )

    with pytest.raises(IntegrityError):
        await views.update_view(ctx, table.id, view.id, TableViewUpdate(visibility="shared"))


async def test_a_different_constraint_violation_on_a_rename_is_not_mistaken_for_a_name_clash(
    db, monkeypatch
):
    # A rename that hits some other constraint - the organization/table
    # foreign key, say - is not a name clash just because a name changed in
    # the same request. Only the constraint the check itself guards against
    # (`uq_table_view_owner_name`) may be translated into the 409.
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    view = await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))
    monkeypatch.setattr(
        table_view_repo,
        "update",
        AsyncMock(
            side_effect=IntegrityError("update", {}, _FakeDbApiError("table_views_org_table_fkey"))
        ),
    )

    with pytest.raises(IntegrityError):
        await views.update_view(ctx, table.id, view.id, TableViewUpdate(name="Renamed"))


async def test_creating_a_view_needs_table_edit_not_merely_view(db):
    views, _tables, _ctx, _owner, org, table = await _setup(db)
    colleague = await make_user(db)
    viewer_ctx = ctx_for(colleague, org, "viewer")
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.READ,
    )

    with pytest.raises(NotFoundError):
        await views.create_view(viewer_ctx, table.id, TableViewCreate(name="Nope", kind="table"))


async def test_a_private_view_is_invisible_to_a_colleague_and_a_shared_one_is_not(db):
    views, _tables, ctx, owner, org, table = await _setup(db)
    colleague = await make_user(db)
    colleague_ctx = ctx_for(colleague, org, "member")
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.EDIT,
    )
    private_view = await views.create_view(
        ctx, table.id, TableViewCreate(name="Private", kind="table")
    )
    shared_view = await views.create_view(
        ctx, table.id, TableViewCreate(name="Shared", kind="list", visibility="shared")
    )

    listing = await views.list_views(colleague_ctx, table.id)
    assert [item.id for item in listing.items] == [shared_view.id]
    with pytest.raises(NotFoundError):
        await views.get_view(colleague_ctx, table.id, private_view.id)
    seen_shared = await views.get_view(colleague_ctx, table.id, shared_view.id)
    assert seen_shared.can_manage is False


async def test_only_the_owner_or_an_all_scope_caller_may_change_or_delete_a_view(db):
    views, _tables, ctx, owner, org, table = await _setup(db)
    colleague = await make_user(db)
    colleague_ctx = ctx_for(colleague, org, "member")
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.EDIT,
    )
    shared_view = await views.create_view(
        ctx, table.id, TableViewCreate(name="Shared", kind="list", visibility="shared")
    )

    # The colleague can see it (it is shared) but does not own it and holds no
    # `tables:edit` scope of `ALL` - refused as a 404, the same as a private view.
    with pytest.raises(NotFoundError):
        await views.update_view(
            colleague_ctx, table.id, shared_view.id, TableViewUpdate(name="Mine now")
        )
    with pytest.raises(NotFoundError):
        await views.delete_view(colleague_ctx, table.id, shared_view.id)

    # An admin (`tables:edit` = ALL) may manage it without being its owner.
    admin = await make_user(db)
    admin_ctx = ctx_for(admin, org, "admin")
    renamed = await views.update_view(
        admin_ctx, table.id, shared_view.id, TableViewUpdate(name="Renamed")
    )
    assert renamed.name == "Renamed"
    await views.delete_view(admin_ctx, table.id, shared_view.id)
    with pytest.raises(NotFoundError):
        await views.get_view(ctx, table.id, shared_view.id)


async def test_an_all_scope_caller_can_delete_a_colleagues_private_view(db):
    # `_manageable_view` must not route through `_visible_view`: that hides a
    # private view from anyone but its owner, which would also hide it from an
    # admin `_can_manage` already says may manage it - leaving no one able to
    # delete an orphaned private view (say, its owner left the organization)
    # that still blocks archiving a column it references.
    views, _tables, ctx, _owner, org, table = await _setup(db)
    private_view = await views.create_view(
        ctx, table.id, TableViewCreate(name="Mine", kind="table", visibility="private")
    )

    admin = await make_user(db)
    admin_ctx = ctx_for(admin, org, "admin")
    renamed = await views.update_view(
        admin_ctx, table.id, private_view.id, TableViewUpdate(name="Reclaimed")
    )
    assert renamed.name == "Reclaimed"
    await views.delete_view(admin_ctx, table.id, private_view.id)
    with pytest.raises(NotFoundError):
        await views.get_view(ctx, table.id, private_view.id)


async def test_renaming_to_a_taken_name_is_refused_and_a_no_op_rename_is_not(db):
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    await views.create_view(ctx, table.id, TableViewCreate(name="Taken", kind="table"))
    view = await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))

    with pytest.raises(AlreadyExistsError):
        await views.update_view(ctx, table.id, view.id, TableViewUpdate(name="Taken"))

    same = await views.update_view(ctx, table.id, view.id, TableViewUpdate(name="Mine"))
    assert same.name == "Mine"


async def test_updating_config_and_visibility_persists_and_reads_back(db):
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    status_id = next(c.id for c in table.columns if c.label == "Status")
    view = await views.create_view(ctx, table.id, TableViewCreate(name="Board", kind="kanban"))

    updated = await views.update_view(
        ctx,
        table.id,
        view.id,
        TableViewUpdate(
            visibility="shared",
            config=TableViewConfig(
                filters=[RecordFilter(column_id=status_id, op="eq", value=str(status_id))],
                sort=RecordSort(by="created_at", direction="desc"),
                group_by=status_id,
            ),
        ),
    )

    assert updated.visibility == "shared"
    assert updated.config.group_by == status_id
    assert updated.config.filters[0].column_id == status_id
    fetched = await views.get_view(ctx, table.id, view.id)
    assert fetched.config.sort.direction == "desc"


async def test_an_update_with_nothing_set_changes_nothing(db):
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    view = await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))

    same = await views.update_view(ctx, table.id, view.id, TableViewUpdate())

    assert same == view


async def test_listing_can_be_narrowed_to_one_kind(db):
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    await views.create_view(ctx, table.id, TableViewCreate(name="Grid", kind="table"))
    await views.create_view(ctx, table.id, TableViewCreate(name="Board", kind="kanban"))

    only_kanban = await views.list_views(ctx, table.id, kind="kanban")

    assert [item.name for item in only_kanban.items] == ["Board"]


@pytest.mark.security
async def test_another_organizations_table_has_no_views_to_see(db):
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    await views.create_view(ctx, table.id, TableViewCreate(name="Mine", kind="table"))
    outsider = await make_user(db)
    other_org = await make_org(db, owner=outsider)
    intruder = ctx_for(outsider, other_org, "owner")

    with pytest.raises(NotFoundError):
        await views.list_views(intruder, table.id)


async def test_archiving_a_column_a_view_still_uses_is_refused(db):
    views, tables, ctx, _owner, _org, table = await _setup(db)
    status_id = next(c.id for c in table.columns if c.label == "Status")
    await views.create_view(
        ctx,
        table.id,
        TableViewCreate(
            name="Board",
            kind="kanban",
            config=TableViewConfig(group_by=status_id),
        ),
    )

    with pytest.raises(SchemaDependencyError) as raised:
        await tables.update_schema(
            ctx,
            table.id,
            SchemaUpdate(
                expected_version=1,
                columns=[
                    column(c.label, c.type, id=c.id) for c in table.columns if c.label != "Status"
                ],
            ),
        )
    dependents = raised.value.details["dependents"]
    assert {item["kind"] for item in dependents} == {"table_view"}


async def test_archiving_a_column_no_view_uses_is_not_refused(db):
    views, tables, ctx, _owner, _org, table = await _setup(db)
    status_id = next(c.id for c in table.columns if c.label == "Status")
    await views.create_view(
        ctx,
        table.id,
        TableViewCreate(name="Board", kind="kanban", config=TableViewConfig(group_by=status_id)),
    )
    quantity_id = next(c.id for c in table.columns if c.label == "Quantity")

    changed = await tables.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=1,
            columns=[
                column(c.label, c.type, id=c.id) for c in table.columns if c.label != "Quantity"
            ],
        ),
    )

    archived = next(c for c in changed.columns if c.id == quantity_id)
    assert archived.archived is True


async def test_archiving_the_whole_table_does_not_ask_the_view_checker(db):
    views, tables, ctx, _owner, _org, table = await _setup(db)
    status_id = next(c.id for c in table.columns if c.label == "Status")
    await views.create_view(
        ctx,
        table.id,
        TableViewCreate(name="Board", kind="kanban", config=TableViewConfig(group_by=status_id)),
    )

    archived = await tables.archive_table(ctx, table.id)

    assert archived.archived_at is not None


async def _builders_table_and_an_editing_member(db):
    """A table a builder owns, and a member holding an edit grant on it.

    The builder's `tables:edit` scope is `SHARED`, so the member's private views
    are none of theirs - the shape that let a lower principal block a higher one.
    """
    org_owner = await make_user(db)
    org = await make_org(db, owner=org_owner)
    tables = VirtualTableService(db)
    views = TableViewService(db)
    builder = await make_user(db)
    builder_ctx = ctx_for(builder, org, "builder")
    table = await orders_table(tables, builder_ctx)
    member = await make_user(db)
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=member.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.EDIT,
    )
    return views, tables, builder_ctx, ctx_for(member, org, "member"), table


def _without(table, label: str) -> SchemaUpdate:
    """The schema update that archives the column `label`, leaving the rest as they are."""
    return SchemaUpdate(
        expected_version=table.schema_version,
        columns=[column(c.label, c.type, id=c.id) for c in table.columns if c.label != label],
    )


@pytest.mark.security
async def test_another_members_private_view_neither_blocks_a_column_archive_nor_is_named(db):
    """The archive used to be refused with the private view's id in the details -
    an id `get_view` answers 404 for, naming a row the caller may not know exists,
    and blocking them with no way to see or clear it."""
    views, tables, builder_ctx, member_ctx, table = await _builders_table_and_an_editing_member(db)
    status_id = next(c.id for c in table.columns if c.label == "Status")
    private = await views.create_view(
        member_ctx,
        table.id,
        TableViewCreate(
            name="My board",
            kind="kanban",
            config=TableViewConfig(
                filters=[RecordFilter(column_id=status_id, op="is_null", value=False)],
                sort=RecordSort(by=str(status_id), direction="desc"),
                group_by=status_id,
            ),
        ),
    )

    changed = await tables.update_schema(builder_ctx, table.id, _without(table, "Status"))

    assert next(c for c in changed.columns if c.id == status_id).archived is True
    # Its owner reads it with everything that named the archived column dropped.
    after = await views.get_view(member_ctx, table.id, private.id)
    assert after.config.filters == []
    assert after.config.sort == RecordSort()
    assert after.config.group_by is None


async def test_a_view_the_caller_can_see_still_blocks_a_column_archive_and_is_named(db):
    views, tables, builder_ctx, member_ctx, table = await _builders_table_and_an_editing_member(db)
    status_id = next(c.id for c in table.columns if c.label == "Status")
    shared = await views.create_view(
        member_ctx,
        table.id,
        TableViewCreate(
            name="Team board",
            kind="kanban",
            visibility="shared",
            config=TableViewConfig(group_by=status_id),
        ),
    )
    own = await views.create_view(
        builder_ctx,
        table.id,
        TableViewCreate(
            name="Mine",
            kind="table",
            config=TableViewConfig(sort=RecordSort(by=str(status_id))),
        ),
    )

    with pytest.raises(SchemaDependencyError) as raised:
        await tables.update_schema(builder_ctx, table.id, _without(table, "Status"))

    dependents = raised.value.details["dependents"]
    assert sorted(item["id"] for item in dependents) == sorted([shared.id, own.id])


async def test_a_view_that_only_shows_a_column_does_not_block_archiving_it(db):
    views, tables, ctx, _owner, _org, table = await _setup(db)
    customer_id = next(c.id for c in table.columns if c.label == "Customer")
    status_id = next(c.id for c in table.columns if c.label == "Status")
    view = await views.create_view(
        ctx,
        table.id,
        TableViewCreate(
            name="Narrow",
            kind="table",
            config=TableViewConfig(visible_columns=[customer_id, status_id]),
        ),
    )

    await tables.update_schema(ctx, table.id, _without(table, "Status"))

    listed = await views.list_views(ctx, table.id)
    assert [item.config.visible_columns for item in listed.items if item.id == view.id] == [
        [customer_id]
    ]


@pytest.mark.security
async def test_a_view_owner_who_lost_edit_access_cannot_reshape_or_reshare_it_but_can_delete_it(
    db,
):
    """Creating a view needs `tables:edit`; changing one used to need only
    `tables:view`, so an owner downgraded to read could still publish it to every
    reader of the table."""
    views, _tables, _builder_ctx, member_ctx, table = await _builders_table_and_an_editing_member(
        db
    )
    view = await views.create_view(member_ctx, table.id, TableViewCreate(name="Mine", kind="table"))
    await resource_grant_repo.upsert(
        db,
        organization_id=member_ctx.organization_id,
        subject_user_id=member_ctx.subject_id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.READ,
    )

    with pytest.raises(NotFoundError):
        await views.update_view(
            member_ctx,
            table.id,
            view.id,
            TableViewUpdate(name="Published", visibility="shared"),
        )
    assert (await views.get_view(member_ctx, table.id, view.id)).visibility == "private"
    await views.delete_view(member_ctx, table.id, view.id)
    with pytest.raises(NotFoundError):
        await views.get_view(member_ctx, table.id, view.id)


async def test_listing_views_pages_them_and_counts_them_all(db):
    views, _tables, ctx, _owner, _org, table = await _setup(db)
    for name in ("C", "A", "B"):
        await views.create_view(ctx, table.id, TableViewCreate(name=name, kind="table"))

    first = await views.list_views(ctx, table.id, limit=2)
    rest = await views.list_views(ctx, table.id, skip=2, limit=2)

    assert [item.name for item in first.items] == ["A", "B"]
    assert [item.name for item in rest.items] == ["C"]
    assert first.total == rest.total == 3
