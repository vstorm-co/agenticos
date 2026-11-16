"""Read-only backlinks over the canonical edges, with both endpoint permissions."""

from uuid import UUID

from sqlalchemy import and_

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.repositories import virtual_table_relation as relation_repo
from app.repositories import virtual_table_repo
from app.repositories.virtual_table import SortClause
from app.schemas.virtual_table import RecordList
from app.schemas.virtual_table_relation import BacklinkQuery
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.computed import read_through
from app.services.virtual_tables.record_access import with_record_access
from app.services.virtual_tables.records import RecordOperations
from app.services.virtual_tables.row_policy import view_expression


class RelationOperations(Operations):
    async def list_backlinks(
        self, ctx: AuthContext, table_id: UUID, record_id: UUID, query: BacklinkQuery
    ) -> RecordList:
        """Source rows the caller can read that link to a destination they can read.

        The caller names a source table and field. Hidden tables or source records
        are never enumerated as relationship metadata or hidden counts.
        A backlink grants no source write authority and creates no reverse edges.
        """
        await RecordOperations(self.db).get_record(ctx, table_id, record_id)
        source = await self._load_table(ctx, query.source_table_id, Perm.TABLES_VIEW)
        relation = await relation_repo.get_definition(
            self.db,
            organization_id=ctx.organization_id,
            source_table_id=source.id,
            column_id=query.column_id,
            target_table_id=table_id,
        )
        if relation is None:
            raise NotFoundError(
                message="Relationship not found", details={"column_id": query.column_id}
            )
        columns = await self._columns(source)
        visible = await view_expression(self.db, ctx, source, columns)
        linked = relation_repo.contains_targets(query.column_id, [record_id])
        rows = await virtual_table_repo.list_records(
            self.db,
            organization_id=ctx.organization_id,
            table_id=source.id,
            filters=[],
            sort=SortClause(direction="asc"),
            skip=query.skip,
            limit=query.limit + 1,
            extra=linked if visible is None else and_(linked, visible),
        )
        items = await read_through(self.db, ctx, columns, rows[: query.limit])
        items = await with_record_access(self.db, ctx, source, columns, items)
        return RecordList(
            items=items, skip=query.skip, limit=query.limit, has_more=len(rows) > query.limit
        )
