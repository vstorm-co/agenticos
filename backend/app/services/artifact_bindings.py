"""Page queries: what a page's bindings read, resolved at publish and checked on every load.

A binding is a page query - a table, filters, a sort, a limit and the fields the page
reads, each a column of that table - resolved to ids when a version is published, and
stored on it with its reach: the revision of every column the query reaches, through
formulas, lookups, rollups and links; every table it reaches; and the column each
linked table a link field reads names its records by. Nothing points at a saved view:
a binding that names one copies its filters and sort, and editing the view later
changes nothing on the page.

Everyone who opens the page reads the same records: the query, read with the access
of the page's owner. So at publish `check_bindings` holds the person behind the run to
reading every table the query reaches - they cannot bind what they cannot read - and,
for a binding the publish changes, the page's owner too. On every load `page_source`
checks the owner again, and compares the reach with the tables as they are now: a
column whose meaning changed, an archived column or table, or a linked table naming its
records by another column, and that binding is served nothing, with the reason, until
it is published again. Never widened, never read best-effort.

`disclose` says a query in words. It is the one place that wording is written: the
publish result shows it to the model, and it is what a page's owner will consent to.

This module also shapes what a page load is served (`page_data`): each record as its
id and the binding's named fields, nothing else, and one byte budget for the page,
shared fairly among its bindings.

The spec's table grants arrive as a plain mapping; this module never imports the
agents package.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.schemas.artifact import (
    ArtifactBinding,
    BindingData,
    BindingDisclosure,
    BindingReach,
    BindingRequest,
    BoundField,
)
from app.schemas.virtual_table import (
    MAX_FILTERS,
    CellValue,
    ColumnDef,
    RecordFilter,
    RecordRead,
    RecordSort,
)
from app.services.virtual_tables import (
    BoundRows,
    ReadDeadline,
    TableSource,
    TableViewService,
    VirtualTableService,
    named_by,
    reach,
)
from app.services.virtual_tables.exceptions import InvalidQueryError, TableArchivedError
from app.services.virtual_tables.formula import references
from app.services.virtual_tables.presentation import filters_by_label, readable
from app.services.virtual_tables.records import check_query
from app.services.virtual_tables.types import OPTION_TYPES, READ_THROUGH_LINK

Reason = Literal[
    "awaiting_consent",
    "creator_gone",
    "creator_lost_access",
    "source_changed",
    "not_current",
    "timeout",
]
"""Why a page load serves a binding nothing.

`creator_gone`: the page's owner is no longer an active member. `creator_lost_access`:
they can no longer read a table the query reaches. `source_changed`: a column or table
the query reaches changed since it was published. `awaiting_consent`: the viewer is
not yet served the page's data at all."""

_NAME = re.compile(r"[a-z_][a-z0-9_]{0,63}")
_PATTERN = "`^[a-z_][a-z0-9_]{0,63}$`"
_FIELD = re.compile(r"(?!\d)\w+(?: \w+)*")
"""A field name: words of letters in any case or script, digits and `_`, one space
between words, not starting with a digit. A model names a field after its column's
label - `Title`, `Created At` - and the page reads exactly the key it declared, so
the case is the page's business. A field name reaches the page only as a key of the
JSON its data arrives in, never in its markup; the binding name, which is written
into the page's script, keeps `_NAME`."""
_RESERVED_FIELDS = frozenset({"id", "__proto__", "constructor", "prototype"})
"""Names a page script reads every record by, or that would reach an object's prototype."""
_RESERVED_NAMES = frozenset({"__proto__", "constructor", "prototype"})
"""Binding names a page script would reach an object's prototype by."""
MAX_FIELDS = 50
DEFAULT_LIMIT = 1_000
"""The records a query serves when it names no `limit`, within `ARTIFACT_DATA_MAX_RECORDS`."""
_VIEWS_PER_TABLE = 100
"""The views of one table looked through for a name: the most `list_views` gives at once."""
NO_PERSON = "Only a run acting for a member can bind a page to data."
HINT = (
    " Take a view's id from `list_views` and a table's from `list_tables`, never from "
    "memory; to keep a page's current bindings, leave `bindings` out."
)
KEPT = "kept"
"""What the publish result says of a binding carried from the previous version.

Its query is not said again: a carried binding is not read for the run, whose person
may not read its tables."""
_RECORD_TIMES = {"created_at": "when created", "updated_at": "when last changed"}
_OPERATORS = {
    "eq": "is",
    "ne": "is not",
    "lt": "is less than",
    "lte": "is at most",
    "gt": "is more than",
    "gte": "is at least",
    "contains": "contains",
    "starts_with": "starts with",
    "in": "is one of",
}


@dataclass(frozen=True)
class BindingCheck:
    """One binding's outcome at publish: what it resolves to, and the problem, if any."""

    name: str
    binding: ArtifactBinding | None
    """The resolved query; `None` when it could not be resolved."""
    problem: str | None
    """Text for the model, safe for whoever the run acts for to read; `None` when fine."""
    changed: bool
    """Whether it differs from the stored binding of that name, reach included. A
    binding carried forward, or resolving to exactly the stored one, is not changed."""
    disclosure: BindingDisclosure | None = None
    """The query in words, for one the run's person resolved; `None` for one carried."""


@dataclass(frozen=True)
class Refused:
    """Why a restored query cannot stand, in a sentence for the person restoring it."""

    message: str
    forbidden: bool
    """Whether it is about access - someone cannot read a table - rather than a query
    the tables can no longer answer."""


@dataclass(frozen=True)
class _Start:
    """Where a query starts: its table, and the filters and sort a view gave it."""

    source: TableSource
    filters: list[RecordFilter]
    sort: RecordSort


@dataclass(frozen=True)
class _Query:
    """A query resolved to ids, before its reach is known."""

    name: str
    source: TableSource
    filters: list[RecordFilter]
    sort: RecordSort
    limit: int
    fields: dict[str, UUID]


async def check_bindings(
    db: AsyncSession,
    *,
    requested: Mapping[str, BindingRequest] | None,
    previous: Sequence[ArtifactBinding],
    person: AuthContext | None,
    owner: AuthContext | None,
    grants: Mapping[UUID, frozenset[str]],
) -> list[BindingCheck]:
    """Check a page version's bindings, one outcome per binding, in the order given.

    `requested` is what the model sent, replacing `previous` whole; `None` carries
    `previous` forward exactly as stored, its reach included, and needs no person.

    Each requested binding is resolved as `person`, who must read every table its query
    reaches; `grants` is the spec's operations per table id, and each of those tables
    needs `read` there too. One that differs from the stored binding of its name -
    new, or reaching other columns or revisions - must also be readable by `owner`,
    the page's owner as the member they are now: `None` when nobody active owns it.
    When `owner` is `person`, that is the same check. A run with no person binds
    nothing.
    """
    if requested is None:
        return [BindingCheck(prior.name, prior, None, False) for prior in previous]
    if person is None:
        return [BindingCheck(name, None, NO_PERSON, True) for name in requested]
    cap = settings.ARTIFACT_DATA_MAX_BINDINGS
    if len(requested) > cap:
        problem = f"A page takes at most {cap} bindings; this one has {len(requested)}."
        return [BindingCheck(name, None, problem, True) for name in requested]
    stored = {binding.name: binding for binding in previous}
    service = VirtualTableService(db)
    views = TableViewService(db)
    checks: list[BindingCheck] = []
    for name, request in requested.items():
        resolved = await _resolve(service, views, person, name, request, grants)
        if isinstance(resolved, str):
            checks.append(BindingCheck(name, None, resolved, True))
            continue
        binding, sources = resolved
        prior = stored.get(name)
        changed = prior is None or binding != prior
        problem = await _owner_problem(service, owner, person, name, sources) if changed else None
        if problem is not None:
            checks.append(BindingCheck(name, None, problem, True))
            continue
        checks.append(BindingCheck(name, binding, None, changed, disclose(binding, sources)))
    return checks


async def reresolve(
    db: AsyncSession,
    binding: ArtifactBinding,
    *,
    person: AuthContext,
    owner: AuthContext | None,
) -> ArtifactBinding | Refused:
    """A stored query with its reach taken again from the tables now, for a restore.

    The query - table, filters, sort, limit and fields - is kept; what it reaches and
    at which revisions is read afresh, so a restore is a changed query whenever the
    tables moved on. Its filters and sort must still be ones the table answers, as at
    publish: a column converted since may no longer take them. `person`, who is
    restoring, and `owner` must both read every table it reaches. An archived column
    or table is kept in the reach, and the page serves the binding nothing until it
    is published again.

    Returns:
        The binding with its new reach, or why it cannot stand.
    """
    service = VirtualTableService(db)
    try:
        source = await service.table_source(person, binding.table_id)
    except NotFoundError:
        return Refused(f"Binding {binding.name} reads a table you can't read.", forbidden=True)
    unanswered = _invalid(binding.name, source, binding.filters, binding.sort, viewed=0)
    if unanswered is not None:
        return Refused(unanswered, forbidden=False)
    query = _Query(
        binding.name, source, binding.filters, binding.sort, binding.limit, binding.fields
    )
    reached = await _reach(service, person, query, grants=None)
    if isinstance(reached, str):
        return Refused(reached, forbidden=True)
    found, sources = reached
    problem = await _owner_problem(service, owner, person, binding.name, sources)
    if problem is not None:
        return Refused(problem, forbidden=True)
    return binding.model_copy(update={"reach": found})


async def _resolve(
    service: VirtualTableService,
    views: TableViewService,
    person: AuthContext,
    name: str,
    request: BindingRequest,
    grants: Mapping[UUID, frozenset[str]],
) -> tuple[ArtifactBinding, dict[UUID, TableSource]] | str:
    """A requested binding as its query, resolved as `person`, and the tables it reaches."""
    if not _NAME.fullmatch(name):
        return f"Binding name {name[:64]!r} must match {_PATTERN}."
    if name in _RESERVED_NAMES:
        return f"Binding name {name} is reserved; choose another."
    start = await _start(service, views, person, name, request, grants)
    if isinstance(start, str):
        return start
    query = _query(name, request, start)
    if isinstance(query, str):
        return query
    reached = await _reach(service, person, query, grants=grants)
    if isinstance(reached, str):
        return reached
    found, sources = reached
    binding = ArtifactBinding(
        name=name,
        table_id=query.source.id,
        filters=query.filters,
        sort=query.sort,
        limit=query.limit,
        fields=query.fields,
        reach=found,
    )
    return binding, sources


async def _start(
    service: VirtualTableService,
    views: TableViewService,
    person: AuthContext,
    name: str,
    request: BindingRequest,
    grants: Mapping[UUID, frozenset[str]],
) -> _Start | str:
    """The table a query reads, and what a view it names gives it to start from."""
    if request.view is not None and request.table is not None:
        return f"Binding {name}: name its `view` or its `table`, not both."
    filters: list[RecordFilter] = []
    sort = RecordSort()
    table_id: UUID | str
    if request.view is not None:
        view_id = await _view_id(views, person, name, request.view, grants)
        if isinstance(view_id, str):
            return view_id
        try:
            bound = await views.find_view(person, view_id)
        except NotFoundError:
            return _not_found("View", view_id)
        except TableArchivedError:
            return f"Binding {name}: view {view_id} is on an archived table."
        view = bound.view.name
        if bound.config.search:
            return (
                f"Binding {name}: view {view!r} searches for {bound.config.search!r}, and a page "
                "can't copy a search - it matches more as columns are added. Name a view "
                "without one, or the `table` with `filters`."
            )
        if bound.filters_dropped:
            return (
                f"Binding {name}: a filter of view {view!r} names a column that is no longer "
                "live, so the view matches more than it was saved to. Fix the view, or name "
                "the `table` with `filters`."
            )
        table_id = bound.table_id
        filters, sort = list(bound.config.filters), bound.config.sort
    elif request.table is not None:
        table_id = await _table_id(service, person, name, request.table, grants)
    else:
        return f"Binding {name}: name the `view` or the `table` it reads."
    if isinstance(table_id, str):
        return table_id
    if "read" not in grants.get(table_id, ()):
        return f"Binding {name}: this agent is not granted read on table {table_id}."
    try:
        source = await service.table_source(person, table_id)
    except NotFoundError:
        return _not_found("Table", table_id)
    if source.archived:
        return f"Binding {name}: table {source.name} is archived."
    return _Start(source=source, filters=filters, sort=sort)


async def _view_id(
    views: TableViewService,
    person: AuthContext,
    name: str,
    view: UUID | str,
    grants: Mapping[UUID, frozenset[str]],
) -> UUID | str:
    """The view a binding names, by id or by name; text when it names none or several.

    A name is matched ignoring case, among the views `person` sees - their own and
    the shared ones - on the tables the spec grants `read`. A view anyone else could
    not see is never matched, so a name that misses reads the same whether such a
    view exists or not.
    """
    if isinstance(view, UUID):
        return view
    as_id = _as_uuid(view)
    if as_id is not None:
        return as_id
    wanted = view.casefold()
    found: list[UUID] = []
    for table_id, operations in grants.items():
        if "read" not in operations:
            continue
        try:
            listed = await views.list_views(person, table_id, limit=_VIEWS_PER_TABLE)
        except NotFoundError:
            continue
        found += [item.id for item in listed.items if item.name.casefold() == wanted]
    return _one(name, "saved view", view, found)


async def _table_id(
    service: VirtualTableService,
    person: AuthContext,
    name: str,
    table: UUID | str,
    grants: Mapping[UUID, frozenset[str]],
) -> UUID | str:
    """The table a binding names, by id or by name; text when it names none or several.

    A name is matched ignoring case, among the live tables the spec grants `read` that
    `person` may read.
    """
    if isinstance(table, UUID):
        return table
    as_id = _as_uuid(table)
    if as_id is not None:
        return as_id
    wanted = table.casefold()
    found: list[UUID] = []
    for table_id, operations in grants.items():
        if "read" not in operations:
            continue
        try:
            source = await service.table_source(person, table_id)
        except NotFoundError:
            continue
        if not source.archived and source.name.casefold() == wanted:
            found.append(source.id)
    return _one(name, "table", table, found)


def _one(name: str, kind: str, asked: str, found: Sequence[UUID]) -> UUID | str:
    if len(found) == 1:
        return found[0]
    if not found:
        return f"Binding {name}: no {kind} named {asked[:64]!r} that this agent may read.{HINT}"
    ids = ", ".join(sorted(str(item) for item in found))
    return (
        f"Binding {name}: {len(found)} {kind}s are named {asked[:64]!r}; pass the id of one: {ids}."
    )


def _query(name: str, request: BindingRequest, start: _Start) -> _Query | str:
    """The request's fields, filters, sort and limit as ids, on top of where it starts."""
    source = start.source
    live = [column for column in source.columns if not column.archived]
    fields: dict[str, UUID] = {}
    said: list[str] = []
    for field, ref in request.fields.items():
        found = _column_for(ref, live)
        if isinstance(found, UUID):
            fields[field] = found
        else:
            said.append(_unresolved(name, f"field {field}", ref, found, source))
    filters = list(start.filters)
    added: list[RecordFilter] = []
    for index, item in enumerate(request.filters, start=1):
        found = _column_for(item.column, live)
        if isinstance(found, UUID):
            added.append(RecordFilter(column_id=found, op=item.op, value=item.value))
        else:
            said.append(_unresolved(name, f"filter {index}", item.column, found, source))
    sort = start.sort
    if request.sort is not None:
        by, direction = request.sort.by, request.sort.direction
        column = None if by in _RECORD_TIMES else _column_for(by, live)
        if column is None or isinstance(column, UUID):
            sort = RecordSort(by=by if column is None else str(column), direction=direction)
        else:
            said.append(_unresolved(name, "its sort", by, column, source))
    if said:
        return " ".join(said)
    misnamed = _misnamed(name, fields)
    if misnamed is not None:
        return misnamed
    filters += filters_by_label(source.columns, added)
    if len(filters) > MAX_FILTERS:
        return (
            f"Binding {name}: a query takes at most {MAX_FILTERS} filters, the view's "
            f"included; this one has {len(filters)}."
        )
    cap = settings.ARTIFACT_DATA_MAX_RECORDS
    if request.limit is not None and request.limit > cap:
        return f"Binding {name}: `limit` is at most {cap:,}."
    bad = _invalid(name, source, filters, sort, viewed=len(start.filters))
    if bad is not None:
        return bad
    limit = request.limit or min(DEFAULT_LIMIT, cap)
    return _Query(name, source, filters, sort, limit, fields)


def _invalid(
    name: str, source: TableSource, filters: list[RecordFilter], sort: RecordSort, *, viewed: int
) -> str | None:
    """What the table cannot answer of the filters and the sort, filter by filter.

    The first `viewed` filters came from the view, the rest from the request.
    """
    by_id = {column.id: column for column in source.columns}
    for index, condition in enumerate(filters):
        which = (
            f"the view's filter on {by_id[condition.column_id].label}"
            if index < viewed
            else f"filter {index - viewed + 1}"
        )
        try:
            check_query(source.columns, [condition], RecordSort())
        except InvalidQueryError as refused:
            return f"Binding {name}: {which}: {refused.message}."
    try:
        check_query(source.columns, [], sort)
    except InvalidQueryError as refused:
        return f"Binding {name}: its sort: {refused.message}."
    return None


async def _reach(
    service: VirtualTableService,
    person: AuthContext,
    query: _Query,
    *,
    grants: Mapping[UUID, frozenset[str]] | None,
) -> tuple[BindingReach, dict[UUID, TableSource]] | str:
    """Everything `query` reaches, each table read as `person`, or what is lacking.

    The fields, the filters' columns and the sort's column, and through them every
    formula input, lookup and rollup link and target, and every linked table. With
    `grants` - a publish - each linked table must be granted `read` and be live; a
    restore passes none and keeps an archived one.
    """
    source = query.source
    by_id = {column.id: column for column in source.columns}
    sort_column = _as_uuid(query.sort.by)
    named = [
        *query.fields.values(),
        *(condition.column_id for condition in query.filters),
        *([sort_column] if sort_column is not None else []),
    ]
    found = reach(source.columns, named)
    # Columns are archived, never deleted, so every id reached is in the schema.
    tables = {source.id: {column_id: by_id[column_id].revision for column_id in found.columns}}
    sources = {source.id: source}
    labelled = {
        by_id[column_id].link_table_id
        for column_id in query.fields.values()
        if by_id[column_id].type == "link"
    }
    names: dict[UUID, UUID | None] = {}
    for table_id, targets in found.linked.items():
        through = ", ".join(
            column.label
            for column in source.columns
            if column.id in found.columns and column.link_table_id == table_id
        )
        if grants is not None and "read" not in grants.get(table_id, ()):
            return (
                f"Binding {query.name}: it reads through {through} a linked table this agent "
                "is not granted read on."
            )
        try:
            linked = sources.get(table_id) or await service.table_source(person, table_id)
        except NotFoundError:
            return f"Binding {query.name}: it reads through {through} a table you can't read."
        if grants is not None and linked.archived:
            return f"Binding {query.name}: it reads through {through} table {linked.name}, which is archived."
        sources[table_id] = linked
        columns = {column.id: column for column in linked.columns}
        revisions = tables.setdefault(table_id, {})
        for target in targets:
            revisions[target] = columns[target].revision
        if table_id in labelled:
            by = named_by(linked.columns)
            names[table_id] = by.id if by is not None else None
            if by is not None:
                revisions[by.id] = by.revision
    return BindingReach(tables=tables, named_by=names), sources


async def _owner_problem(
    service: VirtualTableService,
    owner: AuthContext | None,
    person: AuthContext,
    name: str,
    sources: Mapping[UUID, TableSource],
) -> str | None:
    """Whether the page's owner, whose access its data is read with, reads every table.

    Nothing to check when the owner is the person, already held to the same rule.
    """
    if owner is not None and owner.user_id == person.user_id:
        return None
    if owner is None:
        return (
            f"Binding {name}: the page's owner is no longer an active member, and a page's "
            "data is read with its owner's access."
        )
    lacking: list[str] = []
    for table_id, source in sources.items():
        try:
            await service.table_source(owner, table_id)
        except NotFoundError:
            lacking.append(source.name)
    if not lacking:
        return None
    return (
        f"Binding {name}: the page's owner can't read {', '.join(lacking)}, and a page's "
        "data is read with its owner's access."
    )


def _column_for(
    ref: str | UUID, live: Sequence[ColumnDef]
) -> UUID | Literal["unknown", "ambiguous"]:
    ids = {column.id for column in live}
    if isinstance(ref, UUID):
        return ref if ref in ids else "unknown"
    as_id = _as_uuid(ref)
    if as_id is not None and as_id in ids:
        return as_id
    matches = [column.id for column in live if column.label.casefold() == ref.casefold()]
    if len(matches) == 1:
        return matches[0]
    return "ambiguous" if matches else "unknown"


def _unresolved(
    name: str, what: str, ref: str, found: Literal["unknown", "ambiguous"], source: TableSource
) -> str:
    quoted = repr(ref[:200])
    if found == "ambiguous":
        return (
            f"Binding {name}: {what} names {quoted}, which matches more than one column of "
            f"table {source.name}; give the column's id."
        )
    return (
        f"Binding {name}: {what} names {quoted}, which is not a live column of table "
        f"{source.name}; `describe_table` lists its columns."
    )


def _misnamed(name: str, fields: Mapping[str, UUID]) -> str | None:
    """What is wrong with the field names, once each has resolved to a column."""
    bad = next((field for field in fields if len(field) > 64 or not _FIELD.fullmatch(field)), None)
    if bad is not None:
        return (
            f"Binding {name}: field name {bad[:64]!r} must be words of letters, digits and "
            "`_` with single spaces between them, at most 64 characters, not starting with a "
            "digit."
        )
    reserved = next((field for field in fields if field in _RESERVED_FIELDS), None)
    if reserved is not None:
        return f"Binding {name}: field name {reserved} is reserved; choose another."
    if len(fields) > MAX_FIELDS:
        return (
            f"Binding {name}: a binding takes at most {MAX_FIELDS} fields; "
            f"this one has {len(fields)}."
        )
    named: dict[UUID, str] = {}
    for field, column_id in fields.items():
        if column_id in named:
            return (
                f"Binding {name}: fields {named[column_id]} and {field} name the same "
                "column; keep one."
            )
        named[column_id] = field
    return None


def _not_found(kind: Literal["View", "Table"], item_id: UUID) -> str:
    """The same words for one that is gone, elsewhere or not this person's to read."""
    return f"{kind} {item_id} not found.{HINT}"


def _as_uuid(text: str) -> UUID | None:
    try:
        return UUID(text)
    except ValueError:
        return None


def disclose(binding: ArtifactBinding, sources: Mapping[UUID, TableSource]) -> BindingDisclosure:
    """A page query in words: its table, each filter, its order, its limit and each field.

    `sources` holds every table the query reaches. A worked-out field says what it is
    worked out from - `Pay band: formula over Salary, Level`, `Customer: link, labels
    from Customers -> Name`, `Open value: rollup sum of Deals -> Amount` - since what it
    shows comes from columns, and tables, the page names nowhere else.
    """
    source = sources[binding.table_id]
    by_id = {column.id: column for column in source.columns}
    return BindingDisclosure(
        table=source.name,
        filters=[_condition(by_id[item.column_id], item) for item in binding.filters],
        sort=_order(binding.sort, by_id, sources, binding.reach),
        limit=binding.limit,
        fields={
            field: _reads(by_id[column_id], by_id, sources, binding.reach)
            for field, column_id in binding.fields.items()
        },
    )


def fingerprint(bindings: Sequence[ArtifactBinding]) -> str | None:
    """One digest of a version's page queries, their reach included; `None` with none.

    The same queries give the same digest, whatever order the page declared them in.
    """
    if not bindings:
        return None
    canonical = sorted((binding.model_dump(mode="json") for binding in bindings), key=_named)
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _named(dumped: dict[str, Any]) -> str:
    return str(dumped["name"])


def _condition(column: ColumnDef, condition: RecordFilter) -> str:
    if condition.op == "is_null":
        return f"{column.label} is {'empty' if condition.value else 'not empty'}"
    value = condition.value
    if isinstance(value, list):
        shown = ", ".join(_shown(column, item) for item in value)
    else:
        shown = _shown(column, value)
    return f"{column.label} {_OPERATORS[condition.op]} {shown}"


def _shown(column: ColumnDef, value: CellValue) -> str:
    """One operand as a person reads it: a choice by its label, text in quotes."""
    if column.type in OPTION_TYPES and isinstance(value, str):
        value = next((option.label for option in column.options if str(option.id) == value), value)
    return json.dumps(value, ensure_ascii=False)


def _order(
    sort: RecordSort,
    by_id: Mapping[UUID, ColumnDef],
    sources: Mapping[UUID, TableSource],
    found: BindingReach,
) -> str:
    """The order, by a column's label and, for a worked-out one, what it is worked out from."""
    direction = "ascending" if sort.direction == "asc" else "descending"
    sorted_by = _as_uuid(sort.by)
    if sorted_by is None:
        return f"{_RECORD_TIMES[sort.by]}, {direction}"
    column = by_id[sorted_by]
    derived = _derivation(column, by_id, sources, found)
    what = column.label if derived is None else f"{column.label} ({derived})"
    return f"{what}, {direction}"


def _reads(
    column: ColumnDef,
    by_id: Mapping[UUID, ColumnDef],
    sources: Mapping[UUID, TableSource],
    found: BindingReach,
) -> str:
    """What one field reads: its column, and for a worked-out one where it comes from."""
    derived = _derivation(column, by_id, sources, found)
    return f"{column.label} ({column.type})" if derived is None else f"{column.label}: {derived}"


def _derivation(
    column: ColumnDef,
    by_id: Mapping[UUID, ColumnDef],
    sources: Mapping[UUID, TableSource],
    found: BindingReach,
) -> str | None:
    """Where a worked-out column's values come from - `formula over Salary, Level` -
    or `None` for a column holding values of its own."""
    if column.type == "formula":
        live = {item.label for item in by_id.values() if not item.archived}
        inputs = [label for label in references(column.formula or "") if label in live]
        return f"formula over {', '.join(inputs)}" if inputs else "formula"
    if column.type == "link" and column.link_table_id is not None:
        linked = sources[column.link_table_id]
        label = found.named_by.get(linked.id)
        by = next((item.label for item in linked.columns if item.id == label), "record ids")
        return f"link, labels from {linked.name} -> {by}"
    link = by_id[column.link_column_id] if column.link_column_id is not None else None
    if column.type in READ_THROUGH_LINK and link is not None and link.link_table_id is not None:
        linked = sources[link.link_table_id]
        if column.aggregate == "count":
            return f"rollup count of {linked.name}"
        target = next(
            (item.label for item in linked.columns if item.id == column.target_column_id), "?"
        )
        kind = "lookup of" if column.type == "lookup" else f"rollup {column.aggregate} of"
        return f"{kind} {linked.name} -> {target}"
    return None


@dataclass(frozen=True)
class BindingRows:
    """One binding as a page load read it: the fields it names, and what its query served."""

    fields: Mapping[str, UUID]
    rows: BoundRows


@dataclass(frozen=True)
class Unavailable:
    """A binding a page load serves nothing for, and why, for an editor to hear."""

    reason: Reason
    changed: str | None = None
    """With `source_changed`: the column, by its label now, or the table that changed."""


async def page_source(
    service: VirtualTableService,
    owner: AuthContext,
    binding: ArtifactBinding,
    *,
    deadline: ReadDeadline,
) -> TableSource | Unavailable:
    """The binding's table as its owner reads it now, or why the binding reads nothing.

    `owner` must read every table the query reaches, or it is `creator_lost_access`.
    Then the reach is compared with the tables now: a reached table archived, a
    reached column archived or at another revision, or a linked table naming its
    records by another column is `source_changed`, naming the column by its label now,
    or the table.

    Raises:
        DeadlineReached: Too little of `deadline` is left for the next statement.
    """
    sources: dict[UUID, TableSource] = {}
    for table_id in binding.reach.tables:
        try:
            sources[table_id] = await service.table_source(owner, table_id, deadline=deadline)
        except NotFoundError:
            return Unavailable("creator_lost_access")
    for table_id, revisions in binding.reach.tables.items():
        source = sources[table_id]
        if source.archived:
            return Unavailable("source_changed", source.name)
        columns = {column.id: column for column in source.columns}
        for column_id, revision in revisions.items():
            column = columns.get(column_id)
            if column is None:
                return Unavailable("source_changed", source.name)
            if column.archived or column.revision != revision:
                return Unavailable("source_changed", column.label)
    for table_id, stored in binding.reach.named_by.items():
        now = named_by(sources[table_id].columns)
        if (now.id if now is not None else None) != stored:
            return Unavailable("source_changed", sources[table_id].name)
    return sources[binding.table_id]


def shape_for(
    columns: Sequence[ColumnDef], fields: Mapping[str, UUID]
) -> Callable[[RecordRead], dict[str, Any]]:
    """A record as a page reads it: its id and each named field, and nothing else.

    A choice reads as its label and a link as `[{id, label}]` from the record's
    resolved links. A field whose column is archived or gone reads `None`, and so
    does an empty cell.
    """
    by_id = {column.id: column for column in columns}
    named = [(field, by_id.get(column_id)) for field, column_id in fields.items()]

    def shape(record: RecordRead) -> dict[str, Any]:
        shaped: dict[str, Any] = {"id": str(record.id)}
        for field, column in named:
            if column is None or column.archived:
                shaped[field] = None
            elif column.type == "link":
                shaped[field] = [
                    {"id": str(linked.id), "label": linked.label}
                    for linked in record.links.get(str(column.id), [])
                ]
            else:
                shaped[field] = readable(column, record.values.get(str(column.id)))
        return shaped

    return shape


def bound_fields(columns: Sequence[ColumnDef], fields: Mapping[str, UUID]) -> dict[str, BoundField]:
    """What each field reads now: its column's current label, type and live choices."""
    by_id = {column.id: column for column in columns}
    described: dict[str, BoundField] = {}
    for field, column_id in fields.items():
        column = by_id.get(column_id)
        if column is None:
            described[field] = BoundField(label=field, type="text", state="missing")
            continue
        described[field] = BoundField(
            label=column.label,
            type=column.type,
            options=(
                [option.label for option in column.options if not option.archived]
                if column.type in OPTION_TYPES
                else None
            ),
            state="archived" if column.archived else "ok",
        )
    return described


def fair_shares(totals: Mapping[str, int], cap: int) -> dict[str, int]:
    """How many bytes each binding may serve so the page stays within `cap`, shared max-min fairly.

    Within the cap every binding keeps all it read. Over it, the smallest go first
    and keep all they read while that is no more than an even split of what is left;
    the rest split it evenly. Ties go by name, so the shares never depend on the
    order a page declared its bindings in.
    """
    if sum(totals.values()) <= cap:
        return dict(totals)
    shares: dict[str, int] = {}
    left = cap
    ordered = sorted(totals.items(), key=lambda item: (item[1], item[0]))
    for index, (name, total) in enumerate(ordered):
        shares[name] = min(total, left // (len(ordered) - index))
        left -= shares[name]
    return shares


def unavailable(reason: str | None, changed: str | None = None) -> BindingData:
    return BindingData(
        status="unavailable",
        reason=reason,
        changed=changed,
        truncated=False,
        limit=None,
        count=0,
        fields={},
        records=[],
    )


def page_data(
    reads: Mapping[str, BindingRows | Unavailable], *, max_bytes: int, can_edit: bool
) -> dict[str, BindingData]:
    """Every binding's payload for one page load, the page within `max_bytes` of shaped data.

    A binding over its fair share keeps the longest prefix of its records that fits,
    and says `limit: "bytes"`, as it does when its read already stopped at the byte
    budget. Only an editor (`can_edit`) is told why a binding is unavailable.
    """
    shares = fair_shares(
        {name: read.rows.bytes for name, read in reads.items() if isinstance(read, BindingRows)},
        max_bytes,
    )
    served: dict[str, BindingData] = {}
    for name, read in reads.items():
        if isinstance(read, Unavailable):
            served[name] = unavailable(read.reason, read.changed) if can_edit else unavailable(None)
            continue
        rows = read.rows
        kept, used = 0, 0
        for size in rows.sizes:
            if used + size > shares[name]:
                break
            kept, used = kept + 1, used + size
        limit: Literal["records", "bytes"] | None = (
            "bytes" if rows.stopped_by == "bytes" or kept < len(rows.records) else rows.stopped_by
        )
        served[name] = BindingData(
            status="ok",
            truncated=limit is not None,
            limit=limit,
            count=kept,
            fields=bound_fields(rows.columns, read.fields),
            records=rows.records[:kept],
        )
    return served
