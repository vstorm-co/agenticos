"""Tables and their schemas: create, list, describe, rename, archive, change columns."""

from datetime import UTC, datetime
from uuid import UUID

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.virtual_table import VirtualTable
from app.db.updates import writable
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import (
    ColumnDef,
    SchemaUpdate,
    SchemaVersionList,
    SchemaVersionRead,
    TableCreate,
    TableList,
    TableRead,
    TableSummary,
    TableUpdate,
)
from app.services.access import TABLE, visible_resource_ids
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.dependencies import find_dependents
from app.services.virtual_tables.exceptions import (
    InvalidSchemaError,
    SchemaDependencyError,
    SchemaVersionConflictError,
)
from app.services.virtual_tables.schema import build_columns, diff


def _dump(columns: list[ColumnDef]) -> list[dict[str, object]]:
    return [column.model_dump(mode="json") for column in columns]


class TableOperations(Operations):
    """Everything about a table that is not one of its records."""

    async def create_table(self, ctx: AuthContext, data: TableCreate) -> TableRead:
        """Create a table with its first schema version.

        Raises:
            AuthorizationError: The caller lacks `tables:create`.
            AlreadyExistsError: A live table already has this name.
            InvalidSchemaError: The columns are inconsistent.
        """
        if not ctx.has(Perm.TABLES_CREATE):
            raise AuthorizationError(
                message="You cannot create tables", details={"required": [Perm.TABLES_CREATE.value]}
            )
        columns = build_columns(data.columns, [])
        await self._claim_name(ctx, data.name)
        table = await virtual_table_repo.create_table(
            self.db,
            organization_id=ctx.organization_id,
            owner_user_id=ctx.subject_id,
            name=data.name,
            description=data.description,
            visibility=data.visibility,
        )
        await virtual_table_repo.add_schema_version(
            self.db,
            table_id=table.id,
            version=1,
            columns=_dump(columns),
            created_by=ctx.subject_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.created",
            target_type="table",
            target_id=str(table.id),
            details={"name": table.name, "columns": len(columns)},
        )
        return self._read(table, columns)

    async def list_tables(
        self,
        ctx: AuthContext,
        *,
        include_archived: bool = False,
        search: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> TableList:
        """The tables this caller may see: their own, the org-visible ones and those shared."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=TABLE, perm=Perm.TABLES_VIEW
        )
        items, total = await virtual_table_repo.list_tables_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=shared or [],
            include_archived=include_archived,
            search=search,
            skip=skip,
            limit=limit,
        )
        return TableList(items=[TableSummary.model_validate(item) for item in items], total=total)

    async def describe_table(self, ctx: AuthContext, table_id: UUID) -> TableRead:
        """One table with the columns of its current schema."""
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        return self._read(table, await self._columns(table))

    async def list_schema_versions(self, ctx: AuthContext, table_id: UUID) -> SchemaVersionList:
        """Every schema version the table has had, oldest first."""
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        versions = await virtual_table_repo.list_schema_versions(self.db, table_id=table.id)
        return SchemaVersionList(
            items=[SchemaVersionRead.model_validate(version) for version in versions]
        )

    async def update_table(self, ctx: AuthContext, table_id: UUID, data: TableUpdate) -> TableRead:
        """Rename a table or change its description."""
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT)
        self._ensure_live(table)
        changes = writable(data, over=VirtualTable)
        if "name" in changes and changes["name"] != table.name:
            await self._claim_name(ctx, changes["name"])
        table = await virtual_table_repo.update_table(self.db, table=table, update_data=changes)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.updated",
            target_type="table",
            target_id=str(table.id),
            details={"fields": sorted(changes)},
        )
        return self._read(table, await self._columns(table))

    async def archive_table(self, ctx: AuthContext, table_id: UUID) -> TableRead:
        """Archive a table: its records stay readable and it refuses writes.

        Archiving twice is not an error. A table that workflows, views or triggers
        still depend on is refused, naming them.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        columns = await self._columns(table)
        if table.archived_at is not None:
            return self._read(table, columns)
        await self._refuse_dependents(ctx, table, column_ids=None)
        table = await virtual_table_repo.update_table(
            self.db, table=table, update_data={"archived_at": datetime.now(UTC)}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.archived",
            target_type="table",
            target_id=str(table.id),
        )
        return self._read(table, columns)

    async def update_schema(
        self, ctx: AuthContext, table_id: UUID, data: SchemaUpdate
    ) -> TableRead:
        """Append the next schema version.

        Records are not rewritten. Each keeps the version it was written under and
        is read through the current columns, so a column added later is simply empty
        on older records.

        Raises:
            SchemaVersionConflictError: `expected_version` is not the current one.
            InvalidSchemaError: The columns are inconsistent, or a column that already
                has empty cells was made required.
            SchemaDependencyError: Something depends on a column this archives.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        self._ensure_live(table)
        if data.expected_version != table.schema_version:
            raise SchemaVersionConflictError(
                expected_version=data.expected_version, current_version=table.schema_version
            )
        previous = await self._columns(table)
        columns = build_columns(data.columns, previous)
        change = diff(previous, columns)
        await self._refuse_empty_required(table, columns, change.required)
        await self._refuse_dependents(ctx, table, column_ids=change.archived)
        version = table.schema_version + 1
        await virtual_table_repo.add_schema_version(
            self.db,
            table_id=table.id,
            version=version,
            columns=_dump(columns),
            created_by=ctx.subject_id,
        )
        table = await virtual_table_repo.update_table(
            self.db, table=table, update_data={"schema_version": version}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.schema_changed",
            target_type="table",
            target_id=str(table.id),
            details={"version": version, "archived_columns": len(change.archived)},
        )
        return self._read(table, columns)

    async def _claim_name(self, ctx: AuthContext, name: str) -> None:
        """Refuse a name a live table holds, serialized so two creates cannot both pass."""
        await hold_subject(self.db, LockScope.VIRTUAL_TABLE_NAMES_PER_ORG, ctx.organization_id)
        if await virtual_table_repo.get_live_table_by_name(
            self.db, name, organization_id=ctx.organization_id
        ):
            raise AlreadyExistsError(
                message=f"A table named '{name}' already exists. Choose a different name.",
                details={"name": name},
            )

    async def _refuse_empty_required(
        self, table: VirtualTable, columns: list[ColumnDef], required: frozenset[UUID]
    ) -> None:
        for index, column in enumerate(columns):
            if column.id in required and await virtual_table_repo.count_records_without_value(
                self.db, table_id=table.id, column_id=column.id
            ):
                raise InvalidSchemaError(
                    f"columns.{index}.nullable",
                    "Some records have no value for this column, so it cannot become required. "
                    "Fill them in first.",
                )

    async def _refuse_dependents(
        self, ctx: AuthContext, table: VirtualTable, *, column_ids: frozenset[UUID] | None
    ) -> None:
        if column_ids is not None and not column_ids:
            return
        dependents = await find_dependents(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            column_ids=column_ids,
        )
        if dependents:
            raise SchemaDependencyError(
                [{"kind": dependent.kind, "id": dependent.id} for dependent in dependents]
            )
