"""Whether a page's bindings to saved table views may stand, and what each one resolves to.

A published page reads live records through bindings: a name, a saved view and the
fields it reads, each one a column of the view's table. `check_bindings` is the one
check for them. A publish refuses on any problem it reports; a restore never refuses,
and keeps a binding that fails as `unavailable`, with the reason.

What the check may say depends on who hears it. A binding is resolved first, without
a person, but nothing learned there is reported until the person behind the run has
been shown to see the view: a view they cannot see is "not found", whatever its
columns are. A run with no person hears only that it cannot bind at all. A binding
carried forward unchanged is checked without a person, so its problems name the
binding and its field names, never a column's label.

This module also shapes what a page load is served (`page_data`): each record as its
id and the binding's named fields, nothing else, and one byte budget for the page,
shared fairly among its bindings.

This module takes the spec's table grants as a plain mapping and never imports the
agents package: the caller extracts them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.schemas.artifact import ArtifactBinding, BindingData, BindingRequest, BoundField
from app.schemas.virtual_table import ColumnDef, RecordRead
from app.services.virtual_tables import BoundRows, TableViewService, reach
from app.services.virtual_tables.exceptions import TableArchivedError
from app.services.virtual_tables.presentation import readable
from app.services.virtual_tables.types import OPTION_TYPES

Reason = Literal[
    "no_person",
    "view_missing",
    "table_archived",
    "table_not_granted",
    "field_missing",
    "linked_table_not_granted",
]

_NAME = re.compile(r"[a-z_][a-z0-9_]{0,63}")
_PATTERN = "`^[a-z_][a-z0-9_]{0,63}$`"
_RESERVED_FIELDS = frozenset({"id", "__proto__", "constructor", "prototype"})
"""Names a page script reads every record by, or that would reach an object's prototype."""
_RESERVED_NAMES = frozenset({"__proto__", "constructor", "prototype"})
"""Binding names a page script would reach an object's prototype by."""
MAX_FIELDS = 50
NO_PERSON = "Only a run acting for a member can bind a page to a view."
_REPLACE = "; pass `bindings` to replace them."


@dataclass(frozen=True)
class BindingCheck:
    """One binding's outcome: what it resolves to, and the problem, if any, in the model's words."""

    name: str
    binding: ArtifactBinding | None
    """The resolved binding. On a restore, a failed one is the stored binding marked
    `unavailable` with its reason. `None` when a publish could not resolve it: its
    view, or one of its fields, is not a live part of the organization's tables."""
    problem: str | None
    """Text for the model, safe for whoever the run acts for to read; `None` when fine."""
    changed: bool
    """Whether the request names it differently from the stored binding of that name.
    A binding carried forward, or sent again identically, is not changed."""


@dataclass(frozen=True)
class _Failure:
    """Why a binding cannot stand, in the words each kind of caller may hear."""

    reason: Reason
    sent: str
    """For a run that sent the binding and was shown to see its view."""
    carried: str
    """For a run carrying it forward: names the binding and its field names, no label."""
    plain: bool = False
    """Said the same to everyone, however the binding came to be checked."""


@dataclass(frozen=True)
class _Resolved:
    """A binding whose view and fields all resolved, and anything wrong with its field names."""

    binding: ArtifactBinding
    columns: Sequence[ColumnDef]
    held: _Failure | None


async def check_bindings(
    db: AsyncSession,
    *,
    organization_id: UUID,
    requested: Mapping[str, BindingRequest] | None,
    previous: Sequence[ArtifactBinding],
    person: AuthContext | None,
    grants: Mapping[UUID, frozenset[str]],
    recheck_person: bool = False,
) -> list[BindingCheck]:
    """Check a page version's bindings, one outcome per binding, in the order given.

    `requested` is what the model sent, replacing `previous` whole; `None` carries
    `previous` forward. `grants` is the spec's operations per table id. A binding
    needs `read` on its table and on every table it reads through a link.

    A requested binding that is new or changed is checked as `person`, who must be
    able to see the view. One identical to the stored binding of its name is carried,
    and needs no person. A carried binding is rechecked against its view's live
    columns and the grants only. A carried binding stored `unavailable` stays so for
    a run with no person, and is checked in full as `person` otherwise: it comes back
    `ok`, or reports why not.

    `recheck_person` is the restore: every binding is checked in full as `person`, a
    failure marks it `unavailable` rather than refusing, and one stored `unavailable`
    stays as it is.
    """
    views = TableViewService(db)
    if requested is None:
        return [
            await _carry(views, organization_id, prior, None, person, grants, recheck_person)
            for prior in previous
        ]
    cap = settings.ARTIFACT_DATA_MAX_BINDINGS
    if len(requested) > cap:
        problem = f"A page takes at most {cap} bindings; this one has {len(requested)}."
        return [BindingCheck(name, None, problem, True) for name in requested]
    stored = {binding.name: binding for binding in previous}
    return [
        await _check_requested(
            views,
            organization_id,
            name,
            request,
            stored.get(name),
            person,
            grants,
            recheck_person,
        )
        for name, request in requested.items()
    ]


async def _check_requested(
    views: TableViewService,
    organization_id: UUID,
    name: str,
    request: BindingRequest,
    prior: ArtifactBinding | None,
    person: AuthContext | None,
    grants: Mapping[UUID, frozenset[str]],
    recheck_person: bool,
) -> BindingCheck:
    if not _NAME.fullmatch(name):
        return BindingCheck(name, None, f"Binding name {name[:64]!r} must match {_PATTERN}.", True)
    if name in _RESERVED_NAMES:
        return BindingCheck(name, None, f"Binding name {name} is reserved; choose another.", True)
    if prior is not None and _resends(request, prior):
        return await _carry(views, organization_id, prior, None, person, grants, recheck_person)
    resolution = await _resolve(views, organization_id, name, request.view, request.fields)
    if prior is not None and isinstance(resolution, _Resolved) and _same(resolution.binding, prior):
        return await _carry(
            views, organization_id, prior, resolution, person, grants, recheck_person
        )
    failure = await _as_person(views, person, name, request.view) or _standing(resolution, grants)
    binding = resolution.binding if isinstance(resolution, _Resolved) else None
    return BindingCheck(name, binding, failure.sent if failure else None, True)


async def _carry(
    views: TableViewService,
    organization_id: UUID,
    prior: ArtifactBinding,
    resolution: _Resolved | None,
    person: AuthContext | None,
    grants: Mapping[UUID, frozenset[str]],
    recheck_person: bool,
) -> BindingCheck:
    """A stored binding kept: by omission, by being sent again identically, or by a restore."""
    if prior.status == "unavailable" and (recheck_person or person is None):
        return BindingCheck(prior.name, prior, None, False)
    revived = prior.status == "unavailable"
    outcome = resolution or await _resolve(
        views, organization_id, prior.name, prior.view_id, prior.fields
    )
    failure = None
    if revived or recheck_person:
        failure = await _as_person(views, person, prior.name, prior.view_id)
    failure = failure or _standing(outcome, grants)
    binding = outcome.binding if isinstance(outcome, _Resolved) else None
    if failure is None:
        return BindingCheck(prior.name, binding, None, False)
    if recheck_person:
        marked = prior.model_copy(update={"status": "unavailable", "reason": failure.reason})
        return BindingCheck(prior.name, marked, failure.carried, False)
    if revived and not failure.plain:
        problem = (
            f"Binding {prior.name} is unavailable ({failure.reason}); "
            "pass `bindings` to replace or drop it."
        )
        return BindingCheck(prior.name, binding, problem, False)
    return BindingCheck(prior.name, binding, failure.carried, False)


async def _resolve(
    views: TableViewService,
    organization_id: UUID,
    name: str,
    view_id: UUID,
    fields: Mapping[str, str | UUID],
) -> _Resolved | _Failure:
    """The binding as ids, read without a person. What is wrong is held for the caller to say.

    A field is a live column's id, or, when sent as text, a live column's label,
    matched case-insensitively and only when one column has it.
    """
    try:
        bound = await views.view_for_binding(organization_id, view_id)
    except NotFoundError:
        return _Failure(
            "view_missing", _not_found(view_id), f"Binding {name}: its view was deleted{_REPLACE}"
        )
    except TableArchivedError:
        return _archived(name, view_id)
    live = [column for column in bound.columns if not column.archived]
    resolved: dict[str, UUID] = {}
    missing: list[str] = []
    said: list[str] = []
    for field, ref in fields.items():
        found = _column_for(ref, live)
        if isinstance(found, UUID):
            resolved[field] = found
            continue
        missing.append(field)
        quoted = repr(str(ref)[:200])
        said.append(
            f"Binding {name}: field {field} names {quoted}, which is not a live column of view "
            f"{view_id}; `list_views` lists its columns."
            if found == "unknown"
            else f"Binding {name}: field {field} names {quoted}, which matches more than one "
            f"column of view {view_id}; give the column's id."
        )
    if missing:
        archived = (
            f"field {missing[0]} points at a column that was archived"
            if len(missing) == 1
            else f"fields {', '.join(missing)} point at columns that were archived"
        )
        return _Failure("field_missing", " ".join(said), f"Binding {name}: {archived}{_REPLACE}")
    binding = ArtifactBinding(name=name, view_id=view_id, table_id=bound.table_id, fields=resolved)
    return _Resolved(binding=binding, columns=bound.columns, held=_misnamed(name, resolved))


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


def _misnamed(name: str, fields: Mapping[str, UUID]) -> _Failure | None:
    """What is wrong with the field names, once each has resolved to a column.

    The reason is never stored: a stored binding passed this check when it was
    published, so only a requested one can fail it, and a publish refuses it.
    """
    text = None
    bad = next((field for field in fields if not _NAME.fullmatch(field)), None)
    reserved = next((field for field in fields if field in _RESERVED_FIELDS), None)
    if bad is not None:
        text = f"Binding {name}: field name {bad[:64]!r} must match {_PATTERN}."
    elif reserved is not None:
        text = f"Binding {name}: field name {reserved} is reserved; choose another."
    elif len(fields) > MAX_FIELDS:
        text = (
            f"Binding {name}: a binding takes at most {MAX_FIELDS} fields; "
            f"this one has {len(fields)}."
        )
    else:
        named: dict[UUID, str] = {}
        for field, column_id in fields.items():
            if column_id in named:
                text = (
                    f"Binding {name}: fields {named[column_id]} and {field} name the same "
                    "column; keep one."
                )
                break
            named[column_id] = field
    return None if text is None else _Failure("field_missing", text, text)


async def _as_person(
    views: TableViewService, person: AuthContext | None, name: str, view_id: UUID
) -> _Failure | None:
    """Whether `person` sees the view: shared or their own, on a table they may view.

    Every view they cannot see reads the same, so nothing held about its columns is said.
    """
    if person is None:
        return _Failure("no_person", NO_PERSON, NO_PERSON, plain=True)
    try:
        await views.find_view(person, view_id)
    except NotFoundError:
        return _Failure("view_missing", _not_found(view_id), _not_found(view_id), plain=True)
    except TableArchivedError:
        return _archived(name, view_id)
    return None


def _standing(
    resolution: _Resolved | _Failure, grants: Mapping[UUID, frozenset[str]]
) -> _Failure | None:
    """What resolving held, else whether the grants let the agent read what the binding names."""
    if isinstance(resolution, _Failure):
        return resolution
    if resolution.held is not None:
        return resolution.held
    binding = resolution.binding
    if "read" not in grants.get(binding.table_id, ()):
        return _Failure(
            "table_not_granted",
            f"Binding {binding.name}: this agent is not granted read on the table of view "
            f"{binding.view_id}.",
            f"Binding {binding.name}: this agent is not granted read on its view's table{_REPLACE}",
        )
    ungranted = [
        field
        for field, column_id in binding.fields.items()
        if any(
            "read" not in grants.get(table_id, ())
            for table_id in reach(resolution.columns, [column_id]).linked
        )
    ]
    if not ungranted:
        return None
    reads = (
        f"field {ungranted[0]} reads"
        if len(ungranted) == 1
        else f"fields {', '.join(ungranted)} read"
    )
    said = f"Binding {binding.name}: {reads} a linked table this agent is not granted read on"
    return _Failure("linked_table_not_granted", f"{said}.", f"{said}{_REPLACE}")


def _archived(name: str, view_id: UUID) -> _Failure:
    return _Failure(
        "table_archived",
        f"View {view_id} is on an archived table.",
        f"Binding {name}: its view's table was archived{_REPLACE}",
    )


def _not_found(view_id: UUID) -> str:
    return f"View {view_id} not found."


def _resends(request: BindingRequest, prior: ArtifactBinding) -> bool:
    """Whether the request names exactly the stored binding's view and column ids."""
    return (
        request.view == prior.view_id
        and {field: _as_uuid(ref) for field, ref in request.fields.items()} == prior.fields
    )


def _same(binding: ArtifactBinding, prior: ArtifactBinding) -> bool:
    return (binding.view_id, binding.table_id, binding.fields) == (
        prior.view_id,
        prior.table_id,
        prior.fields,
    )


def _as_uuid(text: str) -> UUID | None:
    try:
        return UUID(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class BindingRows:
    """One binding as a page load read it: the fields it names, and what its view served."""

    fields: Mapping[str, UUID]
    rows: BoundRows
    filters_dropped: bool


@dataclass(frozen=True)
class Unavailable:
    """A binding a page load serves nothing for, and why, for an editor to hear."""

    reason: str | None


def shape_for(
    columns: Sequence[ColumnDef], fields: Mapping[str, UUID]
) -> Callable[[RecordRead], dict[str, Any]]:
    """A record as a page reads it: its id and each named field, and nothing else.

    A choice reads as its label and a link as `[{id, label}]` from the record's
    resolved links, `[]` when the reader may not see the linked table. A field whose
    column is archived or gone reads `None`, and so does an empty cell.
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


def unavailable(reason: str | None) -> BindingData:
    return BindingData(
        status="unavailable",
        reason=reason,
        truncated=False,
        limit=None,
        count=0,
        filters_dropped=False,
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
            served[name] = unavailable(read.reason if can_edit else None)
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
            filters_dropped=read.filters_dropped,
            fields=bound_fields(rows.columns, read.fields),
            records=rows.records[:kept],
        )
    return served
