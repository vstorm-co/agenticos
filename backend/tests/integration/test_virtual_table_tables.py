"""Tables and schema versions against a real database.

What matters here is what stored records go through when the schema changes: a
column keeps its id across a rename, nothing is deleted, a type never changes,
and records written under version 1 stay readable and editable under version 3.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.resource_grant import GrantLevel
from app.repositories import resource_grant_repo
from app.schemas.virtual_table import (
    ColumnInput,
    OptionInput,
    RecordCreate,
    RecordUpdate,
    SchemaUpdate,
    TableCreate,
    TableUpdate,
)
from app.services.access import TABLE
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables import dependencies as dependency_hook
from app.services.virtual_tables.dependencies import Dependent
from app.services.virtual_tables.exceptions import (
    ArchivedColumnError,
    InvalidRecordError,
    InvalidSchemaError,
    SchemaDependencyError,
    SchemaVersionConflictError,
    TableArchivedError,
)
from tests.integration.virtual_table_support import (
    cid,
    column,
    ctx_for,
    make_org,
    make_user,
    orders_table,
)

pytestmark = pytest.mark.anyio


async def _setup(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    return VirtualTableService(db), ctx_for(owner, org), owner, org


async def test_a_table_is_created_with_its_first_schema_version_and_audited(db):
    service, ctx, _owner, org = await _setup(db)

    table = await orders_table(service, ctx)

    assert table.schema_version == 1
    assert [item.label for item in table.columns][:2] == ["Customer", "Quantity"]
    assert all(item.id for item in table.columns)
    versions = await service.list_schema_versions(ctx, table.id)
    assert [version.version for version in versions.items] == [1]
    audited = await db.scalars(
        select(AppAdminAuditLog.action).where(AppAdminAuditLog.organization_id == org.id)
    )
    assert "table.created" in list(audited)


@pytest.mark.security
async def test_creating_a_table_needs_the_create_permission(db):
    service, _ctx, owner, org = await _setup(db)

    with pytest.raises(AuthorizationError):
        await service.create_table(ctx_for(owner, org, "viewer"), TableCreate(name="Nope"))
    with pytest.raises(AuthorizationError):
        await service.create_table(AuthContext.anonymous(org.id), TableCreate(name="Nope"))


async def test_a_live_name_is_taken_but_an_archived_one_is_free(db):
    service, ctx, _owner, _org = await _setup(db)
    first = await service.create_table(ctx, TableCreate(name="Orders"))

    with pytest.raises(AlreadyExistsError):
        await service.create_table(ctx, TableCreate(name="Orders"))

    await service.archive_table(ctx, first.id)
    again = await service.create_table(ctx, TableCreate(name="Orders"))
    assert again.id != first.id


async def test_a_rename_is_checked_against_live_names_and_audited(db):
    service, ctx, _owner, _org = await _setup(db)
    await service.create_table(ctx, TableCreate(name="Orders"))
    other = await service.create_table(ctx, TableCreate(name="Invoices"))

    with pytest.raises(AlreadyExistsError):
        await service.update_table(ctx, other.id, TableUpdate(name="Orders"))
    renamed = await service.update_table(ctx, other.id, TableUpdate(name="Bills", description="d"))
    assert (renamed.name, renamed.description) == ("Bills", "d")
    same = await service.update_table(ctx, other.id, TableUpdate(name="Bills"))
    assert same.name == "Bills"


async def test_the_listing_shows_what_the_caller_may_see_and_hides_archived_by_default(db):
    service, ctx, owner, org = await _setup(db)
    mine = await service.create_table(ctx, TableCreate(name="Mine"))
    gone = await service.create_table(ctx, TableCreate(name="Gone"))
    await service.archive_table(ctx, gone.id)
    colleague = await make_user(db)
    stranger = ctx_for(colleague, org, "member")

    assert [item.name for item in (await service.list_tables(ctx)).items] == ["Mine"]
    everything = await service.list_tables(ctx, include_archived=True)
    assert everything.total == 2
    assert (await service.list_tables(ctx, search="min")).total == 1
    assert (await service.list_tables(stranger)).items == []

    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=mine.id,
        level=GrantLevel.READ,
    )
    shared = await service.list_tables(stranger)
    assert [item.id for item in shared.items] == [mine.id]
    assert owner.id


@pytest.mark.security
async def test_a_private_table_is_a_404_to_another_member_but_a_grant_opens_it(db):
    service, ctx, _owner, org = await _setup(db)
    table = await service.create_table(ctx, TableCreate(name="Private"))
    colleague = await make_user(db)
    other = ctx_for(colleague, org, "member")

    with pytest.raises(NotFoundError):
        await service.describe_table(other, table.id)
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.READ,
    )
    assert (await service.describe_table(other, table.id)).name == "Private"
    with pytest.raises(NotFoundError):
        await service.update_table(other, table.id, TableUpdate(name="Mine now"))


async def test_a_rename_keeps_the_column_id_and_the_records_keep_their_values(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text")])
    )
    name_id = table.columns[0].id
    written = await service.create_record(ctx, table.id, RecordCreate(values={str(name_id): "Ada"}))

    changed = await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(expected_version=1, columns=[column("Full name", "text", id=name_id)]),
    )

    assert changed.schema_version == 2
    assert changed.columns[0].id == name_id
    assert changed.columns[0].label == "Full name"
    assert (await service.get_record(ctx, table.id, written.record.id)).values == {
        str(name_id): "Ada"
    }
    versions = await service.list_schema_versions(ctx, table.id)
    assert [version.columns[0].label for version in versions.items] == ["Name", "Full name"]


@pytest.mark.security
async def test_a_column_left_out_is_archived_not_deleted_and_can_no_longer_be_written(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text"), column("Age", "integer")])
    )
    name_id, age_id = table.columns[0].id, table.columns[1].id
    written = await service.create_record(
        ctx, table.id, RecordCreate(values={str(name_id): "Ada", str(age_id): 36})
    )

    changed = await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(expected_version=1, columns=[column("Name", "text", id=name_id)]),
    )

    archived = next(item for item in changed.columns if item.id == age_id)
    assert archived.archived is True
    assert (await service.get_record(ctx, table.id, written.record.id)).values[str(age_id)] == 36
    with pytest.raises(ArchivedColumnError) as raised:
        await service.update_record(
            ctx,
            table.id,
            written.record.id,
            RecordUpdate(expected_revision=1, values={str(age_id): 37}),
        )
    assert raised.value.details is not None
    assert raised.value.details["column_id"] == str(age_id)


@pytest.mark.security
async def test_a_schema_change_refuses_what_would_break_stored_values(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text"), column("Age", "integer")])
    )
    name_id, age_id = table.columns[0].id, table.columns[1].id
    keep = [column("Name", "text", id=name_id), column("Age", "integer", id=age_id)]
    two_options = [OptionInput(label="a"), OptionInput(label="a")]
    cases = [
        ([keep[0], column("Age", "text", id=age_id)], "columns.1.type"),
        ([*keep, column("Name", "text")], "columns"),
        ([*keep, column("Boss", "text", nullable=False)], "columns.2.default"),
        ([*keep, column("Bad", "integer", default="x")], "columns.2.default"),
        ([*keep, column("Note", "text", options=[OptionInput(label="a")])], "columns.2.options"),
        ([*keep, column("Ghost", "text", id=uuid.uuid4())], "columns.2.id"),
        ([*keep, keep[0]], "columns.2.id"),
        ([*keep, column("Pick", "single_select", options=two_options)], "columns.2.options"),
        (
            [
                *keep,
                column("Pick", "single_select", options=[OptionInput(id=uuid.uuid4(), label="a")]),
            ],
            "columns.2.options.0.id",
        ),
    ]
    for columns, field in cases:
        with pytest.raises(InvalidSchemaError) as raised:
            await service.update_schema(
                ctx, table.id, SchemaUpdate(expected_version=1, columns=columns)
            )
        assert raised.value.details is not None
        assert raised.value.details["fields"][0]["field"] == field
    assert (await service.describe_table(ctx, table.id)).schema_version == 1


async def test_options_are_archived_when_left_out_and_keep_their_ids(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx,
        TableCreate(
            name="Tickets",
            columns=[
                column(
                    "Status",
                    "single_select",
                    options=[OptionInput(label="Open"), OptionInput(label="Closed")],
                )
            ],
        ),
    )
    status = table.columns[0]
    open_, closed = status.options

    changed = await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=1,
            columns=[
                column(
                    "Status",
                    "single_select",
                    id=status.id,
                    options=[
                        OptionInput(id=open_.id, label="Opened"),
                        OptionInput(label="Blocked"),
                    ],
                )
            ],
        ),
    )

    options = {option.label: option for option in changed.columns[0].options}
    assert options["Opened"].id == open_.id
    assert options["Closed"].id == closed.id and options["Closed"].archived
    assert options["Blocked"].archived is False


@pytest.mark.security
async def test_a_stale_schema_version_is_a_conflict_and_nothing_changes(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(ctx, TableCreate(name="People"))
    await service.update_schema(
        ctx, table.id, SchemaUpdate(expected_version=1, columns=[column("Name", "text")])
    )

    with pytest.raises(SchemaVersionConflictError) as raised:
        await service.update_schema(
            ctx, table.id, SchemaUpdate(expected_version=1, columns=[column("Other", "text")])
        )
    assert raised.value.details == {"expected_version": 1, "current_version": 2}


@pytest.mark.security
async def test_a_column_with_empty_cells_cannot_become_required(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text")])
    )
    name_id = table.columns[0].id
    await service.create_record(ctx, table.id, RecordCreate(values={}))

    with pytest.raises(InvalidSchemaError, match="no value"):
        await service.update_schema(
            ctx,
            table.id,
            SchemaUpdate(
                expected_version=1, columns=[column("Name", "text", id=name_id, nullable=False)]
            ),
        )


async def test_a_new_required_column_with_a_default_fills_old_records_when_they_are_edited(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text")])
    )
    name_id = table.columns[0].id
    old = await service.create_record(ctx, table.id, RecordCreate(values={str(name_id): "Ada"}))

    changed = await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=1,
            columns=[
                column("Name", "text", id=name_id),
                column("Country", "text", nullable=False, default="PL"),
            ],
        ),
    )
    country_id = str(changed.columns[1].id)

    assert country_id not in (await service.get_record(ctx, table.id, old.record.id)).values
    edited = await service.update_record(
        ctx,
        table.id,
        old.record.id,
        RecordUpdate(expected_revision=1, values={str(name_id): "Grace"}),
    )
    assert edited.record.values == {str(name_id): "Grace", country_id: "PL"}
    assert edited.record.schema_version == 2
    new = await service.create_record(ctx, table.id, RecordCreate(values={}))
    assert new.record.values == {country_id: "PL"}


@pytest.mark.security
async def test_an_archived_table_keeps_its_records_readable_and_refuses_every_write(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text")])
    )
    name_id = str(table.columns[0].id)
    written = await service.create_record(ctx, table.id, RecordCreate(values={name_id: "Ada"}))

    archived = await service.archive_table(ctx, table.id)
    again = await service.archive_table(ctx, table.id)

    assert archived.archived_at is not None and again.archived_at == archived.archived_at
    assert (await service.get_record(ctx, table.id, written.record.id)).values == {name_id: "Ada"}
    with pytest.raises(TableArchivedError):
        await service.create_record(ctx, table.id, RecordCreate(values={}))
    with pytest.raises(TableArchivedError):
        await service.update_record(
            ctx, table.id, written.record.id, RecordUpdate(expected_revision=1, values={})
        )
    with pytest.raises(TableArchivedError):
        await service.delete_record(ctx, table.id, written.record.id, expected_revision=1)
    with pytest.raises(TableArchivedError):
        await service.update_table(ctx, table.id, TableUpdate(name="Renamed"))
    with pytest.raises(TableArchivedError):
        await service.update_schema(ctx, table.id, SchemaUpdate(expected_version=1, columns=[]))


@pytest.mark.security
async def test_a_registered_dependency_blocks_archiving_and_dropping_a_column(db, monkeypatch):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text"), column("Age", "integer")])
    )
    workflow = uuid.uuid4()
    seen: list[frozenset[uuid.UUID] | None] = []

    async def checker(db, *, organization_id, table_id, column_ids):
        seen.append(column_ids)
        return [Dependent(kind="workflow", id=workflow)]

    monkeypatch.setattr(dependency_hook, "_checkers", [checker])

    with pytest.raises(SchemaDependencyError) as raised:
        await service.archive_table(ctx, table.id)
    assert raised.value.details == {"dependents": [{"kind": "workflow", "id": workflow}]}
    with pytest.raises(SchemaDependencyError):
        await service.update_schema(
            ctx,
            table.id,
            SchemaUpdate(
                expected_version=1, columns=[column("Name", "text", id=table.columns[0].id)]
            ),
        )
    assert seen == [None, frozenset({table.columns[1].id})]
    # A change that archives nothing does not ask.
    await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=1,
            columns=[*(ColumnInput(**c.model_dump(exclude={"options"})) for c in table.columns)],
        ),
    )
    assert len(seen) == 2


@pytest.mark.security
async def test_another_organizations_table_does_not_exist(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await orders_table(service, ctx)
    outsider = await make_user(db)
    other_org = await make_org(db, owner=outsider)
    intruder = ctx_for(outsider, other_org, "owner")

    for call in (
        service.describe_table(intruder, table.id),
        service.archive_table(intruder, table.id),
        service.list_schema_versions(intruder, table.id),
        service.update_schema(intruder, table.id, SchemaUpdate(expected_version=1, columns=[])),
    ):
        with pytest.raises(NotFoundError):
            await call
    assert (await service.list_tables(intruder)).total == 0
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AppAdminAuditLog)
            .where(AppAdminAuditLog.organization_id == other_org.id)
        )
        == 0
    )
    assert cid(table, "Customer")


async def test_a_column_made_required_after_every_record_has_a_value_rejects_new_ones_without(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text")])
    )
    name_id = table.columns[0].id
    await service.create_record(ctx, table.id, RecordCreate(values={str(name_id): "Ada"}))

    await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=1, columns=[column("Name", "text", id=name_id, nullable=False)]
        ),
    )

    with pytest.raises(InvalidRecordError) as raised:
        await service.create_record(ctx, table.id, RecordCreate(values={}))
    assert raised.value.details["fields"] == [
        {"field": f"values.{name_id}", "message": "This column is required"}
    ]
    with pytest.raises(InvalidRecordError):
        await service.create_record(ctx, table.id, RecordCreate(values={str(name_id): None}))


@pytest.mark.security
async def test_a_required_column_cannot_come_back_from_the_archive_beside_records_that_lack_it(db):
    """Records written while it was archived could not hold a value, so it would be violated."""
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx, TableCreate(name="People", columns=[column("Name", "text")])
    )
    name = table.columns[0].id
    await service.create_record(ctx, table.id, RecordCreate(values={str(name): "Ada"}))
    await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(expected_version=1, columns=[column("Name", "text", id=name, nullable=False)]),
    )
    await service.update_schema(ctx, table.id, SchemaUpdate(expected_version=2, columns=[]))
    await service.create_record(ctx, table.id, RecordCreate(values={}))

    with pytest.raises(InvalidSchemaError) as raised:
        await service.update_schema(
            ctx,
            table.id,
            SchemaUpdate(
                expected_version=3, columns=[column("Name", "text", id=name, nullable=False)]
            ),
        )

    assert raised.value.details["fields"][0]["field"] == "columns.0.nullable"
    assert (await service.describe_table(ctx, table.id)).schema_version == 3


async def test_a_required_column_with_a_default_can_come_back_and_fills_on_the_next_edit(db):
    service, ctx, _owner, _org = await _setup(db)
    table = await service.create_table(
        ctx,
        TableCreate(
            name="People",
            columns=[column("Country", "text", nullable=False, default="PL")],
        ),
    )
    country = table.columns[0].id
    await service.update_schema(ctx, table.id, SchemaUpdate(expected_version=1, columns=[]))
    other = await service.update_schema(
        ctx, table.id, SchemaUpdate(expected_version=2, columns=[column("Note", "text")])
    )
    written = await service.create_record(
        ctx, table.id, RecordCreate(values={str(other.columns[0].id): "x"})
    )
    assert str(country) not in written.record.values

    restored = await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=3,
            columns=[
                column("Note", "text", id=other.columns[0].id),
                column("Country", "text", id=country, nullable=False, default="PL"),
            ],
        ),
    )
    edited = await service.update_record(
        ctx,
        table.id,
        written.record.id,
        RecordUpdate(expected_revision=1, values={str(other.columns[0].id): "y"}),
    )

    assert restored.schema_version == 4
    assert edited.record.values[str(country)] == "PL"
