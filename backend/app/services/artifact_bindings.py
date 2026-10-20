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

This module takes the spec's table grants as a plain mapping and never imports the
agents package: the caller extracts them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.schemas.artifact import ArtifactBinding, BindingRequest
from app.schemas.virtual_table import ColumnDef
from app.services.virtual_tables import TableViewService, reach
from app.services.virtual_tables.exceptions import TableArchivedError

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
