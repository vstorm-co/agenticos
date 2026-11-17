"""Read-only backlinks over the canonical edges, with both endpoint permissions."""

from uuid import UUID

from sqlalchemy import and_

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.repositories import virtual_table_relation as relation_repo
from app.repositories import virtual_table_repo
from app.repositories.virtual_table import SortClause
from app.schemas.virtual_table import ColumnDef, RecordList
from app.schemas.virtual_table_relation import BacklinkQuery
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.computed import read_through
from app.services.virtual_tables.formula import FormulaProblem, check_formula
from app.services.virtual_tables.record_access import with_record_access
from app.services.virtual_tables.records import RecordOperations
from app.services.virtual_tables.row_policy import view_expression
from app.services.virtual_tables.types import READ_THROUGH_LINK


def _without_broken_formulas(columns: list[ColumnDef]) -> list[ColumnDef]:
    """`columns`, with each live formula that no longer checks archived.

    One pass is enough: a formula never reads another formula.
    """

    def broken(column: ColumnDef) -> bool:
        if column.archived or column.type != "formula" or column.formula is None:
            return False
        try:
            check_formula(column.formula, column, columns)
        except FormulaProblem:
            return True
        return False

    return [
        column.model_copy(update={"archived": True, "revision": column.revision + 1})
        if broken(column)
        else column
        for column in columns
    ]


class RelationOperations(Operations):
    async def release_links_to(self, *, organization_id: UUID, table_id: UUID) -> None:
        """Remove every other table's link fields naming `table_id` before it is purged.

        Called by the purge, in its transaction, with the purged table already locked.
        A link to a table that will not exist names nothing, live or archived, so each
        referencing table gets one new schema version without those link columns or
        the lookups and rollups reading through them. A live formula that no longer
        checks against what remains is archived, as an edit leaving it out would.
        `sync_schema` then archives the removed definitions, and deleting the table
        cascades them and their edges away.
        """
        for source_id in await relation_repo.referencing_tables(
            self.db, organization_id=organization_id, target_table_id=table_id
        ):
            source = await virtual_table_repo.get_table(
                self.db, source_id, organization_id=organization_id, for_update=True
            )
            if source is None:
                continue
            columns = await self._columns(source)
            links = {
                column.id
                for column in columns
                if column.type == "link" and column.link_table_id == table_id
            }
            if not links:
                continue
            kept = [
                column
                for column in columns
                if column.id not in links
                and not (column.type in READ_THROUGH_LINK and column.link_column_id in links)
            ]
            version = source.schema_version + 1
            await virtual_table_repo.add_schema_version(
                self.db,
                table_id=source.id,
                version=version,
                columns=[
                    column.model_dump(mode="json") for column in _without_broken_formulas(kept)
                ],
                created_by=None,
            )
            await virtual_table_repo.update_table(
                self.db, table=source, update_data={"schema_version": version}
            )

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
