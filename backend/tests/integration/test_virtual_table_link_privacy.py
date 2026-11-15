"""Link predicates, counts and projections cannot reveal an unreadable destination."""

import csv
from io import StringIO
from uuid import UUID, uuid4

import pytest

from app.db.models.organization import OrganizationMember
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import (
    RecordCountQuery,
    RecordExportQuery,
    RecordFilter,
    RecordQuery,
    RecordSort,
    SchemaUpdate,
    TableCreate,
)
from app.services.virtual_tables import ReadDeadline, VirtualTableService
from tests.integration.virtual_table_support import (
    cid,
    column,
    ctx_for,
    insert_rows,
    make_org,
    make_user,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _people(db):
    owner = await make_user(db)
    viewer = await make_user(db)
    org = await make_org(db, owner=owner)
    db.add(OrganizationMember(id=uuid4(), organization_id=org.id, user_id=viewer.id, role="viewer"))
    await db.flush()
    return owner, viewer, org


async def _restrict(db, table, org, assignee):
    stored = await virtual_table_repo.get_table(db, table.id, organization_id=org.id)
    stored.row_policy = {
        "rule": "assignee",
        "view_column_id": assignee,
        "edit_column_id": assignee,
    }
    await db.flush()
    return stored


async def test_link_filters_agree_across_lists_counts_exports_and_bound_reads(db):
    owner, viewer, org = await _people(db)
    service = VirtualTableService(db)
    owner_ctx, reader = ctx_for(owner, org), ctx_for(viewer, org, "viewer")
    target = await service.create_table(
        owner_ctx,
        TableCreate(
            name="Destinations",
            visibility="org",
            columns=[column("Name", "text"), column("Assignee", "user")],
        ),
    )
    visible, hidden = await insert_rows(
        db,
        target,
        [
            {cid(target, "Name"): "Public label", cid(target, "Assignee"): str(viewer.id)},
            {cid(target, "Name"): "Private label", cid(target, "Assignee"): str(owner.id)},
        ],
    )
    await _restrict(db, target, org, cid(target, "Assignee"))
    source = await service.create_table(
        owner_ctx,
        TableCreate(
            name="Sources",
            visibility="org",
            columns=[column("Name", "text"), column("Related", "link", link_table_id=target.id)],
        ),
    )
    name, link = cid(source, "Name"), cid(source, "Related")
    dangling = uuid4()
    identifiers = await insert_rows(
        db,
        source,
        [
            {name: "visible", link: [str(visible)]},
            {name: "hidden", link: [str(hidden)]},
            {name: "both", link: [str(visible), str(hidden)]},
            {name: "empty", link: []},
            {name: "missing"},
            {name: "dangling", link: [str(dangling)]},
        ],
    )
    all_ids = set(identifiers)
    names_by_id = dict(
        zip(identifiers, ("visible", "hidden", "both", "empty", "missing", "dangling"))
    )
    visible_sources = {identifiers[0], identifiers[2]}
    for operation, value, expected in (
        ("contains", str(visible), visible_sources),
        ("contains", str(hidden), set()),
        ("contains", str(dangling), set()),
        ("is_null", True, all_ids - visible_sources),
        ("is_null", False, visible_sources),
    ):
        filters = [RecordFilter(column_id=UUID(link), op=operation, value=value)]
        page = await service.list_records(reader, source.id, RecordQuery(filters=filters))
        assert {item.id for item in page.items} == expected
        assert str(hidden) not in page.model_dump_json()
        count = await service.count_records(reader, source.id, RecordCountQuery(filters=filters))
        assert count.count == len(expected)
        exported = await service.export_records(
            reader, source.id, RecordExportQuery(filters=filters, include_metadata=True)
        )
        exported_csv = "".join([line async for line in exported.lines])
        assert str(hidden) not in exported_csv and "Private label" not in exported_csv
        exported_rows = list(csv.DictReader(StringIO(exported_csv.lstrip("\ufeff"))))
        assert {row["Name"] for row in exported_rows} == {names_by_id[item] for item in expected}
        assert len(exported_rows) == len(expected)
        bound = await service.read_bound(
            reader,
            table_id=source.id,
            columns=source.columns,
            filters=filters,
            sort=RecordSort(),
            column_ids=[item.id for item in source.columns],
            shape=lambda record: {"id": str(record.id), "values": record.values},
            max_records=100,
            max_bytes=100_000,
            deadline=ReadDeadline(60, 10_000),
        )
        assert {UUID(item["id"]) for item in bound.records} == expected
        assert str(hidden) not in str(bound.records)

    # Several predicates on one destination must reuse its authorization while
    # preserving conjunction semantics and the hidden-target refusal.
    for destination, expected in ((visible, visible_sources), (hidden, set())):
        page = await service.list_records(
            reader,
            source.id,
            RecordQuery(
                filters=[
                    RecordFilter(column_id=UUID(link), op="is_null", value=False),
                    RecordFilter(column_id=UUID(link), op="contains", value=str(destination)),
                ]
            ),
        )
        assert {item.id for item in page.items} == expected


@pytest.mark.parametrize("invalid", [False, True])
async def test_unreadable_or_invalid_target_policy_is_an_empty_filter_surface(db, invalid):
    owner, viewer, org = await _people(db)
    service = VirtualTableService(db)
    owner_ctx, reader = ctx_for(owner, org), ctx_for(viewer, org, "viewer")
    target = await service.create_table(
        owner_ctx,
        TableCreate(
            name="Restricted target",
            visibility="org" if invalid else "private",
            columns=[column("Name", "text")],
        ),
    )
    destination = (await insert_rows(db, target, [{cid(target, "Name"): "Secret"}]))[0]
    source = await service.create_table(
        owner_ctx,
        TableCreate(
            name="Readable source",
            visibility="org",
            columns=[column("Related", "link", link_table_id=target.id)],
        ),
    )
    link = cid(source, "Related")
    source_id = (await insert_rows(db, source, [{link: [str(destination)]}]))[0]
    if invalid:
        stored = await virtual_table_repo.get_table(db, target.id, organization_id=org.id)
        stored.row_policy = {"rule": "unexpected"}
        await db.flush()
    for operation, value, expected in (
        ("contains", str(destination), set()),
        ("is_null", False, set()),
        ("is_null", True, {source_id}),
    ):
        page = await service.list_records(
            reader,
            source.id,
            RecordQuery(filters=[RecordFilter(column_id=UUID(link), op=operation, value=value)]),
        )
        assert {item.id for item in page.items} == expected
        assert str(destination) not in page.model_dump_json()


async def test_self_links_apply_the_policy_to_the_destination_alias(db):
    owner, viewer, org = await _people(db)
    service = VirtualTableService(db)
    owner_ctx, reader = ctx_for(owner, org), ctx_for(viewer, org, "viewer")
    table = await service.create_table(
        owner_ctx,
        TableCreate(
            name="Self links",
            visibility="org",
            columns=[column("Name", "text"), column("Assignee", "user")],
        ),
    )
    table = await service.update_schema(
        owner_ctx,
        table.id,
        SchemaUpdate(
            expected_version=table.schema_version,
            columns=[
                *(column(item.label, item.type, id=item.id) for item in table.columns),
                column("Related", "link", link_table_id=table.id),
            ],
        ),
    )
    assignee, link = cid(table, "Assignee"), cid(table, "Related")
    visible, hidden = await insert_rows(
        db, table, [{assignee: str(viewer.id)}, {assignee: str(owner.id)}]
    )
    hidden_source, visible_source = await insert_rows(
        db,
        table,
        [
            {assignee: str(viewer.id), link: [str(hidden)]},
            {assignee: str(viewer.id), link: [str(visible)]},
        ],
    )
    await _restrict(db, table, org, assignee)
    for destination, expected in ((visible, {visible_source}), (hidden, set())):
        page = await service.list_records(
            reader,
            table.id,
            RecordQuery(
                filters=[RecordFilter(column_id=UUID(link), op="contains", value=str(destination))]
            ),
        )
        assert {item.id for item in page.items} == expected
    page = await service.list_records(
        reader,
        table.id,
        RecordQuery(filters=[RecordFilter(column_id=UUID(link), op="is_null", value=True)]),
    )
    assert {item.id for item in page.items} == {visible, hidden_source}
