"""What table and record operations share: loading a table the caller may reach."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.virtual_table import VirtualTable
from app.repositories import virtual_table_repo
from app.schemas.resource_grant import as_visibility
from app.schemas.virtual_table import ColumnDef, TableRead
from app.services.access import TABLE, resolve_access
from app.services.virtual_tables.exceptions import TableArchivedError


class Operations:
    """A session and the two questions every operation starts with."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _load_table(
        self,
        ctx: AuthContext,
        table_id: UUID,
        perm: Perm,
        *,
        lock: bool = False,
        share: bool = False,
    ) -> VirtualTable:
        """The table, if this caller may exercise `perm` on it.

        Another organization's table and one the caller may not reach are both a
        404: whether a private table exists is itself something the caller may not
        learn. `lock` takes the row lock that serializes schema changes; `share` is the lock a
        record write takes, which waits for a schema change or an archive in flight and holds
        them off until the write commits. Table locks come first and the audit chain lock last,
        so the two never wait on each other.
        """
        table = await virtual_table_repo.get_table(
            self.db,
            table_id,
            organization_id=ctx.organization_id,
            for_update=lock,
            for_share=share,
        )
        if table is None or not await resolve_access(
            self.db, ctx, table, perm, resource_type=TABLE
        ):
            raise NotFoundError(message="Table not found", details={"table_id": table_id})
        return table

    async def _columns(self, table: VirtualTable) -> list[ColumnDef]:
        """The columns of the table's current schema version."""
        version = await virtual_table_repo.get_schema_version(
            self.db, table_id=table.id, version=table.schema_version
        )
        return [ColumnDef.model_validate(column) for column in version.columns]

    @staticmethod
    def _ensure_live(table: VirtualTable) -> None:
        if table.archived_at is not None:
            raise TableArchivedError(table_id=table.id)

    @staticmethod
    def _read(table: VirtualTable, columns: list[ColumnDef]) -> TableRead:
        return TableRead(
            id=table.id,
            name=table.name,
            description=table.description,
            visibility=as_visibility(table.visibility),
            owner_user_id=table.owner_user_id,
            schema_version=table.schema_version,
            archived_at=table.archived_at,
            created_at=table.created_at,
            updated_at=table.updated_at,
            columns=columns,
        )
