"""Images inherit table grants and storage admission, including refusal paths."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.virtual_table import VirtualTable, VirtualTableMedia
from app.services.virtual_tables import media
from app.services.virtual_tables.exceptions import QuotaExceededError, TableArchivedError

pytestmark = pytest.mark.anyio
PNG = b"\x89PNG\r\n\x1a\nexample"


@pytest.fixture
def context() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


@pytest.fixture
def setup(context: AuthContext, monkeypatch: pytest.MonkeyPatch):
    db = MagicMock(spec=AsyncSession)
    service = media.MediaOperations(db)
    table = VirtualTable(id=uuid4(), organization_id=context.organization_id, archived_at=None)
    loaded = AsyncMock(return_value=table)
    monkeypatch.setattr(service, "_load_table", loaded)
    monkeypatch.setattr(media, "lock_storage", AsyncMock())
    monkeypatch.setattr(media, "enforce_storage", AsyncMock())
    created = AsyncMock(
        return_value=VirtualTableMedia(
            id=uuid4(), table_id=table.id, data=PNG, mime_type="image/png"
        )
    )
    found = AsyncMock(return_value=created.return_value)
    monkeypatch.setattr(media.virtual_table_repo, "create_media", created)
    monkeypatch.setattr(media.virtual_table_repo, "get_media", found)
    return service, table, loaded, created, found


async def test_upload_and_read_use_table_permissions_and_tenant(context, setup):
    service, table, loaded, created, found = setup
    image = await service.upload_image(context, table.id, PNG)
    assert "VirtualTableMedia" in repr(image)
    loaded.assert_awaited_once_with(context, table.id, Perm.TABLES_EDIT, share=True)
    created.assert_awaited_once_with(
        service.db,
        organization_id=context.organization_id,
        table_id=table.id,
        data=PNG,
        mime_type="image/png",
    )
    assert await service.read_image(context, table.id, image.id) is image
    loaded.assert_awaited_with(context, table.id, Perm.TABLES_VIEW)
    found.assert_awaited_once_with(
        service.db, organization_id=context.organization_id, table_id=table.id, media_id=image.id
    )


@pytest.mark.parametrize("data", [b"", b"<svg></svg>", PNG + b"x" * media.MAX_IMAGE_BYTES])
async def test_invalid_or_oversized_images_write_nothing(context, setup, data):
    service, table, _, created, _ = setup
    with pytest.raises(BadRequestError):
        await service.upload_image(context, table.id, data)
    created.assert_not_awaited()


async def test_a_revoked_grant_never_reads_image_bytes(context, setup):
    service, table, loaded, created, found = setup
    loaded.side_effect = NotFoundError(message="Table not found")
    with pytest.raises(NotFoundError):
        await service.read_image(context, table.id, uuid4())
    found.assert_not_awaited()
    with pytest.raises(NotFoundError):
        await service.upload_image(context, table.id, PNG)
    created.assert_not_awaited()


async def test_missing_image_does_not_resolve_in_another_table(context, setup):
    service, table, _, _, found = setup
    found.return_value = None
    with pytest.raises(NotFoundError):
        await service.read_image(context, table.id, uuid4())


async def test_quota_refusal_exits_the_image_savepoint(context, setup, monkeypatch):
    service, table, _, _, _ = setup
    monkeypatch.setattr(
        media,
        "enforce_storage",
        AsyncMock(side_effect=QuotaExceededError(quota="storage_bytes", limit=1, message="Full")),
    )
    with pytest.raises(QuotaExceededError):
        await service.upload_image(context, table.id, PNG)
    service.db.begin_nested.return_value.__aexit__.assert_awaited_once()


async def test_archived_tables_refuse_uploads_but_still_allow_reads(context, setup):
    from datetime import UTC, datetime

    service, table, _, created, found = setup
    table.archived_at = datetime.now(UTC)
    with pytest.raises(TableArchivedError):
        await service.upload_image(context, table.id, PNG)
    created.assert_not_awaited()
    assert await service.read_image(context, table.id, uuid4()) is found.return_value
