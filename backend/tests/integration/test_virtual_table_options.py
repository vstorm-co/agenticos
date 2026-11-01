"""Choice presentation and creation defaults share the durable table schema."""

import csv
from io import StringIO

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.virtual_table import (
    ColumnInput,
    OptionInput,
    RecordCreate,
    RecordExportQuery,
    RecordUpdate,
    SchemaUpdate,
    TableCreate,
)
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.exceptions import InvalidRecordError
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


async def test_choice_defaults_colors_and_record_metadata_roundtrip(db: AsyncSession) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    table = await service.create_table(
        ctx,
        TableCreate(
            name="Tasks",
            columns=[
                ColumnInput(
                    label="Status",
                    type="single_select",
                    options=[
                        OptionInput(label="Todo", color="blue"),
                        OptionInput(label="Done", color="green"),
                    ],
                    default="Todo",
                ),
                ColumnInput(
                    label="Tags",
                    type="multi_select",
                    options=[
                        OptionInput(label="API", color="purple"),
                        OptionInput(label="Docs", color="yellow"),
                    ],
                    default=["API"],
                ),
            ],
        ),
    )
    status, tags = table.columns
    first = (await service.create_record(ctx, table.id, RecordCreate())).record
    assert first.values[str(status.id)] == str(status.options[0].id)
    assert first.values[str(tags.id)] == [str(tags.options[0].id)]
    updated_schema = await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=table.schema_version,
            columns=[
                ColumnInput(
                    id=status.id,
                    label="Status",
                    type="single_select",
                    options=[
                        OptionInput(id=status.options[0].id, label="Todo", color="red"),
                        OptionInput(id=status.options[1].id, label="Done", color="green"),
                    ],
                    default="Done",
                ),
                ColumnInput.model_validate(tags.model_dump()),
            ],
        ),
    )
    assert updated_schema.columns[0].options[0].color == "red"
    reread = await service.describe_table(ctx, table.id)
    assert reread.columns[0].options[0].color == "red"
    second = (await service.create_record(ctx, table.id, RecordCreate())).record
    assert second.values[str(status.id)] == str(status.options[1].id)
    assert (await service.get_record(ctx, table.id, first.id)).values[str(status.id)] == str(
        status.options[0].id
    )
    assert first.created_by == owner.id
    assert first.created_at is not None
    with pytest.raises(InvalidRecordError):
        await service.update_record(
            ctx,
            table.id,
            first.id,
            RecordUpdate(expected_revision=first.revision, values={"__created_at": "2020-01-01"}),
        )
    unchanged = await service.get_record(ctx, table.id, first.id)
    assert unchanged.created_at == first.created_at
    assert unchanged.revision == first.revision

    exported = await service.export_records(ctx, table.id, RecordExportQuery(include_metadata=True))
    parsed = list(
        csv.reader(StringIO("".join([line async for line in exported.lines]).lstrip("\ufeff")))
    )
    assert parsed[0][-4:] == ["created_at", "updated_at", "created_by", "updated_by"]
    assert parsed[1][-2] == str(owner.id)
