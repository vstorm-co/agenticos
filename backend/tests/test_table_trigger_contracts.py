"""A table trigger's filter evaluator, and the reads the end-to-end suite leaves (#1785).

`holds` has to say of a record what the record query's SQL says of the same row,
or a trigger and a filtered view disagree about which records match; each case
here is one branch of `_predicate` in `app/repositories/virtual_table.py`.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.permissions import AuthContext
from app.repositories import virtual_table_trigger as trigger_repo
from app.schemas.virtual_table import ColumnDef, ColumnTypeName, FilterOp, RecordFilter
from app.schemas.virtual_table_trigger import TableTriggerCreate, TableTriggerUpdate
from app.services.virtual_tables.triggers import TableTriggerService, holds

pytestmark = pytest.mark.anyio


def _case(type_: ColumnTypeName, op: FilterOp, operand: Any, cell: Any) -> bool:
    column = ColumnDef(id=uuid.uuid4(), label="C", type=type_)
    values = {} if cell is None else {str(column.id): cell}
    return holds(column, RecordFilter(column_id=column.id, op=op, value=operand), values)


@pytest.mark.parametrize(
    ("type_", "op", "operand", "cell", "expected"),
    [
        ("text", "is_null", True, None, True),
        ("text", "is_null", False, None, False),
        ("text", "is_null", False, "a", True),
        ("text", "eq", "a", None, False),
        ("text", "ne", "a", None, False),
        ("text", "eq", "a", "a", True),
        ("text", "ne", "a", "b", True),
        ("text", "contains", "DA", "ada", True),
        ("text", "contains", "x", "ada", False),
        ("text", "starts_with", "Ad", "Ada", True),
        ("text", "starts_with", "ad", "Ada", False),
        ("single_select", "in", ["o1", "o2"], "o2", True),
        ("single_select", "in", ["o1"], "o2", False),
        ("single_select", "in", "not-a-list", "o1", False),
        ("multi_select", "contains", "o1", ["o1", "o2"], True),
        ("multi_select", "contains", "o3", ["o1", "o2"], False),
        ("integer", "gt", 80, 90, True),
        ("integer", "gte", 90, 90, True),
        ("integer", "lt", 80, 90, False),
        ("integer", "lte", 90, 90, True),
        ("number", "eq", 1.5, 1.50, True),
        ("number", "in", [1, 2.5], 2.5, True),
        ("date", "lt", "2026-09-30", "2026-09-29", True),
        ("date", "gt", "2026-09-30", "2026-09-29", False),
        ("datetime", "gte", "2026-09-29T10:30:00+00:00", "2026-09-29T12:00:00+02:00", False),
        ("datetime", "gte", "2026-09-29T10:00:00+00:00", "2026-09-29T11:00:00+00:00", True),
        ("boolean", "eq", True, True, True),
        ("boolean", "eq", True, False, False),
    ],
)
def test_a_filter_holds_where_the_record_query_would_match(
    type_: ColumnTypeName, op: FilterOp, operand: Any, cell: Any, expected: bool
) -> None:
    assert _case(type_, op, operand, cell) is expected


async def test_the_admissions_page_counts_and_lists() -> None:
    row = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    db = MagicMock(scalar=AsyncMock(return_value=3), execute=AsyncMock(return_value=result))

    assert await trigger_repo.list_admissions(db, trigger_id=uuid.uuid4(), skip=0, limit=10) == (
        [row],
        3,
    )


async def test_the_service_reads_a_triggers_admissions_through_its_table() -> None:
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    service = TableTriggerService(MagicMock())
    trigger = MagicMock(id=uuid.uuid4())
    with (
        patch.object(service, "_load_table", new=AsyncMock(return_value=MagicMock())),
        patch.object(service, "_trigger", new=AsyncMock(return_value=trigger)),
        patch.object(
            trigger_repo, "list_admissions", new=AsyncMock(return_value=([], 0))
        ) as listed,
    ):
        page = await service.admissions(ctx, uuid.uuid4(), trigger.id, skip=5, limit=10)

    assert (page.items, page.total) == ([], 0)
    listed.assert_awaited_once_with(service.db, trigger_id=trigger.id, skip=5, limit=10)


@pytest.mark.parametrize(
    "schema",
    [
        lambda mapping: TableTriggerCreate(workflow_id=uuid.uuid4(), input_mapping=mapping),
        lambda mapping: TableTriggerUpdate(input_mapping=mapping),
    ],
    ids=["create", "update"],
)
def test_two_mapping_keys_the_same_once_trimmed_are_refused(schema) -> None:
    """Trimmed silently, one of the two sources would replace the other."""
    with pytest.raises(ValidationError, match="same once spaces are trimmed"):
        schema({"email": "c1", " email": "@author"})
    assert schema({"email": "c1", "by": "@author"}).input_mapping == {
        "email": "c1",
        "by": "@author",
    }
    # Not a mapping at all is the type check's to refuse, not this one's.
    with pytest.raises(ValidationError, match="valid dictionary"):
        schema(["email"])
