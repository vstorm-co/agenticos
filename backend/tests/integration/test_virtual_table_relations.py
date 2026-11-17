"""Ordered links, constrained endpoints, retained evidence and read-only backlinks."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import NotFoundError
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import GrantLevel
from app.db.models.virtual_table import VirtualTableRecord, VirtualTableRecordHistory
from app.db.models.virtual_table_relation import (
    VirtualTableLinkEvidence,
    VirtualTableRecordLink,
    VirtualTableRelation,
)
from app.repositories import resource_grant_repo, virtual_table_repo
from app.repositories import virtual_table_relation as relation_repo
from app.schemas.virtual_table import (
    ColumnInput,
    RecordBatchCreate,
    RecordCreate,
    RecordFilter,
    RecordLinkChange,
    RecordQuery,
    RecordUpdate,
    RowPolicyUpdate,
    SchemaUpdate,
    TableCreate,
)
from app.schemas.virtual_table_relation import BacklinkQuery
from app.services.access import TABLE
from app.services.virtual_tables import ReadDeadline, VirtualTableService
from app.services.virtual_tables.exceptions import (
    IdempotencyKeyReuseError,
    InvalidRecordError,
    InvalidSchemaError,
)
from app.services.virtual_tables.receipts import payload_hash
from tests.integration.virtual_table_support import (
    bound_view,
    cid,
    column,
    ctx_for,
    make_org,
    make_user,
    shaper,
)

pytestmark = pytest.mark.anyio


async def _setup(db, *, limit=None):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    target = await service.create_table(
        ctx,
        TableCreate(
            name="Customers",
            visibility="org",
            columns=[column("Name", "text"), column("Assignee", "user")],
        ),
    )
    source = await service.create_table(
        ctx,
        TableCreate(
            name="Orders",
            visibility="org",
            columns=[
                column("Name", "text"),
                column("Assignee", "user"),
                column("Customers", "link", link_table_id=target.id, link_limit=limit),
            ],
        ),
    )
    targets = []
    for label in ("First", "Second", "Third"):
        result = await service.create_record(
            ctx, target.id, RecordCreate(values={cid(target, "Name"): label})
        )
        targets.append(result.record.id)
    return service, ctx, org, owner, source, target, targets


def _columns(table, **link_changes):
    return [
        ColumnInput(
            **{
                **item.model_dump(exclude={"revision"}),
                **(link_changes if item.type == "link" else {}),
            }
        )
        for item in table.columns
    ]


async def _edges(db, source_id):
    return list(
        await db.scalars(
            select(VirtualTableRecordLink)
            .where(VirtualTableRecordLink.source_record_id == source_id)
            .order_by(VirtualTableRecordLink.position)
        )
    )


async def test_ordered_edges_and_replayed_snapshot_keep_the_source_revision(db):
    service, ctx, org, _owner, source, _target, targets = await _setup(db)
    key = cid(source, "Customers")
    body = RecordCreate(values={key: [str(targets[2]), str(targets[0])]})
    first = await service.create_record(ctx, source.id, body, operation_key="original")
    edges = await _edges(db, first.record.id)
    assert [(edge.position, edge.target_record_id) for edge in edges] == [
        (0, targets[2]),
        (1, targets[0]),
    ]
    definitions = await relation_repo.definitions(
        db, organization_id=org.id, source_table_id=source.id
    )
    assert definitions[0].column_id == UUID(key)
    changed = await service.update_record(
        ctx,
        source.id,
        first.record.id,
        RecordUpdate(
            expected_revision=1,
            values={key: [str(targets[1])]},
        ),
    )
    assert changed.record.values[key] == [str(targets[1])]
    retry = await service.create_record(ctx, source.id, body, operation_key="original")
    assert retry.replayed
    assert retry.record.revision == 1
    assert retry.record.values[key] == first.record.values[key]
    assert [item.id for item in retry.record.links[key]] == [targets[2], targets[0]]
    assert [edge.target_record_id for edge in await _edges(db, first.record.id)] == [targets[1]]


@pytest.mark.security
async def test_replaying_a_create_after_deletion_does_not_restore_the_record(db):
    service, ctx, org, _owner, source, _target, targets = await _setup(db)
    key = cid(source, "Customers")
    body = RecordCreate(values={key: [str(targets[0])]})
    first = await service.create_record(ctx, source.id, body, operation_key="deleted-original")
    await service.delete_record(ctx, source.id, first.record.id, expected_revision=1)

    with pytest.raises(NotFoundError) as refused:
        await service.create_record(ctx, source.id, body, operation_key="deleted-original")

    assert refused.value.message == "Record not found"
    assert refused.value.details == {"table_id": source.id}
    assert (
        await virtual_table_repo.get_record(
            db, first.record.id, table_id=source.id, organization_id=org.id
        )
        is None
    )
    assert await _edges(db, first.record.id) == []


@pytest.mark.security
@pytest.mark.parametrize(
    "wrong",
    [
        "organization",
        "source_table",
        "target_table",
        "source_record",
        "target_record",
        "column",
        "duplicate_target",
        "duplicate_position",
        "position",
        "max_links",
    ],
)
async def test_database_rejects_edges_outside_the_declared_relationship(db, wrong):
    service, ctx, org, _owner, source, target, targets = await _setup(db, limit=1)
    written = await service.create_record(
        ctx,
        source.id,
        RecordCreate(
            values={cid(source, "Customers"): [str(targets[0])]},
        ),
    )
    row = {
        "organization_id": org.id,
        "source_table_id": source.id,
        "column_id": UUID(cid(source, "Customers")),
        "source_record_id": written.record.id,
        "target_table_id": target.id,
        "target_record_id": targets[1],
        "position": 0,
        "max_links": 1,
    }
    changes = {
        "organization": {"organization_id": uuid4()},
        "source_table": {"source_table_id": target.id},
        "target_table": {"target_table_id": source.id},
        "source_record": {"source_record_id": targets[0]},
        "target_record": {"target_record_id": written.record.id},
        "column": {"column_id": uuid4()},
        "duplicate_target": {"target_record_id": targets[0]},
        "duplicate_position": {},
        "position": {"position": 1},
        "max_links": {"max_links": 100, "position": 1},
    }
    if wrong not in {"duplicate_target", "duplicate_position"}:
        await db.execute(
            delete(VirtualTableRecordLink).where(
                VirtualTableRecordLink.source_record_id == written.record.id
            )
        )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(insert(VirtualTableRecordLink).values(**{**row, **changes[wrong]}))
    expected = [targets[0]] if wrong in {"duplicate_target", "duplicate_position"} else []
    assert [edge.target_record_id for edge in await _edges(db, written.record.id)] == expected


async def test_single_destination_is_validated_and_narrowing_needs_existing_rows_repaired(db):
    service, ctx, org, _owner, source, _target, targets = await _setup(db)
    key = cid(source, "Customers")
    written = await service.create_record(
        ctx,
        source.id,
        RecordCreate(
            values={key: [str(targets[0]), str(targets[1])]},
        ),
    )
    with pytest.raises(InvalidSchemaError):
        await service.update_schema(
            ctx,
            source.id,
            SchemaUpdate(
                expected_version=source.schema_version,
                columns=_columns(source, link_limit=1),
            ),
        )
    await service.update_record(
        ctx,
        source.id,
        written.record.id,
        RecordUpdate(
            expected_revision=1,
            values={key: [str(targets[0])]},
        ),
    )
    single = await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=source.schema_version,
            columns=_columns(source, link_limit=1),
        ),
    )
    assert next(item for item in single.columns if item.type == "link").link_limit == 1
    assert (await _edges(db, written.record.id))[0].max_links == 1
    # An old client omitting the new optional field cannot widen the relationship.
    legacy = await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=single.schema_version,
            columns=_columns(single, link_limit=None),
        ),
    )
    assert next(item for item in legacy.columns if item.type == "link").link_limit == 1
    with pytest.raises(InvalidRecordError):
        await service.create_record(
            ctx,
            source.id,
            RecordCreate(
                values={key: [str(targets[0]), str(targets[1])]},
            ),
        )
    definition = (
        await relation_repo.definitions(db, organization_id=org.id, source_table_id=source.id)
    )[0]
    assert definition.max_links == 1


async def test_archive_restore_retains_edges_and_backlinks_are_read_only(db):
    service, ctx, org, _owner, source, target, targets = await _setup(db)
    key = cid(source, "Customers")
    written = await service.create_record(
        ctx, source.id, RecordCreate(values={key: [str(targets[0])]})
    )
    query = BacklinkQuery(source_table_id=source.id, column_id=UUID(key))
    result = await service.list_backlinks(ctx, target.id, targets[0], query)
    assert [row.id for row in result.items] == [written.record.id]
    archived = await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=source.schema_version,
            columns=_columns(source, archived=True),
        ),
    )
    definition = (
        await relation_repo.definitions(db, organization_id=org.id, source_table_id=source.id)
    )[0]
    assert definition.archived
    assert len(await _edges(db, written.record.id)) == 1
    with pytest.raises(NotFoundError):
        await service.list_backlinks(ctx, target.id, targets[0], query)
    await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=archived.schema_version,
            columns=_columns(archived, archived=False),
        ),
    )
    restored = await service.list_backlinks(ctx, target.id, targets[0], query)
    assert restored.items[0].revision == 1
    assert restored.items[0].values[key] == [str(targets[0])]


async def test_deleting_a_target_cascades_only_edges_and_current_reads_use_them(db):
    service, ctx, org, _owner, source, _target, targets = await _setup(db)
    key = cid(source, "Customers")
    written = await service.create_record(
        ctx, source.id, RecordCreate(values={key: [str(targets[0])]})
    )
    await db.execute(delete(VirtualTableRecord).where(VirtualTableRecord.id == targets[0]))
    assert await _edges(db, written.record.id) == []
    stored = await virtual_table_repo.get_record(
        db, written.record.id, table_id=source.id, organization_id=org.id
    )
    assert stored.revision == 1
    assert stored.values[key] == [str(targets[0])]
    read = await service.get_record(ctx, source.id, written.record.id)
    assert read.values[key] == []
    assert read.links[key] == []


@pytest.mark.security
async def test_backlink_paging_requires_read_access_to_both_endpoints(db):
    service, ctx, org, owner, source, target, targets = await _setup(db)
    member = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=member.id, role="member"))
    await db.flush()
    viewer = ctx_for(member, org, "member")
    key = cid(source, "Customers")
    visible = []
    for index, user in enumerate((owner, member, owner, member)):
        result = await service.create_record(
            ctx,
            source.id,
            RecordCreate(
                values={
                    cid(source, "Name"): str(index),
                    cid(source, "Assignee"): str(user.id),
                    key: [str(targets[0])],
                }
            ),
        )
        if user.id == member.id:
            visible.append(result.record.id)
    source_model = await virtual_table_repo.get_table(db, source.id, organization_id=org.id)
    source_model.row_policy = {
        "rule": "assignee",
        "view_column_id": cid(source, "Assignee"),
        "edit_column_id": cid(source, "Assignee"),
    }
    await db.flush()
    query = BacklinkQuery(source_table_id=source.id, column_id=UUID(key), limit=1)
    first = await service.list_backlinks(viewer, target.id, targets[0], query)
    second = await service.list_backlinks(
        viewer, target.id, targets[0], query.model_copy(update={"skip": 1})
    )
    assert [row.id for row in first.items + second.items] == visible
    assert first.has_more and not second.has_more
    target_model = await virtual_table_repo.get_table(db, target.id, organization_id=org.id)
    target_model.row_policy = {
        "rule": "assignee",
        "view_column_id": cid(target, "Assignee"),
        "edit_column_id": cid(target, "Assignee"),
    }
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.list_backlinks(viewer, target.id, targets[0], query)
    # No destination policy bypass is inherited from a visible source row.
    assert len(await _edges(db, visible[0])) == 1


async def test_unresolved_values_keep_evidence_without_duplicating_it_on_later_writes(db):
    service, ctx, org, _owner, source, _target, targets = await _setup(db)
    key = cid(source, "Customers")
    missing = str(uuid4())
    stored = VirtualTableRecord(
        organization_id=org.id,
        table_id=source.id,
        schema_version=source.schema_version,
        values={key: [str(targets[1]), missing, "bad", str(targets[1]), {"bad": "value"}]},
        revision=7,
    )
    db.add(stored)
    await db.flush()
    await relation_repo.sync_record(db, record=stored)
    assert [(edge.position, edge.target_record_id) for edge in await _edges(db, stored.id)] == [
        (0, targets[1])
    ]
    held = list(
        await db.scalars(
            select(VirtualTableLinkEvidence).order_by(VirtualTableLinkEvidence.position)
        )
    )
    assert [(row.position, row.reason, row.value) for row in held] == [
        (1, "missing_target", missing),
        (2, "invalid_id", "bad"),
        (3, "duplicate_target", str(targets[1])),
        (4, "invalid_id", {"bad": "value"}),
    ]
    original_values = deepcopy(stored.values)
    await relation_repo.sync_record(db, record=stored)
    retained_ids = set(await db.scalars(select(VirtualTableLinkEvidence.id)))
    assert retained_ids == {row.id for row in held}
    assert stored.values == original_values
    assert stored.revision == 7
    before = await virtual_table_repo.storage_bytes(db, organization_id=org.id)
    assert before > 0
    unchanged = await service.update_record(
        ctx,
        source.id,
        stored.id,
        RecordUpdate(
            expected_revision=7,
            values={cid(source, "Name"): None},
        ),
    )
    assert unchanged.record.revision == 7
    assert unchanged.record.values[key] == [str(targets[1])]
    await db.refresh(stored)
    assert stored.values == original_values
    changed = await service.update_record(
        ctx,
        source.id,
        stored.id,
        RecordUpdate(
            expected_revision=7,
            values={cid(source, "Name"): "Updated"},
            link_changes={UUID(key): RecordLinkChange(add=[targets[0]])},
        ),
    )
    assert changed.record.revision == 8
    assert changed.record.values[key] == [str(targets[1]), str(targets[0])]
    history = await db.scalar(
        select(VirtualTableRecordHistory).where(
            VirtualTableRecordHistory.record_id == stored.id,
        )
    )
    assert history.before[key] == original_values[key]
    await relation_repo.sync_record(db, record=stored)
    assert await db.scalar(select(func.count()).select_from(VirtualTableLinkEvidence)) == 4
    assert {row.source_revision for row in held} == {7}


@pytest.mark.security
@pytest.mark.parametrize("operation_key", [None, "canonical-import"])
async def test_batch_update_preserves_hidden_edges_and_legacy_evidence(db, operation_key):
    service, ctx, org, owner, source, target, targets = await _setup(db)
    member = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=member.id, role="member"))
    await db.flush()
    writer = ctx_for(member, org, "member")
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=member.id,
        resource_type=TABLE.key,
        resource_id=source.id,
        level=GrantLevel.EDIT,
    )
    for target_id, assignee in ((targets[0], member), (targets[1], owner)):
        await service.update_record(
            ctx,
            target.id,
            target_id,
            RecordUpdate(
                expected_revision=1,
                values={cid(target, "Assignee"): str(assignee.id)},
            ),
        )
    target_model = await virtual_table_repo.get_table(db, target.id, organization_id=org.id)
    target_model.row_policy = {
        "rule": "assignee",
        "view_column_id": cid(target, "Assignee"),
        "edit_column_id": cid(target, "Assignee"),
    }
    name, link = cid(source, "Name"), cid(source, "Customers")
    original = {name: "Before", link: [str(targets[0]), str(targets[1]), "invalid-legacy-id"]}
    stored = VirtualTableRecord(
        organization_id=org.id,
        table_id=source.id,
        external_id="legacy-import",
        schema_version=source.schema_version,
        values=original,
        revision=7,
    )
    db.add(stored)
    await db.flush()
    await relation_repo.sync_record(db, record=stored)
    body = RecordBatchCreate(
        records=[RecordCreate(external_id="legacy-import", values={name: "After"})],
        update_existing=True,
    )
    if operation_key is None:
        result = await service.create_records(writer, source.id, body)
    else:
        result, replayed = await service.write_batch(
            writer, source.id, body, operation_key=operation_key
        )
        assert not replayed
        retry, replayed = await service.write_batch(
            writer, source.id, body, operation_key=operation_key
        )
        assert replayed and retry == result
    assert (result.created, result.updated, result.failed) == (0, 1, [])
    await db.refresh(stored)
    assert stored.revision == 8
    assert stored.values == {name: "After", link: [str(targets[0]), str(targets[1])]}
    assert [edge.target_record_id for edge in await _edges(db, stored.id)] == targets[:2]
    readable = await service.get_record(writer, source.id, stored.id)
    assert readable.values[link] == [str(targets[0])]
    assert str(targets[1]) not in readable.model_dump_json()
    history = list(
        await db.scalars(
            select(VirtualTableRecordHistory).where(
                VirtualTableRecordHistory.record_id == stored.id
            )
        )
    )
    assert len(history) == 1 and history[0].before[link] == original[link]
    evidence = list(await db.scalars(select(VirtualTableLinkEvidence)))
    assert [(row.source_revision, row.reason, row.value) for row in evidence] == [
        (7, "invalid_id", "invalid-legacy-id")
    ]


async def test_source_write_rollback_restores_edges_record_and_history_together(db, monkeypatch):
    service, ctx, org, _owner, source, _target, targets = await _setup(db)
    key = cid(source, "Customers")
    first = await service.create_record(
        ctx, source.id, RecordCreate(values={key: [str(targets[0])]})
    )
    original = relation_repo.sync_record

    async def fail_after_edges(db, *, record):
        await original(db, record=record)
        raise RuntimeError("after edges")

    monkeypatch.setattr(relation_repo, "sync_record", fail_after_edges)
    with pytest.raises(RuntimeError, match="after edges"):
        await service.update_record(
            ctx,
            source.id,
            first.record.id,
            RecordUpdate(
                expected_revision=1,
                values={key: [str(targets[1])]},
            ),
            operation_key="rolled-back",
        )
    stored = await virtual_table_repo.get_record(
        db, first.record.id, table_id=source.id, organization_id=org.id
    )
    assert stored.revision == 1
    assert stored.values[key] == [str(targets[0])]
    assert [edge.target_record_id for edge in await _edges(db, stored.id)] == [targets[0]]
    assert (
        await db.scalar(
            select(func.count())
            .select_from(VirtualTableRecordHistory)
            .where(VirtualTableRecordHistory.record_id == stored.id)
        )
        == 1
    )


@pytest.mark.security
async def test_hidden_destination_payload_size_does_not_change_bound_page_truncation(db):
    service, ctx, org, owner, source, target, targets = await _setup(db)
    member = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=member.id, role="member"))
    await db.flush()
    viewer = ctx_for(member, org, "member")
    for target_id, assignee in ((targets[0], owner), (targets[1], member)):
        await service.update_record(
            ctx,
            target.id,
            target_id,
            RecordUpdate(
                expected_revision=1,
                values={cid(target, "Assignee"): str(assignee.id)},
            ),
        )
        await service.create_record(
            ctx,
            source.id,
            RecordCreate(
                values={cid(source, "Customers"): [str(target_id)]},
            ),
        )
    target_model = await virtual_table_repo.get_table(db, target.id, organization_id=org.id)
    target_model.row_policy = {
        "rule": "assignee",
        "view_column_id": cid(target, "Assignee"),
        "edit_column_id": cid(target, "Assignee"),
    }
    await db.flush()
    bound = await bound_view(db, ctx, source.id)
    named = [UUID(cid(source, "Customers"))]

    async def page():
        return await service.read_bound(
            viewer,
            table_id=source.id,
            columns=bound.columns,
            filters=[],
            sort=bound.config.sort,
            column_ids=named,
            shape=shaper(bound.columns, named),
            max_records=100,
            max_bytes=4_000,
            deadline=ReadDeadline(60, 2_000),
        )

    before = await page()
    hidden = await virtual_table_repo.get_record(
        db, targets[0], table_id=target.id, organization_id=org.id
    )
    hidden.values = {**hidden.values, cid(target, "Name"): "private" * 10_000}
    await db.flush()
    after = await page()
    assert len(before.records) == 2
    assert after.records == before.records
    assert before.stopped_by is None and after.stopped_by is None


async def test_narrowing_counts_active_edges_and_preserves_quarantined_original_positions(db):
    service, ctx, org, _owner, source, _target, targets = await _setup(db)
    key = cid(source, "Customers")
    row = VirtualTableRecord(
        organization_id=org.id,
        table_id=source.id,
        schema_version=source.schema_version,
        revision=1,
        values={key: ["bad", str(targets[0])]},
    )
    db.add(row)
    await db.flush()
    await relation_repo.sync_record(db, record=row)
    changed = await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=source.schema_version,
            columns=_columns(source, link_limit=1),
        ),
    )
    assert next(item for item in changed.columns if item.type == "link").link_limit == 1
    edges = await _edges(db, row.id)
    assert [(edge.position, edge.target_record_id) for edge in edges] == [(0, targets[0])]
    assert row.values[key] == ["bad", str(targets[0])]
    evidence = await db.scalar(
        select(VirtualTableLinkEvidence).where(VirtualTableLinkEvidence.source_record_id == row.id)
    )
    assert evidence.position == 0 and evidence.value == "bad"
    # Only relationship rows are removed; ordinary record/history payload stays
    # unchanged. Each kind of retained relationship data consumes quota.
    for model in (VirtualTableLinkEvidence, VirtualTableRecordLink, VirtualTableRelation):
        before = await virtual_table_repo.storage_bytes(db, organization_id=org.id)
        await db.execute(delete(model).where(model.organization_id == org.id))
        assert await virtual_table_repo.storage_bytes(db, organization_id=org.id) < before


@pytest.mark.security
async def test_quarantined_project_cell_grants_no_single_list_or_backlink_read(db):
    service, ctx, org, owner, source, target, targets = await _setup(db)
    member = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=member.id, role="member"))
    await db.flush()
    viewer = ctx_for(member, org, "member")
    await service.update_record(
        ctx,
        target.id,
        targets[0],
        RecordUpdate(
            expected_revision=1,
            values={cid(target, "Assignee"): str(member.id)},
        ),
    )
    key = cid(source, "Customers")
    valid = await service.create_record(
        ctx,
        source.id,
        RecordCreate(
            values={
                cid(source, "Assignee"): str(owner.id),
                key: [str(targets[0])],
            }
        ),
    )
    held = VirtualTableRecord(
        organization_id=org.id,
        table_id=source.id,
        schema_version=source.schema_version,
        revision=1,
        values={cid(source, "Assignee"): str(owner.id), key: [str(targets[0])] * 101},
    )
    db.add(held)
    await db.flush()
    await relation_repo.sync_record(db, record=held)
    await service.set_row_policy(
        ctx,
        source.id,
        RowPolicyUpdate(
            rule="assignee",
            view_column_id=UUID(cid(source, "Assignee")),
            edit_column_id=UUID(cid(source, "Assignee")),
            view_project_link_column_id=UUID(key),
            view_projects_table_id=target.id,
            view_project_members_column_id=UUID(cid(target, "Assignee")),
        ),
    )
    with pytest.raises(NotFoundError):
        await service.get_record(viewer, source.id, held.id)
    listed = await service.list_records(viewer, source.id, RecordQuery())
    backlinks = await service.list_backlinks(
        viewer,
        target.id,
        targets[0],
        BacklinkQuery(
            source_table_id=source.id,
            column_id=UUID(key),
        ),
    )
    assert [item.id for item in listed.items] == [valid.record.id]
    assert [item.id for item in backlinks.items] == [valid.record.id]

    # An owner still filters the canonical representation: held legacy values
    # cannot make a contains filter match or make an empty link appear populated.
    for op, value, expected in [
        ("contains", str(targets[0]), [valid.record.id]),
        ("is_null", True, [held.id]),
    ]:
        filtered = await service.list_records(
            ctx,
            source.id,
            RecordQuery(filters=[RecordFilter(column_id=UUID(key), op=op, value=value)]),
        )
        assert [item.id for item in filtered.items] == expected

    # The linked destination policy itself uses an edge EXISTS. Its source row
    # must be adapted to the destination alias, even though the outer link filter
    # is also a canonical edge query.
    container = await service.create_table(
        ctx,
        TableCreate(
            name="Order bundle",
            visibility="org",
            columns=[column("Orders", "link", link_table_id=source.id)],
        ),
    )
    order_key = cid(container, "Orders")
    bundle = await service.create_record(
        ctx,
        container.id,
        RecordCreate(values={order_key: [str(valid.record.id), str(held.id)]}),
    )
    for record_id, expected in [(valid.record.id, [bundle.record.id]), (held.id, [])]:
        filtered = await service.list_records(
            viewer,
            container.id,
            RecordQuery(
                filters=[
                    RecordFilter(column_id=UUID(order_key), op="contains", value=str(record_id))
                ]
            ),
        )
        assert [item.id for item in filtered.items] == expected


@pytest.mark.security
@pytest.mark.parametrize("icon_field", [False, True], ids=["before-icons", "nullable-icon"])
async def test_default_metadata_replays_legacy_table_receipts_without_changing_the_body(
    db, icon_field
):
    service, ctx, org, _owner, _source, target, _targets = await _setup(db)
    body = TableCreate(
        name="Legacy request",
        columns=[
            column("Name", "text"),
            column("Customer", "link", link_table_id=target.id),
        ],
    )
    first = await service.create_table(ctx, body, operation_key="before-link-limit")
    receipt = await virtual_table_repo.read_receipt(
        db,
        organization_id=org.id,
        principal_id=ctx.subject_id,
        operation="table.create",
        operation_key="before-link-limit",
    )
    legacy = body.model_dump(mode="json")
    for field in legacy["columns"]:
        field.pop("link_limit")
    if icon_field:
        legacy["icon"] = None
    else:
        legacy.pop("icon", None)
    receipt.payload_hash = payload_hash(legacy)
    receipt.outcome = {
        **receipt.outcome,
        "columns": [
            {key: value for key, value in field.items() if key != "link_limit"}
            for field in receipt.outcome["columns"]
        ],
    }
    if not icon_field:
        receipt.outcome = {key: value for key, value in receipt.outcome.items() if key != "icon"}
    await db.flush()
    retry = await service.create_table(ctx, body, operation_key="before-link-limit")
    assert retry.id == first.id
    limit_changed = body.model_copy(
        update={
            "columns": [
                body.columns[0],
                body.columns[1].model_copy(update={"link_limit": 1}),
            ]
        }
    )
    for changed in (
        limit_changed,
        body.model_copy(update={"name": "Changed request"}),
        body.model_copy(update={"icon": "table"}),
    ):
        with pytest.raises(IdempotencyKeyReuseError):
            await service.create_table(ctx, changed, operation_key="before-link-limit")


async def test_only_a_link_column_may_limit_its_linked_records(db):
    service, ctx, *_rest = await _setup(db)
    with pytest.raises(InvalidSchemaError, match="Only a link column limits linked records"):
        await service.create_table(
            ctx,
            TableCreate(name="Notes", columns=[column("Name", "text", link_limit=2)]),
        )


async def test_relationship_definitions_need_an_existing_source_table(db):
    with pytest.raises(ValueError, match="existing source table"):
        await relation_repo.sync_schema(db, table_id=uuid4(), columns=[])


async def test_resyncing_an_unchanged_record_keeps_one_copy_of_its_evidence(db):
    _service, _ctx, org, _owner, source, _target, targets = await _setup(db)
    key = cid(source, "Customers")
    stored = VirtualTableRecord(
        organization_id=org.id,
        table_id=source.id,
        schema_version=source.schema_version,
        values={key: [str(targets[0]), "bad"]},
        revision=3,
    )
    db.add(stored)
    await db.flush()
    await relation_repo.sync_record(db, record=stored)
    await relation_repo.sync_record(db, record=stored)
    held = list(await db.scalars(select(VirtualTableLinkEvidence)))
    assert [(row.position, row.reason, row.value) for row in held] == [(1, "invalid_id", "bad")]
    assert [edge.target_record_id for edge in await _edges(db, stored.id)] == [targets[0]]


async def test_replaying_a_create_whose_record_was_deleted_since_is_not_found(db):
    service, ctx, _org, _owner, source, _target, targets = await _setup(db)
    body = RecordCreate(values={cid(source, "Customers"): [str(targets[0])]})
    first = await service.create_record(ctx, source.id, body, operation_key="gone-since")
    await service.delete_record(ctx, source.id, first.record.id, expected_revision=1)
    with pytest.raises(NotFoundError, match="Record not found"):
        await service.create_record(ctx, source.id, body, operation_key="gone-since")


async def test_purging_a_linked_task_board_removes_the_links_and_keeps_the_table_editable(db):
    from app.schemas.task import TaskCreate
    from app.services.tasks import TaskService

    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    task = await TaskService(db).create(ctx, TaskCreate(title="Linked task"))
    board = await service.describe_table(ctx, task.table_id)
    source = await service.create_table(
        ctx,
        TableCreate(
            name="Orders",
            visibility="org",
            columns=[column("Name", "text"), column("Tasks", "link", link_table_id=board.id)],
        ),
    )
    link_id = UUID(cid(source, "Tasks"))
    title_id = next(item.id for item in board.columns if item.type == "text")
    source = await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=source.schema_version,
            columns=[
                *_columns(source),
                column("Task title", "lookup", link_column_id=link_id, target_column_id=title_id),
                column("Shout", "formula", formula="UPPER({Task title})"),
            ],
        ),
    )
    written = await service.create_record(
        ctx,
        source.id,
        RecordCreate(values={cid(source, "Name"): "One", str(link_id): [str(task.id)]}),
    )
    assert len(await _edges(db, written.record.id)) == 1

    await TaskService(db).purge_scope("private", owner.id, organization_id=org.id)

    assert await virtual_table_repo.get_table(db, board.id, organization_id=org.id) is None
    purged = await service.describe_table(ctx, source.id)
    stored = await virtual_table_repo.get_schema_version(
        db, table_id=source.id, version=purged.schema_version
    )
    # Removed, not archived: no column of the live schema names the purged table.
    assert [(item["label"], item["type"], item["archived"]) for item in stored.columns] == [
        ("Name", "text", False),
        ("Shout", "formula", True),
    ]
    assert all(item.get("link_table_id") is None for item in stored.columns)
    assert (
        await relation_repo.definitions(db, organization_id=org.id, source_table_id=source.id) == []
    )
    assert await _edges(db, written.record.id) == []
    edited = await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=purged.schema_version,
            columns=[*_columns(purged), column("Notes", "text")],
        ),
    )
    assert edited.schema_version == purged.schema_version + 1
    assert [item.label for item in edited.columns] == ["Name", "Shout", "Notes"]
    assert all(item.link_table_id is None for item in edited.columns)
    assert (
        await relation_repo.definitions(db, organization_id=org.id, source_table_id=source.id) == []
    )
