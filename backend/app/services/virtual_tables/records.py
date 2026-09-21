"""Records: read, list, create, update, delete and upsert by external id.

Every write is one unit: the record change, its history row, the created-event
outbox row and (when the caller named an operation key) the idempotency receipt
are flushed in the request's transaction and commit or roll back together. Nothing
here commits; the session's own boundary does.

Concurrency rests on three database facts rather than on checks made in Python:

- a record's external id is unique per table, so an insert that loses a race
  returns nothing (`insert_record`) and never creates a duplicate;
- an update or delete reads the row under `FOR UPDATE` and compares its revision,
  so of two writers holding the same `expected_revision` exactly one wins;
- a receipt claim is an insert against a unique key, so two requests with one
  operation key serialize on it.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.exceptions import AlreadyExistsError, ConcurrentChangeError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.virtual_table import VirtualTable, VirtualTableRecord
from app.repositories import virtual_table_repo
from app.repositories.virtual_table import FilterClause, SortClause
from app.schemas.virtual_table import (
    CellValue,
    ColumnDef,
    RecordCreate,
    RecordList,
    RecordQuery,
    RecordRead,
    RecordUpdate,
    RecordUpsert,
)
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.exceptions import (
    ArchivedColumnError,
    InvalidQueryError,
    InvalidRecordError,
    RevisionConflictError,
    RevisionRequiredError,
)
from app.services.virtual_tables.receipts import DeleteOutcome, WriteOutcome, run_once
from app.services.virtual_tables.types import (
    COLUMN_TYPES,
    CellProblem,
    validate_cell,
    validate_filter,
)

CREATED_EVENT = "table.record.created"

_RECORD_TIMESTAMPS = ("created_at", "updated_at")


@dataclass(frozen=True)
class RecordWrite:
    """The result of a create, update or upsert."""

    record: RecordRead
    created: bool
    replayed: bool
    """Whether this is the stored answer to an earlier request with the same operation key."""


def _merge(
    columns: list[ColumnDef], submitted: dict[str, CellValue], stored: dict[str, CellValue] | None
) -> dict[str, CellValue]:
    """The values a record will hold after this write, or the refusal.

    `stored` is `None` on a create: every column with a default that was not
    submitted takes it (one submitted as `null` stays empty). On an update only the submitted cells change, and a
    required column the record has never held takes its default, so a record
    written before a required column existed can still be edited. A cell sent as
    `null` is cleared, and cleared cells are not stored at all.
    """
    by_id = {str(column.id): column for column in columns}
    merged = dict(stored or {})
    problems: list[tuple[str, str]] = []
    for key, value in submitted.items():
        column = by_id.get(key)
        if column is None:
            problems.append((f"values.{key}", "That is not a column of this table"))
            continue
        if column.archived:
            raise ArchivedColumnError(key)
        try:
            cleaned = validate_cell(column, value)
        except CellProblem as problem:
            problems.append((f"values.{key}", str(problem)))
            continue
        if cleaned is None:
            merged.pop(key, None)
        else:
            merged[key] = cleaned
    for key, column in by_id.items():
        if column.archived or key in merged or key in submitted:
            # A cell the caller sent as `null` was decided: it stays empty rather
            # than taking the default, the same as it does on an update.
            continue
        if column.default is not None and (stored is None or not column.nullable):
            merged[key] = column.default
        elif not column.nullable:
            problems.append((f"values.{key}", "This column is required"))
    if problems:
        raise InvalidRecordError(problems)
    return merged


def _clauses(columns: list[ColumnDef], query: RecordQuery) -> tuple[list[FilterClause], SortClause]:
    by_id = {column.id: column for column in columns}
    clauses: list[FilterClause] = []
    for index, condition in enumerate(query.filters):
        column = by_id.get(condition.column_id)
        if column is None:
            raise InvalidQueryError(
                f"filters.{index}.column_id", "That is not a column of this table"
            )
        try:
            operand = validate_filter(column, condition.op, condition.value)
        except CellProblem as problem:
            raise InvalidQueryError(f"filters.{index}", str(problem)) from None
        clauses.append(
            FilterClause(
                column_id=column.id,
                kind=COLUMN_TYPES[column.type].kind,
                op=condition.op,
                value=operand,
            )
        )
    sort = query.sort
    if sort.by in _RECORD_TIMESTAMPS:
        return clauses, SortClause(direction=sort.direction, field=sort.by)
    try:
        sorted_by = by_id.get(UUID(sort.by))
    except ValueError:
        sorted_by = None
    if sorted_by is None:
        raise InvalidQueryError("sort.by", "Sort by created_at, updated_at or a column id")
    column_type = COLUMN_TYPES[sorted_by.type]
    if not column_type.sortable:
        raise InvalidQueryError("sort.by", f"A {sorted_by.type} column cannot be sorted")
    return clauses, SortClause(
        direction=sort.direction, column_id=sorted_by.id, kind=column_type.kind
    )


class RecordOperations(Operations):
    """Reading and writing the records of one table."""

    async def get_record(self, ctx: AuthContext, table_id: UUID, record_id: UUID) -> RecordRead:
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        record = await virtual_table_repo.get_record(
            self.db, record_id, table_id=table.id, organization_id=ctx.organization_id
        )
        if record is None:
            raise NotFoundError(message="Record not found", details={"record_id": record_id})
        return RecordRead.model_validate(record)

    async def get_record_by_external_id(
        self, ctx: AuthContext, table_id: UUID, external_id: str
    ) -> RecordRead:
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        record = await virtual_table_repo.get_record_by_external_id(
            self.db, external_id, table_id=table.id, organization_id=ctx.organization_id
        )
        if record is None:
            raise NotFoundError(message="Record not found", details={"external_id": external_id})
        return RecordRead.model_validate(record)

    async def record_exists(self, ctx: AuthContext, table_id: UUID, external_id: str) -> bool:
        """Whether a record with this external id exists, without reading it."""
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        return await virtual_table_repo.record_exists(
            self.db, external_id, table_id=table.id, organization_id=ctx.organization_id
        )

    async def list_records(
        self, ctx: AuthContext, table_id: UUID, query: RecordQuery | None = None
    ) -> RecordList:
        """A page of records in a total, repeatable order.

        The order is the requested sort and then the record id, so two callers
        paging the same table see the same sequence, and a record never appears
        on two pages of an unchanged table.

        Raises:
            InvalidQueryError: A filter or the sort names something the table or the
                column type does not support.
        """
        query = query or RecordQuery()
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        filters, sort = _clauses(await self._columns(table), query)
        rows = await virtual_table_repo.list_records(
            self.db,
            table_id=table.id,
            organization_id=ctx.organization_id,
            filters=filters,
            sort=sort,
            skip=query.skip,
            limit=query.limit + 1,
        )
        return RecordList(
            items=[RecordRead.model_validate(row) for row in rows[: query.limit]],
            skip=query.skip,
            limit=query.limit,
            has_more=len(rows) > query.limit,
        )

    async def create_record(
        self,
        ctx: AuthContext,
        table_id: UUID,
        data: RecordCreate,
        *,
        operation_key: str | None = None,
    ) -> RecordWrite:
        """Create a record at revision 1 and emit `table.record.created`.

        Raises:
            AlreadyExistsError: The external id is taken.
            InvalidRecordError: A value does not fit its column.
            ArchivedColumnError: A value names an archived column.
            TableArchivedError: The table is archived.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT)

        async def action() -> WriteOutcome:
            self._ensure_live(table)
            record = await self._insert(ctx, table, data.external_id, data.values)
            if record is None:
                raise AlreadyExistsError(
                    message="A record with this external id already exists in the table",
                    details={"external_id": data.external_id},
                )
            return self._outcome(record, created=True)

        return await self._write(
            ctx,
            "record.create",
            operation_key,
            {"table_id": table.id, **data.model_dump(mode="json")},
            action,
        )

    async def update_record(
        self,
        ctx: AuthContext,
        table_id: UUID,
        record_id: UUID,
        data: RecordUpdate,
        *,
        operation_key: str | None = None,
    ) -> RecordWrite:
        """Change the named cells of a record, if it is still at `expected_revision`.

        Raises:
            RevisionConflictError: Someone changed the record since it was read.
            NotFoundError: There is no such record.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT)

        async def action() -> WriteOutcome:
            self._ensure_live(table)
            record = await self._lock_record(ctx, table, record_id)
            await self._apply(ctx, table, record, data.values, data.expected_revision)
            return self._outcome(record, created=False)

        return await self._write(
            ctx,
            "record.update",
            operation_key,
            {"table_id": table.id, "record_id": record_id, **data.model_dump(mode="json")},
            action,
        )

    async def upsert_record(
        self,
        ctx: AuthContext,
        table_id: UUID,
        external_id: str,
        data: RecordUpsert,
        *,
        operation_key: str | None = None,
    ) -> RecordWrite:
        """Create the record with this external id, or update it, atomically.

        When no record has the external id it is created (and `table.record.created`
        is emitted); `expected_revision` is ignored. When one exists the call is an
        update and must carry `expected_revision`. Concurrent upserts of one external
        id produce one record: the loser finds it and either updates it (with a
        matching revision) or is told which revision to send.

        Raises:
            RevisionRequiredError: The record exists and no revision was sent.
            RevisionConflictError: The record exists at a different revision.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT)

        async def action() -> WriteOutcome:
            self._ensure_live(table)
            existing = await virtual_table_repo.get_record_by_external_id(
                self.db,
                external_id,
                table_id=table.id,
                organization_id=ctx.organization_id,
                for_update=True,
            )
            if existing is None:
                created = await self._insert(ctx, table, external_id, data.values)
                if created is not None:
                    return self._outcome(created, created=True)
                # Another transaction took the external id between the lookup and
                # the insert. Its row is committed by now, so read and update it.
                existing = await virtual_table_repo.get_record_by_external_id(
                    self.db,
                    external_id,
                    table_id=table.id,
                    organization_id=ctx.organization_id,
                    for_update=True,
                )
                if existing is None:
                    raise ConcurrentChangeError()
            if data.expected_revision is None:
                raise RevisionRequiredError(
                    record_id=existing.id, current_revision=existing.revision
                )
            await self._apply(ctx, table, existing, data.values, data.expected_revision)
            return self._outcome(existing, created=False)

        return await self._write(
            ctx,
            "record.upsert",
            operation_key,
            {"table_id": table.id, "external_id": external_id, **data.model_dump(mode="json")},
            action,
        )

    async def delete_record(
        self,
        ctx: AuthContext,
        table_id: UUID,
        record_id: UUID,
        *,
        expected_revision: int,
        operation_key: str | None = None,
    ) -> None:
        """Delete a record, if it is still at `expected_revision`. Its history stays.

        With an operation key a retry of a delete that already succeeded returns
        normally instead of reporting the record missing.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT)

        async def action() -> DeleteOutcome:
            self._ensure_live(table)
            record = await self._lock_record(ctx, table, record_id)
            self._check_revision(record, expected_revision)
            await virtual_table_repo.add_history(
                self.db,
                organization_id=ctx.organization_id,
                table_id=table.id,
                record_id=record.id,
                revision=record.revision + 1,
                operation="delete",
                actor_user_id=ctx.subject_id,
                before=dict(record.values),
                after=None,
            )
            await virtual_table_repo.delete_record(self.db, record)
            return DeleteOutcome(record_id=record_id)

        await run_once(
            self.db,
            ctx,
            operation="record.delete",
            operation_key=operation_key,
            payload={
                "table_id": table.id,
                "record_id": record_id,
                "expected_revision": expected_revision,
            },
            outcome_type=DeleteOutcome,
            action=action,
        )

    async def _write(
        self,
        ctx: AuthContext,
        operation: str,
        operation_key: str | None,
        payload: dict[str, Any],
        action: Callable[[], Awaitable[WriteOutcome]],
    ) -> RecordWrite:
        outcome, replayed = await run_once(
            self.db,
            ctx,
            operation=operation,
            operation_key=operation_key,
            payload=payload,
            outcome_type=WriteOutcome,
            action=action,
        )
        return RecordWrite(record=outcome.record, created=outcome.created, replayed=replayed)

    @staticmethod
    def _outcome(record: VirtualTableRecord, *, created: bool) -> WriteOutcome:
        return WriteOutcome(created=created, record=RecordRead.model_validate(record))

    async def _insert(
        self,
        ctx: AuthContext,
        table: VirtualTable,
        external_id: str | None,
        values: dict[str, CellValue],
    ) -> VirtualTableRecord | None:
        """Insert a record with its history and created event, or `None` if the id is taken."""
        merged = _merge(await self._columns(table), values, None)
        record = await virtual_table_repo.insert_record(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            external_id=external_id,
            schema_version=table.schema_version,
            values=merged,
            created_by=ctx.subject_id,
        )
        if record is None:
            return None
        await virtual_table_repo.add_history(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            record_id=record.id,
            revision=record.revision,
            operation="create",
            actor_user_id=ctx.subject_id,
            before=None,
            after=merged,
        )
        await virtual_table_repo.add_outbox(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            record_id=record.id,
            event_type=CREATED_EVENT,
            payload={
                "table_id": str(table.id),
                "record_id": str(record.id),
                "external_id": external_id,
                "schema_version": table.schema_version,
                "revision": record.revision,
            },
        )
        return record

    async def _lock_record(
        self, ctx: AuthContext, table: VirtualTable, record_id: UUID
    ) -> VirtualTableRecord:
        record = await virtual_table_repo.get_record(
            self.db,
            record_id,
            table_id=table.id,
            organization_id=ctx.organization_id,
            for_update=True,
        )
        if record is None:
            raise NotFoundError(message="Record not found", details={"record_id": record_id})
        return record

    @staticmethod
    def _check_revision(record: VirtualTableRecord, expected_revision: int) -> None:
        if record.revision != expected_revision:
            raise RevisionConflictError(
                record_id=record.id,
                expected_revision=expected_revision,
                current_revision=record.revision,
            )

    async def _apply(
        self,
        ctx: AuthContext,
        table: VirtualTable,
        record: VirtualTableRecord,
        values: dict[str, CellValue],
        expected_revision: int,
    ) -> None:
        """Update a locked record and write its history row."""
        self._check_revision(record, expected_revision)
        before = dict(record.values)
        merged = _merge(await self._columns(table), values, before)
        await virtual_table_repo.update_record(
            self.db,
            record=record,
            values=merged,
            schema_version=table.schema_version,
            updated_by=ctx.subject_id,
        )
        await virtual_table_repo.add_history(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            record_id=record.id,
            revision=record.revision,
            operation="update",
            actor_user_id=ctx.subject_id,
            before=before,
            after=merged,
        )
