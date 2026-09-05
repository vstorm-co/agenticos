"""The teardown-reservation repo reserves, checks and releases a name (#1362).

The name reserved between a collection delete's commit and its deferred table drop
is what stops a concurrent claim adopting the still-populated table. These pin the
three operations at the repository boundary; the serialization they enable is proven
end to end in `tests/integration/test_collection_teardown_lock.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import collection_teardown as repo

pytestmark = pytest.mark.anyio


async def test_reserve_writes_and_flushes() -> None:
    db = MagicMock(execute=AsyncMock(), flush=AsyncMock())

    await repo.reserve(db, "docs")

    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()


async def test_is_reserved_is_true_when_a_row_exists() -> None:
    result = MagicMock(scalar_one_or_none=MagicMock(return_value="docs"))
    db = MagicMock(execute=AsyncMock(return_value=result))

    assert await repo.is_reserved(db, "docs") is True


async def test_is_reserved_is_false_when_no_row() -> None:
    result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    db = MagicMock(execute=AsyncMock(return_value=result))

    assert await repo.is_reserved(db, "docs") is False


async def test_release_deletes_the_row_when_present() -> None:
    row = object()
    db = MagicMock(get=AsyncMock(return_value=row), delete=AsyncMock(), flush=AsyncMock())

    await repo.release(db, "docs")

    db.delete.assert_awaited_once_with(row)
    db.flush.assert_awaited_once()


async def test_release_is_a_no_op_when_the_name_carried_no_reservation() -> None:
    db = MagicMock(get=AsyncMock(return_value=None), delete=AsyncMock(), flush=AsyncMock())

    await repo.release(db, "docs")

    db.delete.assert_not_awaited()
    db.flush.assert_not_awaited()


async def test_list_stale_returns_the_rows_the_query_selects() -> None:
    rows = [MagicMock(), MagicMock()]
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db = MagicMock(execute=AsyncMock(return_value=result))

    got = await repo.list_stale(db, older_than=datetime.now(UTC))

    assert got == rows
    db.execute.assert_awaited_once()
