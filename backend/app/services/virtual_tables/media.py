"""Pasted images use table access and the table storage quota."""

from uuid import UUID

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.virtual_table import VirtualTableMedia
from app.repositories import virtual_table_repo
from app.services.file_storage import sniff_image_header
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.quotas import enforce_storage, lock_storage

MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


class MediaOperations(Operations):
    """Atomic bounded uploads retained with the table and its history."""

    async def upload_image(
        self, ctx: AuthContext, table_id: UUID, data: bytes
    ) -> VirtualTableMedia:
        """Authorize the editor, validate bytes and admit their stored size."""
        await lock_storage(self.db, ctx)
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, share=True)
        self._ensure_live(table)
        mime = sniff_image_header(data)
        if not data or len(data) > MAX_IMAGE_BYTES or mime not in IMAGE_TYPES:
            raise BadRequestError(
                message="Paste a PNG, JPEG, GIF or WebP image up to 5 MiB",
                details={"max_bytes": MAX_IMAGE_BYTES},
            )
        async with self.db.begin_nested():
            media = await virtual_table_repo.create_media(
                self.db,
                organization_id=ctx.organization_id,
                table_id=table.id,
                mime_type=mime,
                data=data,
            )
            await enforce_storage(self.db, ctx, table)
        return media

    async def read_image(
        self, ctx: AuthContext, table_id: UUID, media_id: UUID
    ) -> VirtualTableMedia:
        """Recheck table access on every read, including archived tables."""
        await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        media = await virtual_table_repo.get_media(
            self.db, organization_id=ctx.organization_id, table_id=table_id, media_id=media_id
        )
        if media is None:
            raise NotFoundError(message="Table image not found", details={"media_id": media_id})
        return media

    async def discard_image(self, ctx: AuthContext, table_id: UUID, media_id: UUID) -> None:
        """Release an unused upload without deleting images kept in record history."""
        await lock_storage(self.db, ctx)
        await self._load_table(ctx, table_id, Perm.TABLES_EDIT, share=True)
        await virtual_table_repo.delete_unused_media(
            self.db, organization_id=ctx.organization_id, table_id=table_id, media_id=media_id
        )
