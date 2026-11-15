"""Tables and their schemas: create, list, describe, rename, archive, restore, change columns."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.virtual_table import VirtualTable
from app.db.updates import writable
from app.repositories import table_view_repo, virtual_table_repo
from app.repositories import task as task_repo
from app.schemas.virtual_table import (
    MAX_LABEL,
    MAX_OPTIONS,
    CellValue,
    ColumnDef,
    ColumnTypeName,
    OperationKey,
    OptionDef,
    RowPolicyUpdate,
    SchemaUpdate,
    SchemaVersionList,
    SchemaVersionRead,
    TableCreate,
    TableList,
    TableListItem,
    TableRead,
    TableSummary,
    TableUpdate,
)
from app.services.access import TABLE, accessible_ids, visible_resource_ids
from app.services.task_access import table_audience
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.conversions import convert, option_labels
from app.services.virtual_tables.deadline import ReadDeadline
from app.services.virtual_tables.dependencies import find_dependents
from app.services.virtual_tables.exceptions import (
    InvalidSchemaError,
    SchemaDependencyError,
    SchemaVersionConflictError,
)
from app.services.virtual_tables.principals import principal_problems
from app.services.virtual_tables.quotas import enforce_storage, enforce_table_count, lock_storage
from app.services.virtual_tables.receipts import run_once
from app.services.virtual_tables.record_sources import source_for
from app.services.virtual_tables.row_policy import parse_policy
from app.services.virtual_tables.schema import SchemaDiff, build_columns, diff
from app.services.virtual_tables.types import COMPUTED_TYPES, READ_THROUGH_LINK, CellProblem

_OPERATION_KEY = TypeAdapter(OperationKey)


@dataclass(frozen=True)
class TableSource:
    """A table as a page query reads it: its name, whether it is archived, and its columns."""

    id: UUID
    name: str
    archived: bool
    columns: list[ColumnDef]
    """The columns of its current schema version, archived ones included."""


def _checked_key(value: str | None) -> str | None:
    """An operation key held to the limits a route puts on one, for a direct caller."""
    if value is None:
        return None
    try:
        return _OPERATION_KEY.validate_python(value)
    except PydanticValidationError as invalid:
        raise InvalidSchemaError(
            "operation_key", invalid.errors(include_url=False, include_input=False)[0]["msg"]
        ) from None


def _dump(columns: list[ColumnDef]) -> list[dict[str, object]]:
    return [column.model_dump(mode="json") for column in columns]


class TableOperations(Operations):
    """Everything about a table that is not one of its records."""

    async def create_table(
        self, ctx: AuthContext, data: TableCreate, *, operation_key: str | None = None
    ) -> TableRead:
        """Create a table with its first schema version.

        With an `operation_key` a retry returns the table the first call made
        rather than making a second one - what an agent tool call re-sent after a
        timeout, or a workflow step redispatched after a crash, needs. The key is
        the caller's, scoped to them like a record write's, and reusing it with a
        different table is refused.

        Raises:
            AuthorizationError: The caller lacks `tables:create`.
            AlreadyExistsError: A live table already has this name.
            QuotaExceededError: The organization already has as many tables as it may.
            InvalidSchemaError: The columns are inconsistent.
            IdempotencyKeyReuseError: The key was used before for a different table.
        """
        if not ctx.has(Perm.TABLES_CREATE):
            raise AuthorizationError(
                message="You cannot create tables", details={"required": [Perm.TABLES_CREATE.value]}
            )

        async def action() -> TableRead:
            columns = build_columns(data.columns, [], initial=True)
            await self._check_references(ctx, columns, [])
            await self._claim_name(ctx, data.name)
            await enforce_table_count(self.db, ctx)
            table = await virtual_table_repo.create_table(
                self.db,
                organization_id=ctx.organization_id,
                owner_user_id=ctx.subject_id,
                name=data.name,
                description=data.description,
                icon=data.icon,
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
            return self._read(table, columns, can_edit=await self._can_edit(ctx, table))

        created, _replayed = await run_once(
            self.db,
            ctx,
            operation="table.create",
            operation_key=_checked_key(operation_key),
            payload=data.model_dump(mode="json"),
            outcome_type=TableRead,
            action=action,
        )
        return created

    async def list_tables(
        self,
        ctx: AuthContext,
        *,
        include_archived: bool = False,
        search: str | None = None,
        sort: Literal["name", "updated_at"] = "name",
        skip: int = 0,
        limit: int = 50,
    ) -> TableList:
        """The tables this caller may see: their own, the org-visible ones and those shared."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=TABLE, perm=Perm.TABLES_VIEW
        )
        managed, excluded = await table_audience(self.db, ctx)
        items, total = await virtual_table_repo.list_tables_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=shared or [],
            managed_ids=managed,
            excluded_ids=excluded,
            include_archived=include_archived,
            search=search,
            sort=sort,
            skip=skip,
            limit=limit,
        )
        # One grant query for the whole page rather than one per row: `_can_edit`
        # is right for a single table, but a page of fifty would cost fifty
        # queries for a caller whose role alone does not already reach
        # `TABLES_EDIT` on every one of them.
        editable = await accessible_ids(self.db, ctx, items, Perm.TABLES_EDIT, resource_type=TABLE)
        # What each holds, the same way: a query for the page, not one per card.
        records = await virtual_table_repo.record_counts(
            self.db, organization_id=ctx.organization_id, table_ids=[item.id for item in items]
        )
        columns = await virtual_table_repo.current_columns(self.db, tables=items)
        summaries = [
            TableListItem.model_validate(
                {
                    **TableSummary.model_validate(item).model_dump(),
                    # An archived table refuses every write regardless of the grant
                    # (`_ensure_live`), so `can_edit` says so - this list is the only
                    # place `include_archived` surfaces one without a caller opening it.
                    "can_edit": item.id in editable and item.archived_at is None,
                    "record_count": records.get(item.id, 0),
                    "column_count": sum(
                        1 for column in columns.get(item.id, []) if not column.get("archived")
                    ),
                }
            )
            for item in items
        ]
        return TableList(items=summaries, total=total)

    async def describe_table(self, ctx: AuthContext, table_id: UUID) -> TableRead:
        """One table with the columns of its current schema."""
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        can_edit = await self._can_edit(ctx, table)
        return self._read(
            table,
            await self._columns(table),
            can_edit=can_edit,
            can_restore=await self._can_restore(ctx, table),
            can_manage=can_edit and await self._manages_board(ctx, table),
        )

    async def table_source(
        self, ctx: AuthContext, table_id: UUID, *, deadline: ReadDeadline | None = None
    ) -> TableSource:
        """The table as a page query reads it, if `ctx` may read it; an archived one too.

        With a `deadline`, each statement is armed with it first.

        Raises:
            NotFoundError: No such table in `ctx`'s organization, or one `ctx` may not read.
            DeadlineReached: Too little of `deadline` is left for the next statement.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW, deadline=deadline)
        return TableSource(
            id=table.id,
            name=table.name,
            archived=table.archived_at is not None,
            columns=await self._columns(table, deadline=deadline),
        )

    async def list_schema_versions(self, ctx: AuthContext, table_id: UUID) -> SchemaVersionList:
        """Every schema version the table has had, oldest first."""
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        versions = await virtual_table_repo.list_schema_versions(self.db, table_id=table.id)
        return SchemaVersionList(
            items=[SchemaVersionRead.model_validate(version) for version in versions]
        )

    async def update_table(self, ctx: AuthContext, table_id: UUID, data: TableUpdate) -> TableRead:
        """Rename a table or change its description."""
        # Locked, so an archive in flight is waited for and then seen: an unlocked read passes
        # `_ensure_live` on the old row and the update would rename a table archived a moment
        # ago. The row lock comes before the name lock `_claim_name` takes, the same order as
        # every other path that takes both (`create_table` locks no existing row).
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        self._ensure_live(table)
        await self._ensure_manages_board(ctx, table)
        changes = writable(data, over=VirtualTable)
        if data.default_view_id is not None:
            view = await table_view_repo.get(
                self.db, organization_id=ctx.organization_id, view_id=data.default_view_id
            )
            if view is None or view.table_id != table.id or view.visibility != "shared":
                raise BadRequestError(
                    message="Choose a shared saved view of this table as its default"
                )
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
        return self._read(table, await self._columns(table), can_edit=True)

    async def archive_table(self, ctx: AuthContext, table_id: UUID) -> TableRead:
        """Archive a table: its records stay readable and it refuses writes.

        Archiving twice is not an error. A table that workflows, views or triggers
        still depend on is refused, naming them.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        await self._ensure_manages_board(ctx, table)
        columns = await self._columns(table)
        # An archived table refuses every write, so neither answer below offers one. The
        # caller passed the edit check `unarchive_table` makes, so both offer the way back.
        if table.archived_at is not None:
            return self._read(table, columns, can_edit=False, can_restore=True)
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
        return self._read(table, columns, can_edit=False, can_restore=True)

    async def unarchive_table(self, ctx: AuthContext, table_id: UUID) -> TableRead:
        """Restore an archived table: it takes writes again, under the name it had.

        Asks for the same edit right archiving does. Its records, columns, views and
        history are as archiving left them.

        Raises:
            NotFoundError: The table is out of reach, or this caller may not edit it.
            AuthorizationError: A task board this caller may work on but not restore.
            BadRequestError: The table is not archived.
            AlreadyExistsError: A live table has taken its name since it was archived.
        """
        # The row lock before the name lock, the order `update_table` takes them in.
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        await self._ensure_manages_board(ctx, table)
        if table.archived_at is None:
            raise BadRequestError(
                message=f"Table '{table.name}' is not archived", details={"table_id": table.id}
            )
        try:
            await self._claim_name(ctx, table.name)
        except AlreadyExistsError:
            # An archived table cannot be renamed, so the name to change is the live one's.
            raise AlreadyExistsError(
                message=f"A table named '{table.name}' already exists. Rename it "
                "before restoring this one.",
                details={"name": table.name},
            ) from None
        table = await virtual_table_repo.update_table(
            self.db, table=table, update_data={"archived_at": None}
        )
        from app.services.task_execution import TaskExecution

        await TaskExecution(self.db).restored_table(table.id, ctx.organization_id)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.unarchived",
            target_type="table",
            target_id=str(table.id),
        )
        return self._read(table, await self._columns(table), can_edit=True)

    async def update_schema(
        self, ctx: AuthContext, table_id: UUID, data: SchemaUpdate
    ) -> TableRead:
        """Append the next schema version.

        A submission that builds to exactly the current columns changes nothing: no version
        is appended and the current table is returned. A stale `expected_version` is still a
        conflict, because it is checked first.

        Records are not rewritten, except for a column whose type changed: each record
        whose value reads differently in the new type takes the converted value, a new
        revision and a history entry for that cell, and no trigger hears of it. Otherwise
        each keeps the version it was written under and is read through the current
        columns, so a column added later is simply empty on older records.

        Raises:
            SchemaVersionConflictError: `expected_version` is not the current one.
            InvalidSchemaError: The columns are inconsistent, or a column that already
                has empty cells was made required.
            SchemaDependencyError: Something depends on a column this archives.
            QuotaExceededError: The values a type change rewrites, with their history,
                would take the organization past its table storage.
            AuthorizationError: A task board this caller may work on but not reshape.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        self._ensure_live(table)
        await self._ensure_manages_board(ctx, table)
        if data.expected_version != table.schema_version:
            raise SchemaVersionConflictError(
                expected_version=data.expected_version, current_version=table.schema_version
            )
        previous = await self._columns(table)
        columns = build_columns(data.columns, previous)
        from app.services.tasks import TaskLifecycle

        await TaskLifecycle(self.db).protect_schema(ctx, table_id, columns)
        if columns == previous:
            # Identical to what the table has, ids, order, labels and options included.
            # A new version, an audit row and a bumped `schema_version` would make every other
            # client's `expected_version` stale for a change that changed nothing.
            return self._read(table, previous, can_edit=True)
        await self._check_references(ctx, columns, previous)
        change = diff(previous, columns)
        self._refuse_policy_column_change(table, columns, change)
        await self._refuse_dependents(ctx, table, column_ids=change.archived | change.retyped)
        if change.retyped:
            # Rewritten values and their history count toward the organization's storage,
            # taken in the order a record write takes it; over the limit, nothing is written.
            await lock_storage(self.db, ctx)
            async with self.db.begin_nested():
                columns = await self._retype(ctx, table, previous, columns, change.retyped)
                await enforce_storage(self.db, ctx, table)
        await self._refuse_empty_required(table, columns, change.required)
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
        return self._read(table, columns, can_edit=True)

    async def set_row_policy(
        self, ctx: AuthContext, table_id: UUID, data: RowPolicyUpdate
    ) -> TableRead:
        """Set or clear a table's row-level access policy.

        Anyone holding `tables:edit` on the table may set it: the access
        decision is the service's, via `resolve_access`, so a grant holder
        is not refused by a route-level role gate before the service is
        reached. A managed board table and an archived table refuse.

        Raises:
            NotFoundError: The table is out of reach, or this caller may not edit it.
            BadRequestError: The table is a managed board table.
            InvalidSchemaError: A named column does not exist, is archived,
                or is not a user/multi_user (assignee) or link (project)
                column; or the projects table cannot be read.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        self._ensure_live(table)
        if await task_repo.for_table(self.db, table.id, ctx.organization_id) is not None:
            raise BadRequestError(
                message=f"Table '{table.name}' is a managed board table and takes no row policy",
                details={"table_id": table.id},
            )
        columns = await self._columns(table)
        if data.rule == "none":
            document: dict[str, object] | None = None
        else:
            await self._validate_row_policy(ctx, columns, data)
            document = data.model_dump(mode="json")
        table = await virtual_table_repo.update_table(
            self.db, table=table, update_data={"row_policy": document}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.row_policy_changed",
            target_type="table",
            target_id=str(table.id),
            details={"rule": data.rule},
        )
        return self._read(table, columns, can_edit=True)

    async def _validate_row_policy(
        self, ctx: AuthContext, columns: list[ColumnDef], data: RowPolicyUpdate
    ) -> None:
        """The columns a policy names exist, are live, and are the right kind.

        The project half names a link column on this table, a projects
        table the caller may view, and a members column on it. A projects
        table the caller cannot reach is an invalid policy, not a 404: the
        caller named a table they may not see, and the policy could not be
        honoured. An archived projects table is accepted: its records stay
        readable, so its membership still resolves.
        """
        by_id = {column.id: column for column in columns}
        for field in ("view_column_id", "edit_column_id"):
            column_id = getattr(data, field)
            column = by_id.get(column_id)
            if column is None:
                raise InvalidSchemaError(field, "No column with this id on the table")
            if column.archived:
                raise InvalidSchemaError(field, f"Column '{column.label}' is archived")
            if column.type not in ("user", "multi_user"):
                raise InvalidSchemaError(
                    field, f"Column '{column.label}' is {column.type}, not a user column"
                )
        if data.view_projects_table_id is None:
            return
        link = by_id.get(data.view_project_link_column_id)
        if link is None:
            raise InvalidSchemaError(
                "view_project_link_column_id", "No column with this id on the table"
            )
        if link.archived:
            raise InvalidSchemaError(
                "view_project_link_column_id", f"Column '{link.label}' is archived"
            )
        if link.type != "link" or link.link_table_id != data.view_projects_table_id:
            raise InvalidSchemaError(
                "view_project_link_column_id",
                f"Column '{link.label}' does not link to the projects table",
            )
        try:
            projects = await self._load_table(ctx, data.view_projects_table_id, Perm.TABLES_VIEW)
        except NotFoundError:
            raise InvalidSchemaError(
                "view_projects_table_id",
                "No projects table with this id that this caller may view",
            ) from None
        project_columns = await self._columns(projects)
        members = next(
            (
                column
                for column in project_columns
                if column.id == data.view_project_members_column_id
            ),
            None,
        )
        if members is None:
            raise InvalidSchemaError(
                "view_project_members_column_id",
                "No column with this id on the projects table",
            )
        if members.archived:
            raise InvalidSchemaError(
                "view_project_members_column_id", f"Column '{members.label}' is archived"
            )
        if members.type not in ("user", "multi_user"):
            raise InvalidSchemaError(
                "view_project_members_column_id",
                f"Column '{members.label}' is {members.type}, not a user column",
            )

    def _refuse_policy_column_change(
        self, table: VirtualTable, columns: list[ColumnDef], change: SchemaDiff
    ) -> None:
        """Refuse archiving or retyping a column a row policy drives.

        Archiving the assignee column would leave every row invisible to
        everyone but the bypass roles; retyping it away from a user column
        would leave the policy unreadable. Either way the fix is to clear
        the policy first, not to silently break it.
        """
        policy = parse_policy(table.row_policy)
        if policy is None:
            return
        driving: dict[UUID, tuple[str, ...]] = {
            policy.view_column_id: ("user", "multi_user"),
            policy.edit_column_id: ("user", "multi_user"),
        }
        if policy.view_project_link_column_id is not None:
            driving[policy.view_project_link_column_id] = ("link",)
        for index, column in enumerate(columns):
            if column.id in change.archived and column.id in driving:
                raise InvalidSchemaError(
                    f"columns.{index}.archived",
                    f"Column '{column.label}' drives the table's row policy. "
                    "Clear the policy before archiving it.",
                )
            if column.id in change.retyped and column.id in driving:
                allowed = driving[column.id]
                if column.type not in allowed:
                    raise InvalidSchemaError(
                        f"columns.{index}.type",
                        f"Column '{column.label}' drives the table's row policy and "
                        f"must stay a {' or '.join(allowed)} column. "
                        "Clear the policy before changing its type.",
                    )

    async def _retype(
        self,
        ctx: AuthContext,
        table: VirtualTable,
        previous: list[ColumnDef],
        columns: list[ColumnDef],
        retyped: frozenset[UUID],
    ) -> list[ColumnDef]:
        """Rewrite every record's value of each column whose type changed, or refuse.

        All of a change's values are converted before any is written, so a change
        some value does not survive writes nothing. Text that becomes a choice
        gains an option for each distinct value it holds. A value the conversion
        leaves as it was is not written, so its record keeps its revision.

        Raises:
            InvalidSchemaError: A value does not read as its column's new type, or
                text holds more distinct values than a choice column can have.
        """
        before = {column.id: column for column in previous}
        result = list(columns)
        rewrites: list[tuple[UUID, list[tuple[UUID, CellValue]], dict[UUID, CellValue]]] = []
        for index, column in enumerate(columns):
            if column.id not in retyped:
                continue
            old = before[column.id]
            held = await virtual_table_repo.column_values(
                self.db, table_id=table.id, column_id=column.id
            )
            if column.type == "single_select" and old.type in ("text", "long_text"):
                column = _with_choices(index, column, [value for _record, value in held])
                result[index] = column
            converted: list[tuple[UUID, CellValue]] = []
            earlier: dict[UUID, CellValue] = {}
            refused: list[CellValue] = []
            for record_id, value in held:
                try:
                    new = convert(value, old, column)
                except CellProblem:
                    refused.append(value)
                    continue
                if new is None and not column.nullable:
                    refused.append(value)
                    continue
                # `1 == True`, so a number becoming a checkbox must still be written.
                if type(new) is type(value) and new == value:
                    continue
                converted.append((record_id, new))
                earlier[record_id] = value
            if refused:
                raise InvalidSchemaError(
                    f"columns.{index}.type",
                    f"{len(refused)} records hold a value that does not read as {column.type}, "
                    f"such as {str(refused[0])[:40]!r}. Change them first, or add a new column.",
                )
            rewrites.append((column.id, converted, earlier))
        source = (await source_for(self.db, ctx)).stored()
        for column_id, converted, earlier in rewrites:
            revisions = await virtual_table_repo.rewrite_column(
                self.db,
                table_id=table.id,
                column_id=column_id,
                values=converted,
                updated_by=ctx.subject_id,
                source=source,
            )
            key = str(column_id)
            await virtual_table_repo.add_history_rows(
                self.db,
                organization_id=table.organization_id,
                table_id=table.id,
                operation="update",
                actor_user_id=ctx.subject_id,
                rows=[
                    (
                        record_id,
                        revisions[record_id],
                        {key: earlier[record_id]},
                        {} if value is None else {key: value},
                    )
                    for record_id, value in converted
                ],
            )
        return result

    async def _check_references(
        self, ctx: AuthContext, columns: list[ColumnDef], previous: list[ColumnDef]
    ) -> None:
        """Each new or changed link names a live table the caller can see, and each
        lookup and rollup a column of it that its reading suits.

        A column the change leaves as it was is not asked again: a linked table
        archived since, or a column it read archived since, leaves the column
        reading nothing rather than blocking every later edit of this table.
        """
        defaults = {
            str(column.id): column.default
            for column in columns
            if column.default is not None
            and (
                not previous
                or next((old.default for old in previous if old.id == column.id), None)
                != column.default
            )
        }
        problems = await principal_problems(self.db, ctx, columns, defaults)
        if problems:
            key, message = problems[0]
            index = next(index for index, column in enumerate(columns) if str(column.id) == key)
            raise InvalidSchemaError(f"columns.{index}.default", message)
        unchanged = {column.id: column for column in previous}
        # The table each link column reads, which `build_columns` checked every
        # lookup and rollup names.
        linked = {
            column.id: column.link_table_id
            for column in columns
            if column.type == "link" and column.link_table_id is not None
        }
        for index, column in enumerate(columns):
            if column.archived or unchanged.get(column.id) == column:
                continue
            if column.type == "link" and column.link_table_id is not None:
                await self._linked_table(ctx, column.link_table_id, f"columns.{index}")
            elif column.type in READ_THROUGH_LINK and column.link_column_id is not None:
                where = f"columns.{index}"
                target = await self._linked_table(ctx, linked[column.link_column_id], where)
                _check_reading(index, column, await self._columns(target))

    async def _linked_table(self, ctx: AuthContext, table_id: UUID, where: str) -> VirtualTable:
        try:
            table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        except NotFoundError:
            raise InvalidSchemaError(
                f"{where}.link_table_id", "That table does not exist or you cannot see it"
            ) from None
        if table.archived_at is not None:
            raise InvalidSchemaError(f"{where}.link_table_id", "That table is archived")
        return table

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
            # Table-wide by design, like the record-count quota: whether a
            # column may become required depends on every record, not only
            # the ones its caller may see under the table's row policy.
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
            caller=ctx,
        )
        if dependents:
            raise SchemaDependencyError(
                [
                    {"kind": dependent.kind, "id": dependent.id, "name": dependent.name}
                    for dependent in dependents
                ]
            )


_SUMMED: frozenset[ColumnTypeName] = frozenset({"number", "integer", "rating"})
_ORDERED: frozenset[ColumnTypeName] = frozenset({"number", "integer", "rating", "date", "datetime"})


def _check_reading(index: int, column: ColumnDef, target_columns: list[ColumnDef]) -> None:
    """The linked table's column a lookup or rollup reads exists, and suits what it does."""
    if column.target_column_id is None:  # a rollup that counts the links reads no column
        return
    where = f"columns.{index}.target_column_id"
    target = next((c for c in target_columns if c.id == column.target_column_id), None)
    if target is None or target.archived:
        raise InvalidSchemaError(where, "That is not a live column of the linked table")
    if target.type in COMPUTED_TYPES or target.type == "link":
        raise InvalidSchemaError(
            where, "A lookup reads a column holding values, not another link or worked-out one"
        )
    if column.aggregate in ("sum", "avg") and target.type not in _SUMMED:
        raise InvalidSchemaError(where, f"A {column.aggregate} reads a column of numbers")
    if column.aggregate in ("min", "max") and target.type not in _ORDERED:
        raise InvalidSchemaError(where, f"A {column.aggregate} reads a column of numbers or dates")


def _with_choices(index: int, column: ColumnDef, values: list[CellValue]) -> ColumnDef:
    """A text column becoming a choice, with an option for each distinct value it holds."""
    live = {option.label for option in column.options if not option.archived}
    missing = [label for label in option_labels(values) if label not in live]
    if len(column.options) + len(missing) > MAX_OPTIONS:
        raise InvalidSchemaError(
            f"columns.{index}.type",
            f"It holds {len(live) + len(missing)} different values, more than the "
            f"{MAX_OPTIONS} choices a column can have.",
        )
    if any(len(label) > MAX_LABEL for label in missing):
        raise InvalidSchemaError(
            f"columns.{index}.type",
            f"Some values are longer than {MAX_LABEL} characters, the most a choice can be.",
        )
    added = [OptionDef(id=uuid4(), label=label, archived=False) for label in missing]
    return column.model_copy(update={"options": [*column.options, *added]})
