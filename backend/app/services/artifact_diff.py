"""What a version's page queries read that another version's did not (#1974).

A republish by an editor who is not the page's owner waits for the owner's consent, and
the owner decides on what changed, not on the whole page query again. This compares two
versions' queries as the structured parts :func:`app.services.artifact_bindings.describe`
gives, binding by binding, and marks each difference by what it does to the people who
read the data:

- **widens**: a column or a linked table is read that was not - by a field, or only by a
  condition or the order - a larger limit, a condition dropped, another order (it picks
  other records into the limit). A condition that was changed counts as widening - what a
  new operand matches cannot be told from the words - except a list of choices that only
  lost some.
- **narrows**: the opposite of each of those.
- **neutral**: nothing the audience reads differs.

Tables, linked tables and columns are matched by id: a table or column of the same name
that is another one is a change, and the names are only what is shown.

A binding the audience's version did not have is added whole and widens; one it no longer
has narrows.

A workflow-log binding has no columns to compare, so any difference between two of them -
its workflow, step, outcomes, run, test lines, lines or per-day, the limit, the days or the
time zone - widens, and so does a binding that changes from one kind to the other: what a
new filter matches cannot be told from the words, and the owner decides again.
"""

from collections.abc import Mapping
from typing import NamedTuple
from uuid import UUID

from app.schemas.artifact import (
    ArtifactBinding,
    BindingParts,
    DisclosedFilter,
    WorkflowLogBinding,
    WorkflowLogParts,
)
from app.schemas.artifact_share_request import BindingChange, BindingReview, Effect
from app.services.artifact_bindings import describe
from app.services.virtual_tables.tables import TableSource


class BindingView(NamedTuple):
    """A page query as stored, with the names to show its ids by."""

    binding: ArtifactBinding
    parts: BindingParts
    tables: Mapping[UUID, str]
    columns: Mapping[UUID, str]


class LogView(NamedTuple):
    """A workflow-log binding as stored, with its words."""

    binding: WorkflowLogBinding
    parts: WorkflowLogParts


AnyView = BindingView | LogView


def view_of(binding: ArtifactBinding, sources: Mapping[UUID, TableSource]) -> BindingView:
    """`binding` with its words, from the tables it reaches (`sources` holds all of them)."""
    return BindingView(
        binding=binding,
        parts=describe(binding, sources),
        tables={table_id: sources[table_id].name for table_id in binding.reach.tables},
        columns={
            column.id: column.label
            for table_id in binding.reach.tables
            for column in sources[table_id].columns
        },
    )


def diff_bindings(
    before: Mapping[str, AnyView], after: Mapping[str, AnyView]
) -> tuple[list[BindingReview], list[str]]:
    """The bindings that differ between two versions, and the names of those that do not."""
    reviews: list[BindingReview] = []
    unchanged: list[str] = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old is None and new is not None:
            reviews.append(
                BindingReview(name=name, change="added", effect="widens", parts=new.parts)
            )
        elif new is None and old is not None:
            reviews.append(
                BindingReview(name=name, change="removed", effect="narrows", parts=old.parts)
            )
        else:
            assert old is not None and new is not None  # the name came from one of them
            changes = (
                _changes(old, new)
                if isinstance(old, BindingView) and isinstance(new, BindingView)
                else _log_changes(old, new)
            )
            if changes:
                reviews.append(
                    BindingReview(
                        name=name, change="changed", effect=_overall(changes), changes=changes
                    )
                )
            else:
                unchanged.append(name)
    return reviews, unchanged


def _overall(changes: list[BindingChange]) -> Effect:
    effects = {change.effect for change in changes}
    if "widens" in effects:
        return "widens"
    return "narrows" if "narrows" in effects else "neutral"


def _log_changes(old: AnyView, new: AnyView) -> list[BindingChange]:
    """Any difference involving a workflow-log binding: one change, widening."""
    if isinstance(old, LogView) and isinstance(new, LogView):
        if old.binding == new.binding:
            return []
        return [
            BindingChange(
                aspect="log", change="changed", effect="widens", before=old.parts, after=new.parts
            )
        ]
    return [
        BindingChange(
            aspect="kind",
            change="changed",
            effect="widens",
            before=old.parts if isinstance(old, LogView) else old.parts.table,
            after=new.parts if isinstance(new, LogView) else new.parts.table,
        )
    ]


def _changes(old: BindingView, new: BindingView) -> list[BindingChange]:
    was, now = old.binding, new.binding
    found: list[BindingChange] = []
    if was.table_id != now.table_id:
        found.append(
            BindingChange(
                aspect="table",
                change="changed",
                effect="widens",
                before=old.parts.table,
                after=new.parts.table,
            )
        )
    found += _field_changes(old, new)
    found += _filter_changes(old, new)
    if was.sort != now.sort:
        # The order picks which records fall inside the limit, so another order reads other ones.
        found.append(
            BindingChange(
                aspect="sort",
                change="changed",
                effect="widens",
                before=old.parts.sort,
                after=new.parts.sort,
            )
        )
    if was.limit != now.limit:
        found.append(
            BindingChange(
                aspect="limit",
                change="changed",
                effect="widens" if now.limit > was.limit else "narrows",
                before=was.limit,
                after=now.limit,
            )
        )
    found += _linked_changes(old, new)
    found += _reach_changes(old, new)
    return found


def _linked(view: BindingView) -> set[UUID]:
    return set(view.binding.reach.tables) - {view.binding.table_id}


def _linked_changes(old: BindingView, new: BindingView) -> list[BindingChange]:
    found = [
        BindingChange(aspect="linked", change="added", effect="widens", after=new.tables[table_id])
        for table_id in sorted(_linked(new) - _linked(old), key=new.tables.__getitem__)
    ]
    found += [
        BindingChange(
            aspect="linked", change="removed", effect="narrows", before=old.tables[table_id]
        )
        for table_id in sorted(_linked(old) - _linked(new), key=old.tables.__getitem__)
    ]
    return found


def _reach_changes(old: BindingView, new: BindingView) -> list[BindingChange]:
    """Columns of tables both versions reach that only the newer one reads - through a
    condition or the order, since a field's own column is reported as that field."""
    shown = set(new.binding.fields.values()) - set(old.binding.fields.values())
    found: list[BindingChange] = []
    for table_id, columns in new.binding.reach.tables.items():
        if table_id not in old.binding.reach.tables:
            continue  # a table newly reached is reported as the table or a linked one
        gained = set(columns) - set(old.binding.reach.tables[table_id]) - shown
        found += [
            BindingChange(aspect="reach", change="added", effect="widens", after=new.columns[c])
            for c in sorted(gained, key=new.columns.__getitem__)
        ]
    return found


def _field_changes(old: BindingView, new: BindingView) -> list[BindingChange]:
    was = {field.name: field for field in old.parts.fields}
    now = {field.name: field for field in new.parts.fields}
    found: list[BindingChange] = []
    for name in sorted(now.keys() - was.keys()):
        found.append(
            BindingChange(aspect="field", change="added", effect="widens", after=now[name])
        )
    for name in sorted(was.keys() - now.keys()):
        found.append(
            BindingChange(aspect="field", change="removed", effect="narrows", before=was[name])
        )
    for name in sorted(was.keys() & now.keys()):
        if was[name] != now[name] or old.binding.fields[name] != new.binding.fields[name]:
            found.append(
                BindingChange(
                    aspect="field",
                    change="changed",
                    effect="widens",
                    before=was[name],
                    after=now[name],
                )
            )
    return found


type _Condition = tuple[UUID, DisclosedFilter]
"""A condition with the id of its column: what it says, and which column that is."""


def _conditions(view: BindingView) -> list[_Condition]:
    return [
        (stored.column_id, shown)
        for stored, shown in zip(view.binding.filters, view.parts.filters, strict=True)
    ]


def _filter_changes(old: BindingView, new: BindingView) -> list[BindingChange]:
    """Conditions are matched by what they say first; the leftovers on the same column and
    operator are one condition changed, and the rest were dropped or added."""
    gone = _conditions(old)
    came = _conditions(new)
    for condition in list(gone):
        if condition in came:
            gone.remove(condition)
            came.remove(condition)
    found: list[BindingChange] = []
    for condition in list(gone):
        column_id, shown = condition
        match = next(
            (item for item in came if (item[0], item[1].op) == (column_id, shown.op)), None
        )
        if match is None:
            continue
        gone.remove(condition)
        came.remove(match)
        found.append(
            BindingChange(
                aspect="filter",
                change="changed",
                effect=_operand_effect(shown, match[1]),
                before=shown,
                after=match[1],
            )
        )
    found += [
        BindingChange(aspect="filter", change="removed", effect="widens", before=shown)
        for _, shown in gone
    ]
    found += [
        BindingChange(aspect="filter", change="added", effect="narrows", after=shown)
        for _, shown in came
    ]
    return found


def _operand_effect(old: DisclosedFilter, new: DisclosedFilter) -> Effect:
    """A list of choices that only lost some narrows; any other changed operand widens."""
    lost_some = (
        old.op == "in"
        and isinstance(old.value, list)
        and isinstance(new.value, list)
        and set(map(str, new.value)) < set(map(str, old.value))
    )
    return "narrows" if lost_some else "widens"
