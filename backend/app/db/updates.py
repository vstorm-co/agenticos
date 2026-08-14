"""Turning a `*Update` schema into the columns it may actually write.

`model_dump(exclude_unset=True)` is the obvious way and it has one trap, which
this module exists to close: it keeps a field that was **explicitly set to
`None`**. On an `*Update` schema every field is `X | None` because `None` means
"not provided" - but a client that sends `{"name": null}` has provided one, so the
`None` survives the dump, reaches `setattr` and hits a `NOT NULL` column. The API's
own types say the request is legal and the answer is a 500 naming a database
constraint (#637).

Twenty-four such pairs existed across eleven schemas when this was written. They
were not twenty-four bugs to fix: they were one missing function, because the
alternative is a hand-kept list of field names per service and a new optional
field is a new crash nobody notices for months.

**The column decides, not a list.** Nullability is on the model, so the rule reads
it there and a schema gains a field without anybody remembering this file.

What it deliberately does *not* do is invent a value. A `null` a column refuses is
dropped, so the row keeps what it had - which is the honest answer for "reset this"
where there is nothing to reset to. Where a field *does* have a default worth going
back to, the service says so itself before calling this: `EmbedUpdate.config` is
the worked example, and it substitutes the kind's defaults rather than dropping the
key.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase


def writable(
    data: BaseModel, *, over: type[DeclarativeBase], exclude: set[str] | None = None
) -> dict[str, Any]:
    """The fields this update sets, minus the nulls `over` would refuse.

    Args:
        data: The `*Update` schema the caller received.
        over: The model whose row is about to be written. Its columns are what
            decide: a `None` for a nullable column is a value and is kept, and a
            `None` for a `NOT NULL` one is the sentinel and is dropped.
        exclude: Fields to leave out entirely, as `model_dump` takes them. For a
            schema carrying a flag that is not a column - `clear_allowed_tools`
            asks for an *action* rather than naming a value - which the service
            reads off the schema itself.

    A field with no column of that name is passed through untouched - a service
    that renames one on the way to the row (`password` becoming
    `hashed_password`) does that after this, and a schema field that is not a
    column at all is the service's business rather than this function's.
    """
    columns = over.__table__.columns
    changes = data.model_dump(exclude_unset=True, exclude=exclude)
    return {
        field: value
        for field, value in changes.items()
        if not (value is None and _refuses_null(columns, field))
    }


def cleared(data: BaseModel, field: str) -> bool:
    """Whether the caller explicitly sent `null` for this field.

    The question `writable` deliberately answers by dropping, asked directly - for
    the two services where an explicit `null` means something *other* than "leave
    the row alone":

    *Reset it.* `EmbedUpdate.config` restores the kind's defaults, because there is a
    default worth going back to.

    *Refuse it.* An `AgentEnvironment` is always pinned to a version, so
    `version_id: null` is not "track latest" - there is no such state - and the
    caller is owed the sentence rather than a silent no-op. Dropping it turned that
    refusal into "Nothing to change", which is true of the row and useless to the
    person who asked.

    Read off `model_fields_set` rather than a dump, because that set *is* the
    distinction `exclude_unset` is built on: a field nobody mentioned is absent from
    it, and a field somebody set to `null` is in it.
    """
    return field in data.model_fields_set and getattr(data, field) is None


def _refuses_null(columns: Any, field: str) -> bool:
    column = columns.get(field)
    return column is not None and not column.nullable
