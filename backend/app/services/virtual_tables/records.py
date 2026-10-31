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

import csv
import io
import json
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import for_no_person, run_impersonated
from app.core.audit import current_impersonator
from app.core.exceptions import (
    AlreadyExistsError,
    AppException,
    ConcurrentChangeError,
    ExportTooLargeError,
    NotFoundError,
    RateLimitError,
)
from app.core.field_errors import field_problems
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, try_hold_name
from app.db.models.virtual_table import VirtualTable, VirtualTableRecord
from app.repositories import virtual_table_repo
from app.repositories import virtual_table_trigger as trigger_repo
from app.repositories.virtual_table import FilterClause, SearchClause, SortClause
from app.schemas.virtual_table import (
    MAX_COUNT,
    RECORD_METADATA_FIELDS,
    CellValue,
    ColumnDef,
    ExternalId,
    OperationKey,
    RecordBatchCreate,
    RecordBatchFailure,
    RecordBatchResult,
    RecordCount,
    RecordCountQuery,
    RecordCreate,
    RecordExportQuery,
    RecordFilter,
    RecordList,
    RecordQuery,
    RecordRead,
    RecordSort,
    RecordUpdate,
    RecordUpsert,
)
from app.services import rate_limit
from app.services.access import TABLE, resolve_access
from app.services.virtual_tables import quotas
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.computed import (
    LinkedTable,
    linked_cell_keys,
    linked_table_access,
    reach,
    read_through,
)
from app.services.virtual_tables.deadline import ReadDeadline
from app.services.virtual_tables.exceptions import (
    ArchivedColumnError,
    InvalidQueryError,
    InvalidRecordError,
    QuotaExceededError,
    RevisionConflictError,
    RevisionRequiredError,
)
from app.services.virtual_tables.receipts import DeleteOutcome, WriteOutcome, run_once
from app.services.virtual_tables.record_sources import source_for
from app.services.virtual_tables.types import (
    COLUMN_TYPES,
    OPTION_TYPES,
    SEARCHED_TYPES,
    CellProblem,
    validate_cell,
    validate_filter,
)
from app.services.workflow_execution import context as workflow_context

CREATED_EVENT = trigger_repo.CREATED_EVENT
UPDATED_EVENT = trigger_repo.UPDATED_EVENT
DELETED_EVENT = trigger_repo.DELETED_EVENT

_RECORD_TIMESTAMPS = ("created_at", "updated_at")


_EXTERNAL_ID = TypeAdapter(ExternalId)
_OPERATION_KEY = TypeAdapter(OperationKey)


def _external_id(value: str) -> str:
    """An external id as the routes accept it, for a caller that never went through one.

    The console, agent tools and workflow nodes call the service directly, so the limits
    live here as well: an id over 255 characters or holding NUL would otherwise reach
    PostgreSQL and come back as a database error.
    """
    try:
        return _EXTERNAL_ID.validate_python(value)
    except PydanticValidationError as invalid:
        raise _refused(invalid, "external_id") from None


def _operation_key(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _OPERATION_KEY.validate_python(value)
    except PydanticValidationError as invalid:
        raise _refused(invalid, "operation_key") from None


def _refused(invalid: PydanticValidationError, field: str) -> InvalidRecordError:
    problems = field_problems(invalid.errors(include_url=False, include_input=False), root=field)
    return InvalidRecordError([(problem["field"], problem["message"]) for problem in problems])


class _Unchanged(Exception):
    """An update that would change nothing, carrying the record as it already is.

    Raised from inside the write's savepoint on purpose: rolling it back is what removes
    the receipt the operation key had claimed, so a no-op leaves no receipt, no history row
    and no new revision. `_write` catches it and answers with the current record.
    """

    def __init__(self, record: RecordRead) -> None:
        super().__init__("The update changes nothing")
        self.record = record


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


def _changed_cells(
    before: dict[str, CellValue], after: dict[str, CellValue]
) -> dict[str, dict[str, CellValue]]:
    """The `before` and `after` of an update's history row: only the cells that changed.

    A full snapshot of each side would make one edit of one cell cost two copies of the
    record, however large, and the cost of repeating it would be the size of the record
    times the number of requests. A column missing from one side was empty there.
    """
    changed = [key for key in before.keys() | after.keys() if before.get(key) != after.get(key)]
    return {
        "before": {key: before[key] for key in changed if key in before},
        "after": {key: after[key] for key in changed if key in after},
    }


def _causation() -> dict[str, str | bool]:
    """The workflow run whose step is writing, when one is - the chain a table
    trigger's run joins, so a trigger that would start itself again is refused -
    and whether the run writing has no person or started under impersonation, which the run it
    starts inherits."""
    dispatching = workflow_context.active()
    causation: dict[str, str | bool] = (
        {} if dispatching is None else {"causation_run_id": str(dispatching.workflow_run_id)}
    )
    if for_no_person():
        causation["public_origin"] = True
    # An administrator's own write, or one by a run started under impersonation: the
    # run a trigger starts for it is impersonated too.
    if run_impersonated() or current_impersonator() is not None:
        causation["impersonated"] = True
    return causation


def _filters(columns: list[ColumnDef], filters: list[RecordFilter]) -> list[FilterClause]:
    by_id = {column.id: column for column in columns}
    clauses: list[FilterClause] = []
    for index, condition in enumerate(filters):
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
    return clauses


def _clauses(columns: list[ColumnDef], query: RecordQuery) -> tuple[list[FilterClause], SortClause]:
    by_id = {column.id: column for column in columns}
    clauses = _filters(columns, query.filters)
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


def check_query(columns: list[ColumnDef], filters: list[RecordFilter], sort: RecordSort) -> None:
    """Whether `filters` and `sort` can be answered by a table of `columns`.

    Raises:
        InvalidQueryError: The first filter, or the sort, that cannot, naming it by
            its path - `filters.2` or `sort.by`.
    """
    _clauses(columns, RecordQuery(filters=filters, sort=sort))


def _search(columns: list[ColumnDef], term: str | None) -> SearchClause | None:
    """What a search box's `term` looks for in this table, or `None` for no search.

    Only live columns are searched: an archived one is not on anyone's screen,
    and a match found there would look like a record matching nothing.
    """
    if not term:
        return None
    needle = term.casefold()
    live = [column for column in columns if not column.archived]
    options = tuple(
        (
            column.id,
            column.type == "multi_select",
            tuple(str(option.id) for option in column.options if needle in option.label.casefold()),
        )
        for column in live
        if column.type in OPTION_TYPES
    )
    return SearchClause(
        term=term,
        text_columns=tuple(column.id for column in live if column.type in SEARCHED_TYPES),
        options=tuple(entry for entry in options if entry[2]),
    )


EXPORT_MAX_BYTES = 4 * 1024 * 1024
"""Decoded JSON bytes per export page; row count alone cannot bound memory."""

EXPORT_BATCH = 500
"""Records an export reads at a time while it writes the CSV."""

# A cell a spreadsheet would read as a formula. Written as text instead, with a
# leading quote: an export opened in Excel must not run what somebody typed.
_FORMULA = re.compile(r"^[=+\-@\t\r]")


@dataclass(frozen=True)
class RecordExport:
    """A CSV export: what to call the file, and its lines as they are read."""

    filename: str
    lines: AsyncGenerator[str]


def _csv_line(cells: list[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow(cells)
    return buffer.getvalue()


def _export_cell(column: ColumnDef, record: RecordRead) -> str:
    """One cell of an export: a link by the names of its records, anything else as read."""
    if column.type == "link" and str(column.id) in record.links:
        return _neutralized("; ".join(linked.label for linked in record.links[str(column.id)]))
    return _cell_text(column, record.values.get(str(column.id)))


def _cell_text(column: ColumnDef, value: CellValue) -> str:
    """One cell as a person reads it: an option by its label, a yes/no as a word."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    labels = {str(option.id): option.label for option in column.options}
    if isinstance(value, list):
        # A lookup reads numbers and dates as well as text.
        text = "; ".join(labels.get(str(item), str(item)) for item in value)
    else:
        text = labels.get(value, value)
    return _neutralized(text)


def _neutralized(text: str) -> str:
    """`text` as a CSV cell: one a spreadsheet would run as a formula gets a leading quote."""
    return f"'{text}" if _FORMULA.match(text) else text


BOUND_CHUNK = 200
"""Records a page query measures the links of, and loads, at a time."""


@dataclass(frozen=True)
class BoundRows:
    """A page query's records as a binding reads them, within its record and byte limits."""

    records: list[dict[str, Any]]
    """Each record as the caller's `shape` made it, in the query's order."""
    sizes: list[int]
    """The bytes of each shaped record, as compact JSON."""
    bytes: int
    """`sum(sizes)`."""
    columns: list[ColumnDef]
    """The table's columns as read, archived ones included."""
    stopped_by: Literal["records", "bytes"] | None
    """Which limit left records out, or `None` when every record the query matches is here."""


def _referenced(values: Mapping[str, Any], links: Mapping[UUID, UUID]) -> dict[UUID, set[UUID]]:
    """The linked records a record's link cells name, by linked table."""
    referenced: dict[UUID, set[UUID]] = {}
    for column_id, table_id in links.items():
        named = referenced.setdefault(table_id, set())
        named.update(UUID(record_id) for record_id in values.get(str(column_id)) or [])
    return referenced


def _shaped_size(shaped: dict[str, Any]) -> int:
    return len(json.dumps(shaped, separators=(",", ":"), ensure_ascii=False).encode())


def _failure(index: int, refused: AppException) -> RecordBatchFailure:
    return RecordBatchFailure(
        index=index, code=refused.code, message=refused.message, details=refused.details
    )


class _BoundWalk:
    """What `read_bound` knows of the linked records as it walks a page query's records.

    Holds the link cells of one chunk at a time and the measured size of every linked
    record it has seen - ids and integers, never a linked record's cells.
    """

    def __init__(
        self,
        db: AsyncSession,
        ctx: AuthContext,
        table_id: UUID,
        columns: Sequence[ColumnDef],
        *,
        tables: Mapping[UUID, LinkedTable],
        targets: Mapping[UUID, frozenset[UUID]],
        reached: frozenset[UUID],
        deadline: ReadDeadline,
    ) -> None:
        self._db = db
        self._ctx = ctx
        self._table_id = table_id
        self._tables = tables
        self._targets = targets
        self._deadline = deadline
        self._links: dict[UUID, UUID] = {
            column.id: linked_table
            for column in columns
            if (linked_table := column.link_table_id) is not None
            and linked_table in tables
            and column.id in reached
            and column.type == "link"
            and not column.archived
        }
        self._sizes: dict[UUID, dict[UUID, int]] = {table_id: {} for table_id in tables}
        self._counted: dict[UUID, set[UUID]] = {table_id: set() for table_id in tables}
        self._referenced: dict[UUID, dict[UUID, set[UUID]]] = {}

    async def fitting(
        self, chunk: Sequence[tuple[UUID, int]], *, room: int
    ) -> tuple[list[UUID], int]:
        """The longest prefix of `chunk` whose own sizes, and those of the linked records
        it newly names, fit in `room` bytes, and what that prefix measures."""
        await self._measure_links([record_id for record_id, _size in chunk])
        fitting: list[UUID] = []
        spent = 0
        newly: dict[UUID, set[UUID]] = {table_id: set() for table_id in self._tables}
        for record_id, own in chunk:
            fresh = {
                table_id: ids - self._counted[table_id] - newly[table_id]
                for table_id, ids in self._referenced.get(record_id, {}).items()
            }
            cost = own + sum(
                self._sizes[table_id].get(linked_id, 0)
                for table_id, ids in fresh.items()
                for linked_id in ids
            )
            if spent + cost > room:
                break
            spent += cost
            fitting.append(record_id)
            for table_id, ids in fresh.items():
                newly[table_id] |= ids
        return fitting, spent

    async def load(self, record_ids: list[UUID], *, keys: Sequence[str]) -> list[RecordRead]:
        """These records with only the cells under `keys`, in the order given."""
        await self._deadline.arm(self._db)
        cells = await virtual_table_repo.get_record_cells_by_ids(
            self._db,
            record_ids,
            table_id=self._table_id,
            organization_id=self._ctx.organization_id,
            keys=keys,
        )
        by_id = {cell.id: cell for cell in cells}
        # A record deleted since the sizes were read is left out.
        return [
            RecordRead.model_validate(by_id[record_id])
            for record_id in record_ids
            if record_id in by_id
        ]

    def linked_ids(self, record_ids: Sequence[UUID]) -> dict[UUID, frozenset[UUID]]:
        """The measured linked records `record_ids` name, by visible linked table."""
        return {
            table_id: frozenset(
                linked_id
                for record_id in record_ids
                for linked_id in self._referenced.get(record_id, {}).get(table_id, ())
            )
            for table_id in self._tables
        }

    def count(self, record_ids: Sequence[UUID]) -> None:
        """Mark the linked records `record_ids` name as paid for."""
        for table_id, ids in self.linked_ids(record_ids).items():
            self._counted[table_id] |= ids

    async def _measure_links(self, record_ids: list[UUID]) -> None:
        """Read the chunk's link cells, then measure the linked records not yet measured."""
        self._referenced = {}
        if not self._links:
            return
        await self._deadline.arm(self._db)
        cells = await virtual_table_repo.get_record_cells_by_ids(
            self._db,
            record_ids,
            table_id=self._table_id,
            organization_id=self._ctx.organization_id,
            keys=sorted(str(column_id) for column_id in self._links),
        )
        self._referenced = {cell.id: _referenced(cell.values, self._links) for cell in cells}
        for table_id, linked in self._tables.items():
            unmeasured = {
                linked_id
                for referenced in self._referenced.values()
                for linked_id in referenced.get(table_id, ())
            } - self._sizes[table_id].keys()
            if not unmeasured:
                continue
            await self._deadline.arm(self._db)
            found = await virtual_table_repo.get_record_sizes_by_ids(
                self._db,
                unmeasured,
                table_id=table_id,
                organization_id=self._ctx.organization_id,
                keys=linked_cell_keys(linked, self._targets[table_id]),
            )
            # One deleted since costs nothing: it is not there to load.
            self._sizes[table_id].update(
                {linked_id: found.get(linked_id, 0) for linked_id in unmeasured}
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
        return await self._read_through(ctx, table, RecordRead.model_validate(record))

    async def get_record_by_external_id(
        self, ctx: AuthContext, table_id: UUID, external_id: str
    ) -> RecordRead:
        external_id = _external_id(external_id)
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        record = await virtual_table_repo.get_record_by_external_id(
            self.db, external_id, table_id=table.id, organization_id=ctx.organization_id
        )
        if record is None:
            raise NotFoundError(message="Record not found", details={"external_id": external_id})
        return await self._read_through(ctx, table, RecordRead.model_validate(record))

    async def record_exists(self, ctx: AuthContext, table_id: UUID, external_id: str) -> bool:
        """Whether a record with this external id exists, without reading it."""
        external_id = _external_id(external_id)
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
        columns = await self._columns(table)
        filters, sort = _clauses(columns, query)
        selected = None if query.columns is None else {str(item) for item in query.columns}
        if selected is not None:
            live = {str(column.id) for column in columns if not column.archived}
            if selected - live:
                raise InvalidQueryError("columns", "Choose live columns of this table")
        rows = await virtual_table_repo.list_records(
            self.db,
            table_id=table.id,
            organization_id=ctx.organization_id,
            filters=filters,
            search=_search(columns, query.search),
            sort=sort,
            skip=query.skip,
            limit=query.limit + 1,
        )
        items = await read_through(
            self.db,
            ctx,
            columns,
            [RecordRead.model_validate(row) for row in rows[: query.limit]],
        )
        if selected is not None:
            # Compute before projecting: a selected formula can depend on an omitted cell.
            items = [
                item.model_copy(
                    update={
                        "values": {
                            key: value for key, value in item.values.items() if key in selected
                        },
                        "links": {
                            key: value for key, value in item.links.items() if key in selected
                        },
                    }
                )
                for item in items
            ]
        return RecordList(
            items=items,
            skip=query.skip,
            limit=query.limit,
            has_more=len(rows) > query.limit,
        )

    async def read_bound(
        self,
        ctx: AuthContext,
        *,
        table_id: UUID,
        columns: list[ColumnDef],
        filters: list[RecordFilter],
        sort: RecordSort,
        column_ids: Sequence[UUID],
        shape: Callable[[RecordRead], dict[str, Any]],
        max_records: int,
        max_bytes: int,
        deadline: ReadDeadline,
    ) -> BoundRows:
        """A page query's records: the cells `column_ids` take, shaped, within the limits.

        The caller has already checked that `ctx` may read `table_id`, whose current
        `columns` these are, and every table the query reaches, in this transaction:
        they are not checked again here. Linked tables are read as `ctx`.

        Nothing past a limit is loaded. The query runs once and returns only each
        record's id and the size of the cells it takes. Records are then loaded
        `BOUND_CHUNK` at a time, as many as those sizes, and the sizes of the linked
        records they newly name, say fit what is left of `max_bytes`; a linked record
        counted once is free for later records, and one in a table `ctx` may not see is
        neither counted nor read. Whether a record is served is decided on its shaped
        size. Every statement is armed with `deadline` first.

        Raises:
            InvalidQueryError: The filters or the sort do not fit the table.
            DeadlineReached: The deadline left too little time for the next statement.
        """
        query = RecordQuery(filters=filters, sort=sort)
        clauses, order = _clauses(columns, query)
        reached = reach(columns, column_ids)
        keys = sorted(str(column_id) for column_id in reached.columns)
        await deadline.arm(self.db)
        measured = await virtual_table_repo.list_record_sizes(
            self.db,
            table_id=table_id,
            organization_id=ctx.organization_id,
            filters=clauses,
            search=None,
            sort=order,
            limit=max_records + 1,
            keys=keys,
        )
        tables: dict[UUID, LinkedTable | None] = {}
        if measured:
            for linked_id in reached.linked:
                tables[linked_id] = await linked_table_access(
                    self.db, ctx, linked_id, deadline=deadline
                )
        walk = _BoundWalk(
            self.db,
            ctx,
            table_id,
            columns,
            tables={
                linked_id: linked for linked_id, linked in tables.items() if linked is not None
            },
            targets=reached.linked,
            reached=reached.columns,
            deadline=deadline,
        )
        records: list[dict[str, Any]] = []
        sizes: list[int] = []
        used = 0
        # What the records loaded so far measured, linked records included. A linked
        # record shapes to a label or one rollup value, far smaller than what was read
        # to make it, so the room left is charged by this as well as by the shaped bytes:
        # the linked records counted so far are the only ones a later chunk reloads, so
        # no one load holds more than `max_bytes`.
        spent = 0
        stopped_by: Literal["records", "bytes"] | None = None
        serving = measured[:max_records]
        for start in range(0, len(serving), BOUND_CHUNK):
            chunk = serving[start : start + BOUND_CHUNK]
            fitting, cost = await walk.fitting(chunk, room=max_bytes - max(used, spent))
            spent += cost
            if fitting:
                cells = await walk.load(fitting, keys=keys)
                read = await read_through(
                    self.db,
                    ctx,
                    columns,
                    cells,
                    linked_keys=reached.linked,
                    linked_ids=walk.linked_ids(fitting),
                    linked_tables=tables,
                    deadline=deadline,
                )
                for record in read:
                    shaped = shape(record)
                    size = _shaped_size(shaped)
                    if used + size > max_bytes:
                        stopped_by = "bytes"
                        break
                    records.append(shaped)
                    sizes.append(size)
                    used += size
                walk.count(fitting)
            if len(fitting) < len(chunk):
                # The rest did not fit by its measured size, so it is never loaded.
                stopped_by = "bytes"
            if stopped_by is not None:
                break
        if stopped_by is None and len(measured) > max_records:
            stopped_by = "records"
        return BoundRows(
            records=records,
            sizes=sizes,
            bytes=used,
            columns=columns,
            stopped_by=stopped_by,
        )

    async def count_records(
        self, ctx: AuthContext, table_id: UUID, query: RecordCountQuery
    ) -> RecordCount:
        """How many records match the filters and search, counted up to `MAX_COUNT`.

        Raises:
            InvalidQueryError: A filter names something the table or the column type
                does not support.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        columns = await self._columns(table)
        counted = await virtual_table_repo.count_records(
            self.db,
            table_id=table.id,
            organization_id=ctx.organization_id,
            filters=_filters(columns, query.filters),
            search=_search(columns, query.search),
            cap=MAX_COUNT,
        )
        return RecordCount(count=min(counted, MAX_COUNT), capped=counted > MAX_COUNT)

    async def create_records(
        self, ctx: AuthContext, table_id: UUID, data: RecordBatchCreate
    ) -> RecordBatchResult:
        """Create each record on its own, reporting the ones refused rather than failing all.

        With `update_existing`, a record whose external id the table already holds
        updates that record instead - only the cells it names, as an upsert does - so
        a file can be imported again to bring the table up to date.

        Every record is written under its own savepoint, so one that does not fit its
        columns, repeats a taken external id, names an archived column or is too large is
        rolled back alone and answered with the code a single create would give. Once the
        table is full, the rest are refused with that quota without being tried. Each
        record created emits `table.record.created`, so a table trigger starts for it as
        for any other.

        Raises:
            NotFoundError: The table is out of reach.
            TableArchivedError: The table is archived.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, share=True)
        self._ensure_live(table)
        await quotas.lock_storage(self.db, ctx)
        created = updated = 0
        failed: list[RecordBatchFailure] = []
        for index, record in enumerate(data.records):
            try:
                async with self.db.begin_nested():
                    made = await self._create_one(ctx, table, record, update=data.update_existing)
                    await quotas.enforce_storage(self.db, ctx, table)
            except _Unchanged:
                # Already holds what the row says: nothing written, nothing to report.
                continue
            except QuotaExceededError as refused:
                if refused.details is not None and refused.details["quota"] in {
                    "records",
                    "storage_bytes",
                }:
                    failed.extend(_failure(at, refused) for at in range(index, len(data.records)))
                    break
                failed.append(_failure(index, refused))
            except (InvalidRecordError, ArchivedColumnError, AlreadyExistsError) as refused:
                failed.append(_failure(index, refused))
            else:
                if made:
                    created += 1
                else:
                    updated += 1
        return RecordBatchResult(created=created, updated=updated, failed=failed)

    async def _create_one(
        self, ctx: AuthContext, table: VirtualTable, data: RecordCreate, *, update: bool
    ) -> bool:
        """Create the record - or, with `update`, change the one holding its external id.

        Returns whether it was created. An update that changes nothing raises
        `_Unchanged`, as a single one does.
        """
        if data.external_id is not None:
            # As in `create_record`: an id that exists is answered as taken, not as a quota.
            await quotas.lock_record_count(self.db, table)
            existing = await self._lookup(ctx, table, data.external_id)
            if existing is not None and not update:
                raise self._already_exists(data.external_id)
            if existing is not None:
                await self._apply(ctx, table, existing, data.values, existing.revision)
                return False
        if await self._insert(ctx, table, data.external_id, data.values) is None:
            raise self._already_exists(data.external_id)
        return True

    async def export_records(
        self, ctx: AuthContext, table_id: UUID, query: RecordExportQuery
    ) -> RecordExport:
        """The records a query matches, in its order, as CSV lines headed by column labels.

        Everything the export can refuse is checked before the first line, so a
        refusal is an error response rather than a truncated file: a filter or column
        the table does not have, or more than `MAX_COUNT` records - narrowed with a
        filter or search, never cut short.

        Raises:
            InvalidQueryError: A filter, the sort or a column names something the table
                does not support.
            ExportTooLargeError: More records match than one export writes.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        columns = await self._columns(table)
        live = {column.id: column for column in columns if not column.archived}
        if query.columns is None:
            chosen = list(live.values())
        else:
            if any(column_id not in live for column_id in query.columns):
                raise InvalidQueryError("columns", "Export only the table's live columns")
            chosen = [live[column_id] for column_id in query.columns]
        filters, sort = _clauses(columns, RecordQuery(filters=query.filters, sort=query.sort))
        search = _search(columns, query.search)
        matching = await virtual_table_repo.count_records(
            self.db,
            table_id=table.id,
            organization_id=ctx.organization_id,
            filters=filters,
            search=search,
            cap=MAX_COUNT,
        )
        if matching > MAX_COUNT:
            raise ExportTooLargeError(
                message=(
                    f"An export writes at most {MAX_COUNT:,} records. "
                    "Narrow it with a filter or a search."
                ),
                details={"limit": MAX_COUNT},
            )

        decision = await rate_limit.consume_with_local_floor(
            surface="table_export",
            caller=f"org:{ctx.organization_id}",
            limit=rate_limit.Limit(attempts=10),
        )
        if not decision.allowed:
            raise RateLimitError(
                message="Too many table exports. Wait and try again.",
                details={"retry_after_seconds": decision.retry_after_seconds},
            )
        if not await try_hold_name(
            self.db, LockScope.VIRTUAL_TABLE_EXPORT_PER_ORG, str(ctx.organization_id)
        ):
            raise RateLimitError(
                message="This organization already has an export in progress.",
                details={"retry_after_seconds": 1},
            )

        async def lines() -> AsyncGenerator[str]:
            # A byte-order mark, so a spreadsheet reads the file as UTF-8.
            yield "\ufeff" + _csv_line(
                [_neutralized(column.label) for column in chosen]
                + (list(RECORD_METADATA_FIELDS) if query.include_metadata else [])
            )
            async with aclosing(
                virtual_table_repo.stream_export_records(
                    self.db,
                    table_id=table.id,
                    organization_id=ctx.organization_id,
                    filters=filters,
                    search=search,
                    sort=sort,
                    max_records=MAX_COUNT,
                    batch_records=EXPORT_BATCH,
                    batch_bytes=EXPORT_MAX_BYTES,
                )
            ) as batches:
                async for rows in batches:
                    read = await read_through(
                        self.db, ctx, columns, [RecordRead.model_validate(row) for row in rows]
                    )
                    for record in read:
                        yield _csv_line(
                            [_export_cell(column, record) for column in chosen]
                            + (
                                [
                                    record.created_at.isoformat(),
                                    (record.updated_at or record.created_at).isoformat(),
                                    str(record.created_by) if record.created_by else "",
                                    str(record.updated_by) if record.updated_by else "",
                                ]
                                if query.include_metadata
                                else []
                            )
                        )

        name = re.sub(r"[^A-Za-z0-9._-]+", "-", table.name).strip("-") or "table"
        return RecordExport(filename=f"{name}.csv", lines=lines())

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
            QuotaExceededError: The record is over the size limit, or the table is full.
            InvalidRecordError: A value does not fit its column.
            ArchivedColumnError: A value names an archived column.
            TableArchivedError: The table is archived.
        """
        operation_key = _operation_key(operation_key)
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, share=True)

        async def action() -> WriteOutcome:
            self._ensure_live(table)
            if data.external_id is not None:
                # Before the quota is consulted: a full table must still answer an id that
                # exists with ALREADY_EXISTS, not with a quota refusal about a record that would
                # never have been written. Taking the count lock first also lets a concurrent
                # create of the same id commit before this looks.
                await quotas.lock_record_count(self.db, table)
                if await self._lookup(ctx, table, data.external_id) is not None:
                    raise self._already_exists(data.external_id)
            record = await self._insert(ctx, table, data.external_id, data.values)
            if record is None:
                raise self._already_exists(data.external_id)
            return self._outcome(record, created=True)

        return await self._write(
            ctx,
            table,
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

        An update that leaves every cell as it is changes nothing: the revision stays, no
        history row or receipt is written, and the current record is returned.

        Raises:
            RevisionConflictError: Someone changed the record since it was read.
            NotFoundError: There is no such record.
        """
        return await self._update(
            ctx, table_id, record_id, data.values, data.expected_revision, operation_key
        )

    async def update_record_cells(
        self,
        ctx: AuthContext,
        table_id: UUID,
        record_id: UUID,
        values: dict[str, CellValue],
        *,
        operation_key: str | None = None,
    ) -> RecordWrite:
        """Change the named cells of a record at whatever revision it is at now.

        For a caller with no revision to send - a workflow step that never read the
        record. The revision is read under the record's lock, so nothing lands in
        between, and the request the operation key is tied to names no revision: a
        retry after the first write committed replays it, where one carrying the
        revision it read would be a different request.

        Raises:
            NotFoundError: There is no such record.
        """
        return await self._update(ctx, table_id, record_id, values, None, operation_key)

    async def _update(
        self,
        ctx: AuthContext,
        table_id: UUID,
        record_id: UUID,
        values: dict[str, CellValue],
        expected_revision: int | None,
        operation_key: str | None,
    ) -> RecordWrite:
        operation_key = _operation_key(operation_key)
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, share=True)

        async def action() -> WriteOutcome:
            self._ensure_live(table)
            record = await self._lock_record(ctx, table, record_id)
            revision = record.revision if expected_revision is None else expected_revision
            await self._apply(ctx, table, record, values, revision)
            return self._outcome(record, created=False)

        request: dict[str, Any] = {"table_id": table.id, "record_id": record_id, "values": values}
        if expected_revision is not None:
            request["expected_revision"] = expected_revision
        return await self._write(ctx, table, "record.update", operation_key, request, action)

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

        An update that would change nothing follows the rule of `update_record`.

        Raises:
            RevisionRequiredError: The record exists and no revision was sent.
            RevisionConflictError: The record exists at a different revision.
        """
        return await self._upsert(
            ctx,
            table_id,
            external_id,
            data.values,
            operation_key,
            expected_revision=data.expected_revision,
            at_current_revision=False,
        )

    async def upsert_record_cells(
        self,
        ctx: AuthContext,
        table_id: UUID,
        external_id: str,
        values: dict[str, CellValue],
        *,
        operation_key: str | None = None,
    ) -> RecordWrite:
        """Create the record with this external id, or change its cells at whatever
        revision it is at now - `update_record_cells` for a record found by its key.

        The request the operation key is tied to names no revision, so a retry
        replays the first write whether that one created the record or updated it.
        """
        return await self._upsert(
            ctx,
            table_id,
            external_id,
            values,
            operation_key,
            expected_revision=None,
            at_current_revision=True,
        )

    async def _upsert(
        self,
        ctx: AuthContext,
        table_id: UUID,
        external_id: str,
        values: dict[str, CellValue],
        operation_key: str | None,
        *,
        expected_revision: int | None,
        at_current_revision: bool,
    ) -> RecordWrite:
        external_id = _external_id(external_id)
        operation_key = _operation_key(operation_key)
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, share=True)

        async def action() -> WriteOutcome:
            self._ensure_live(table)
            existing = await self._lookup(ctx, table, external_id)
            if existing is None:
                # Take turns with other creates before deciding the id is new. A concurrent
                # upsert of the same id holds this lock until it commits, so once it is ours
                # the winner's row is visible: this call then updates it, and never counts a
                # table its rival just filled and is refused for it.
                await quotas.lock_record_count(self.db, table)
                existing = await self._lookup(ctx, table, external_id)
            if existing is None:
                created = await self._insert(ctx, table, external_id, values)
                if created is not None:
                    return self._outcome(created, created=True)
                # Another transaction took the external id between the lookup and
                # the insert. Its row is committed by now, so read and update it.
                existing = await self._lookup(ctx, table, external_id)
                if existing is None:
                    raise ConcurrentChangeError()
            revision = existing.revision if at_current_revision else expected_revision
            if revision is None:
                raise RevisionRequiredError(
                    record_id=existing.id, current_revision=existing.revision
                )
            await self._apply(ctx, table, existing, values, revision)
            return self._outcome(existing, created=False)

        request: dict[str, Any] = {
            "table_id": table.id,
            "external_id": external_id,
            "values": values,
        }
        if not at_current_revision:
            request["expected_revision"] = expected_revision
        return await self._write(ctx, table, "record.upsert", operation_key, request, action)

    async def delete_record(
        self,
        ctx: AuthContext,
        table_id: UUID,
        record_id: UUID,
        *,
        expected_revision: int | None,
        operation_key: str | None = None,
    ) -> None:
        """Delete a record, if it is still at `expected_revision`. Its history stays.

        `None` deletes it at whatever revision it is at now, read under its lock - for a
        caller with no revision to send, such as a workflow step that never read the
        record. The request the operation key is tied to then names no revision.

        The delete always succeeds, whatever the record's size. The history row keeps the whole
        record unless it is over the size limit (one that predates the limit, or written before
        it was lowered), in which case it keeps only a marker with the size; see
        `quotas.delete_snapshot`.

        With an operation key a retry of a delete that already succeeded returns
        normally instead of reporting the record missing.
        """
        operation_key = _operation_key(operation_key)
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, share=True)

        async def action() -> DeleteOutcome:
            self._ensure_live(table)
            record = await self._lock_record(ctx, table, record_id)
            if expected_revision is not None:
                self._check_revision(record, expected_revision)
            snapshot = quotas.delete_snapshot(record.values)
            await virtual_table_repo.add_history(
                self.db,
                organization_id=ctx.organization_id,
                table_id=table.id,
                record_id=record.id,
                revision=record.revision + 1,
                operation="delete",
                actor_user_id=ctx.subject_id,
                before=snapshot,
                after=None,
            )
            await self._tell_triggers(
                ctx, table, record, DELETED_EVENT, before=snapshot, after=None
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
                **({} if expected_revision is None else {"expected_revision": expected_revision}),
            },
            outcome_type=DeleteOutcome,
            action=action,
        )

    async def _write(
        self,
        ctx: AuthContext,
        table: VirtualTable,
        operation: str,
        operation_key: str | None,
        payload: dict[str, Any],
        action: Callable[[], Awaitable[WriteOutcome]],
    ) -> RecordWrite:
        try:
            async with self.db.begin_nested():
                await quotas.lock_storage(self.db, ctx)
                outcome, replayed = await run_once(
                    self.db,
                    ctx,
                    operation=operation,
                    operation_key=operation_key,
                    payload=payload,
                    outcome_type=WriteOutcome,
                    action=action,
                )
                if not replayed:
                    await quotas.enforce_storage(self.db, ctx, table)
        except _Unchanged as unchanged:
            return RecordWrite(
                record=await self._read_through(ctx, table, unchanged.record),
                created=False,
                replayed=False,
            )
        # Worked out after the receipt, never stored in it: a replay shows what the
        # linked records say now, as any other read would.
        return RecordWrite(
            record=await self._read_through(ctx, table, outcome.record),
            created=outcome.created,
            replayed=replayed,
        )

    async def _tell_triggers(
        self,
        ctx: AuthContext,
        table: VirtualTable,
        record: VirtualTableRecord,
        event_type: str,
        *,
        before: dict[str, Any],
        after: dict[str, Any] | None,
    ) -> None:
        """Queue a record's change or deletion for the table's triggers - when one listens.

        Unlike a creation, which is always queued, these are written only for a table
        a live trigger asks them of: every edit of every record would otherwise grow
        the outbox for no one. The event carries the whole record before and after,
        since its history row keeps only the cells that changed.
        """
        if not await trigger_repo.has_active(
            self.db, table_id=table.id, event=trigger_repo.EVENTS[event_type]
        ):
            return
        await virtual_table_repo.add_outbox(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            record_id=record.id,
            event_type=event_type,
            payload={
                "table_id": str(table.id),
                "record_id": str(record.id),
                "external_id": record.external_id,
                "schema_version": table.schema_version,
                "revision": record.revision,
                "actor_user_id": str(ctx.subject_id),
                "before": before,
                "after": after,
                **_causation(),
            },
        )

    async def _read_through(
        self, ctx: AuthContext, table: VirtualTable, record: RecordRead
    ) -> RecordRead:
        """One record with its links named and its lookups and rollups worked out."""
        return (await read_through(self.db, ctx, await self._columns(table), [record]))[0]

    async def _check_links(
        self, ctx: AuthContext, columns: list[ColumnDef], submitted: dict[str, CellValue]
    ) -> None:
        """Every record a submitted link names exists in the table it links to, which the
        writer can see - a link is not a way to learn which ids another table holds."""
        problems: list[tuple[str, str]] = []
        for column in columns:
            ids = submitted.get(str(column.id))
            if column.type != "link" or column.link_table_id is None or not isinstance(ids, list):
                continue
            target = await virtual_table_repo.get_table(
                self.db, column.link_table_id, organization_id=ctx.organization_id
            )
            if target is None or not await resolve_access(
                self.db, ctx, target, Perm.TABLES_VIEW, resource_type=TABLE
            ):
                problems.append((f"values.{column.id}", "The linked table cannot be reached"))
                continue
            found = await virtual_table_repo.get_records_by_ids(
                self.db,
                [UUID(str(item)) for item in ids],
                table_id=target.id,
                organization_id=ctx.organization_id,
            )
            missing = set(map(str, ids)) - {str(row.id) for row in found}
            if missing:
                problems.append(
                    (
                        f"values.{column.id}",
                        f"No record {sorted(missing)[0]} in the linked table",
                    )
                )
        if problems:
            raise InvalidRecordError(problems)

    @staticmethod
    def _already_exists(external_id: str | None) -> AlreadyExistsError:
        return AlreadyExistsError(
            message="A record with this external id already exists in the table",
            details={"external_id": external_id},
        )

    async def _lookup(
        self, ctx: AuthContext, table: VirtualTable, external_id: str
    ) -> VirtualTableRecord | None:
        """The record with this external id, locked for the write that follows."""
        return await virtual_table_repo.get_record_by_external_id(
            self.db,
            external_id,
            table_id=table.id,
            organization_id=ctx.organization_id,
            for_update=True,
        )

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
        columns = await self._columns(table)
        merged = _merge(columns, values, None)
        await self._check_links(ctx, columns, values)
        await quotas.enforce_record_size(ctx, table, merged)
        await quotas.enforce_record_count(self.db, ctx, table)
        record = await virtual_table_repo.insert_record(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            external_id=external_id,
            schema_version=table.schema_version,
            values=merged,
            created_by=ctx.subject_id,
            source=(await source_for(self.db, ctx)).stored(),
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
                **_causation(),
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
        """Update a locked record and write its history row.

        The revision is checked first, so a stale one is a conflict even when the values
        would have changed nothing. An update that changes nothing raises `_Unchanged`.
        """
        self._check_revision(record, expected_revision)
        before = dict(record.values)
        columns = await self._columns(table)
        merged = _merge(columns, values, before)
        if merged == before:
            # Nothing to record. Bumping the revision and keeping a full before-and-after
            # snapshot, and a receipt holding a whole copy, for a request that changed
            # nothing would let tiny repeated requests grow the shared database.
            raise _Unchanged(RecordRead.model_validate(record))
        await self._check_links(ctx, columns, values)
        await quotas.enforce_record_size(ctx, table, merged)
        await virtual_table_repo.update_record(
            self.db,
            record=record,
            values=merged,
            schema_version=table.schema_version,
            updated_by=ctx.subject_id,
            source=(await source_for(self.db, ctx)).stored(),
        )
        await virtual_table_repo.add_history(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            record_id=record.id,
            revision=record.revision,
            operation="update",
            actor_user_id=ctx.subject_id,
            **_changed_cells(before, merged),
        )
        await self._tell_triggers(ctx, table, record, UPDATED_EVENT, before=before, after=merged)
