"""A table's records and schema as a caller outside the console addresses them.

An agent tool and a workflow step both write values by column - and a person
building either knows a column by its label, not its id. These helpers map a
label to the live column it names, and present a record and a schema back with
labels beside ids, so both surfaces read and write the same way.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas.virtual_table import ColumnDef, RecordRead, TableRead


class UnknownColumnError(ValueError):
    """A value keyed by something that is not one live column's id or label."""


def column_keyed(table: TableRead, values: Mapping[str, Any]) -> dict[str, Any]:
    """`values` keyed by column id, whether the caller used ids or labels.

    A label matches case-insensitively, and only a live column: an archived one
    takes no new values.

    Raises:
        UnknownColumnError: A key names no live column, or a label names more than one.
    """
    live = [column for column in table.columns if not column.archived]
    by_id = {str(column.id): column for column in live}
    by_label: dict[str, list[ColumnDef]] = {}
    for column in live:
        by_label.setdefault(column.label.casefold(), []).append(column)
    resolved: dict[str, Any] = {}
    for key, value in values.items():
        if key in by_id:
            resolved[key] = value
            continue
        matches = by_label.get(key.casefold(), [])
        if len(matches) != 1:
            known = ", ".join(f"{c.label} ({c.id})" for c in live) or "none"
            raise UnknownColumnError(
                f"{key!r} is not a column of {table.name}. Key values by a column id or "
                f"label: {known}."
            )
        resolved[str(matches[0].id)] = value
    return resolved


def labelled(table: TableRead, record: RecordRead) -> dict[str, Any]:
    """A record with its values keyed by column label, and its id and revision."""
    labels = {str(column.id): column.label for column in table.columns}
    return {
        "id": str(record.id),
        "external_id": record.external_id,
        "revision": record.revision,
        "values": {labels.get(key, key): value for key, value in record.values.items()},
    }


def schema(table: TableRead) -> dict[str, Any]:
    """A table's live schema: its columns with id, label, type and select options."""
    return {
        "id": str(table.id),
        "name": table.name,
        "description": table.description,
        "schema_version": table.schema_version,
        "columns": [
            {
                "id": str(column.id),
                "label": column.label,
                "type": column.type,
                "nullable": column.nullable,
                **(
                    {"options": [option.label for option in column.options if not option.archived]}
                    if column.options
                    else {}
                ),
            }
            for column in table.columns
            if not column.archived
        ],
    }
