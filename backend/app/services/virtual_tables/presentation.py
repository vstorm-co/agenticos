"""A table's records and schema as a caller outside the console addresses them.

An agent tool and a workflow step both write values by column - and a person
building either knows a column by its label, not its id, and a select's choice
by its label too. These helpers map a label to the live column or option it
names, and present a record and a schema back by labels, so both surfaces read
and write the same way.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas.virtual_table import CellValue, ColumnDef, RecordFilter, RecordRead, TableRead

_SELECTS = frozenset({"single_select", "multi_select"})


class UnknownColumnError(ValueError):
    """A value keyed by something that is not one live column's id or label."""


def _option_id(column: ColumnDef, value: object) -> object:
    """A choice given by its option's id or live label, as the id; anything else as it came.

    A label matches case-insensitively. What matches no option is left for the
    column's validator to refuse, naming the options there are.
    """
    if not isinstance(value, str) or any(str(option.id) == value for option in column.options):
        return value
    wanted = value.strip().casefold()
    matches = [o for o in column.options if not o.archived and o.label.casefold() == wanted]
    return str(matches[0].id) if len(matches) == 1 else value


def _chosen(column: ColumnDef, value: Any) -> Any:
    """A select's value with its choices named by label as well as id, as ids."""
    if column.type == "single_select":
        return _option_id(column, value)
    if column.type == "multi_select" and isinstance(value, list):
        return [_option_id(column, item) for item in value]
    return value


def readable(column: ColumnDef, value: CellValue) -> CellValue:
    """A select's option ids as their labels - an archived one's too; anything else as stored."""
    labels = {str(option.id): option.label for option in column.options}
    if column.type == "single_select" and isinstance(value, str):
        return labels.get(value, value)
    if column.type == "multi_select" and isinstance(value, list):
        return [labels.get(item, item) for item in value]
    return value


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
            resolved[key] = _chosen(by_id[key], value)
            continue
        matches = by_label.get(key.casefold(), [])
        if len(matches) != 1:
            known = ", ".join(f"{c.label} ({c.id})" for c in live) or "none"
            raise UnknownColumnError(
                f"{key!r} is not a column of {table.name}. Key values by a column id or "
                f"label: {known}."
            )
        resolved[str(matches[0].id)] = _chosen(matches[0], value)
    return resolved


def filters_by_label(table: TableRead, filters: list[RecordFilter]) -> list[RecordFilter]:
    """`filters` with a select's operand named by option label as well as id, as ids."""
    columns = {column.id: column for column in table.columns}
    resolved: list[RecordFilter] = []
    for condition in filters:
        column = columns.get(condition.column_id)
        if column is None or column.type not in _SELECTS or condition.op == "is_null":
            resolved.append(condition)
            continue
        value = condition.value
        if isinstance(value, list):
            # `in` names several choices, each one a single option.
            value = [_option_id(column, item) for item in value]
        else:
            value = _option_id(column, value)
        resolved.append(condition.model_copy(update={"value": value}))
    return resolved


def labelled(table: TableRead, record: RecordRead) -> dict[str, Any]:
    """A record with its values keyed by column label, a choice by its label, and its id and revision."""
    columns = {str(column.id): column for column in table.columns}
    values: dict[str, Any] = {}
    for key, value in record.values.items():
        column = columns.get(key)
        if column is None:
            values[key] = value
        else:
            values[column.label] = readable(column, value)
    return {
        "id": str(record.id),
        "external_id": record.external_id,
        "revision": record.revision,
        "values": values,
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
