"""Markdown documents round-trip through the table service and actual JSONB storage."""

import csv
from io import StringIO

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.virtual_table import (
    ColumnInput,
    RecordCreate,
    RecordExportQuery,
    RecordFilter,
    RecordQuery,
    RecordSort,
    RecordUpdate,
    SchemaUpdate,
    TableCreate,
)
from app.services.virtual_tables import VirtualTableService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


async def test_markdown_preserves_frontmatter_through_storage_queries_conversion_and_export(
    db: AsyncSession,
) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    table = await service.create_table(
        ctx, TableCreate(name="Notes", columns=[ColumnInput(label="Body", type="rich_text")])
    )
    field = table.columns[0]
    source = (
        '---\r\ntitle: "Zażółć"\r\ntags: [team, notes]\r\n---\r\n# Meeting\r\n\r\n**Review**\r\n'
    )
    created = await service.create_record(
        ctx, table.id, RecordCreate(values={str(field.id): source})
    )
    assert created.record.values[str(field.id)] == source
    await service.create_record(ctx, table.id, RecordCreate(values={str(field.id): "Z last"}))
    listed = await service.list_records(
        ctx,
        table.id,
        RecordQuery(
            search="team",
            filters=[RecordFilter(column_id=field.id, op="contains", value="# Meeting")],
        ),
    )
    assert [record.id for record in listed.items] == [created.record.id]
    sorted_rows = await service.list_records(
        ctx, table.id, RecordQuery(sort=RecordSort(by=str(field.id)))
    )
    assert [record.values[str(field.id)] for record in sorted_rows.items] == [source, "Z last"]
    updated = await service.update_record(
        ctx,
        table.id,
        created.record.id,
        RecordUpdate(expected_revision=1, values={str(field.id): source + "Next\r\n"}),
    )
    assert updated.record.values[str(field.id)] == source + "Next\r\n"
    for kind in ("long_text", "rich_text"):
        table = await service.update_schema(
            ctx,
            table.id,
            SchemaUpdate(
                expected_version=table.schema_version,
                columns=[ColumnInput(id=field.id, label="Body", type=kind)],
            ),
        )
    reread = await service.get_record(ctx, table.id, created.record.id)
    assert reread.values[str(field.id)] == source + "Next\r\n"
    export = await service.export_records(ctx, table.id, RecordExportQuery(search="team"))
    content = "".join([part async for part in export.lines])
    rows = list(csv.reader(StringIO(content.lstrip("\ufeff"), newline="")))
    # The CSV shield prefixes leading '-' for spreadsheet safety; import removes it.
    assert rows == [["Body"], ["'" + source + "Next\r\n"]]


async def test_document_template_applies_only_on_creation_and_system_metadata_stays_authoritative(
    db: AsyncSession,
) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    first_template = "# Notes\n\n## Summary\n\n- [ ] Follow up\n"
    table = await service.create_table(
        ctx,
        TableCreate(
            name="Templated notes",
            columns=[ColumnInput(label="Document", type="rich_text", default=first_template)],
        ),
    )
    column = table.columns[0]
    key = str(column.id)
    first = (await service.create_record(ctx, table.id, RecordCreate())).record
    assert first.values[key] == first_template
    assert first.created_by == owner.id
    assert first.created_at is not None
    await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=table.schema_version,
            columns=[
                ColumnInput(
                    id=column.id, label="Document", type="rich_text", default="# New template"
                )
            ],
        ),
    )
    assert (await service.get_record(ctx, table.id, first.id)).values[key] == first_template
    second = (await service.create_record(ctx, table.id, RecordCreate())).record
    assert second.values[key] == "# New template"
    explicit = (await service.create_record(ctx, table.id, RecordCreate(values={key: ""}))).record
    assert explicit.values[key] == ""
    spoofed = "---\ncreated_at: spoofed\ncreated_by: somebody else\n---\n# Actual content"
    updated = (
        await service.update_record(
            ctx,
            table.id,
            first.id,
            RecordUpdate(expected_revision=first.revision, values={key: spoofed}),
        )
    ).record
    assert updated.values[key] == spoofed
    assert updated.created_at == first.created_at
    assert updated.created_by == owner.id
    assert updated.updated_by == owner.id
    assert updated.updated_at is not None
