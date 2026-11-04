"""Real table isolation, image storage accounting and database constraints."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.virtual_table import VirtualTableMedia
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import TableCreate
from app.services.virtual_tables import VirtualTableService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio
PNG = b"\x89PNG\r\n\x1a\nexample"


@pytest.mark.security
async def test_table_images_are_private_tenant_scoped_and_counted(db: AsyncSession):
    owner = await make_user(db)
    colleague = await make_user(db)
    org = await make_org(db, owner=owner)
    other_org = await make_org(db, owner=colleague)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    table = await service.create_table(ctx, TableCreate(name="Documents"))
    before = await virtual_table_repo.storage_bytes(db, organization_id=org.id)
    image = await service.upload_image(ctx, table.id, PNG)
    assert await virtual_table_repo.storage_bytes(db, organization_id=org.id) == before + len(PNG)
    assert await virtual_table_repo.storage_bytes(db, organization_id=other_org.id) == 0
    assert (await service.read_image(ctx, table.id, image.id)).data == PNG
    for outsider in [ctx_for(colleague, org, "viewer"), ctx_for(colleague, other_org)]:
        with pytest.raises(NotFoundError):
            await service.read_image(outsider, table.id, image.id)
        with pytest.raises(NotFoundError):
            await service.upload_image(outsider, table.id, PNG)
    await service.archive_table(ctx, table.id)
    assert (await service.read_image(ctx, table.id, image.id)).data == PNG


async def test_image_constraints_refuse_wrong_table_type_and_size(db: AsyncSession):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    service = VirtualTableService(db)
    table = await service.create_table(ctx_for(owner, org), TableCreate(name="Documents"))
    for table_id, mime, data in [
        (uuid4(), "image/png", PNG),
        (table.id, "image/svg+xml", PNG),
        (table.id, "image/png", b""),
    ]:
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await virtual_table_repo.create_media(
                    db, organization_id=org.id, table_id=table_id, mime_type=mime, data=data
                )
    assert await db.scalar(select(func.count()).select_from(VirtualTableMedia)) == 0


async def test_abandoned_images_release_quota_but_record_history_keeps_its_images(db: AsyncSession):
    from app.schemas.virtual_table import ColumnInput, RecordCreate

    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    table = await service.create_table(
        ctx, TableCreate(name="Notes", columns=[ColumnInput(label="Body", type="rich_text")])
    )
    baseline = await virtual_table_repo.storage_bytes(db, organization_id=org.id)
    image = await service.upload_image(ctx, table.id, PNG)
    await service.discard_image(ctx, table.id, image.id)
    await service.discard_image(ctx, table.id, image.id)
    assert await virtual_table_repo.storage_bytes(db, organization_id=org.id) == baseline
    kept = await service.upload_image(ctx, table.id, PNG)
    created = await service.create_record(
        ctx,
        table.id,
        RecordCreate(
            values={
                str(
                    table.columns[0].id
                ): f"![](/api/tables/{table.id}/media/{str(kept.id).upper()})"
            }
        ),
    )
    await service.discard_image(ctx, table.id, kept.id)
    assert (await service.read_image(ctx, table.id, kept.id)).data == PNG
    await service.delete_record(
        ctx, table.id, created.record.id, expected_revision=created.record.revision
    )
    await service.discard_image(ctx, table.id, kept.id)
    assert (await service.read_image(ctx, table.id, kept.id)).data == PNG
    outsider = await make_user(db)
    other_org = await make_org(db, owner=outsider)
    with pytest.raises(NotFoundError):
        await service.discard_image(ctx_for(outsider, other_org), table.id, kept.id)
