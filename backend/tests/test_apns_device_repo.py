"""The APNs device repository's statements (#2097): each is scoped the way its
docstring says."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories import apns_device as device_repo

pytestmark = pytest.mark.anyio


def _db(result: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = result or MagicMock(rowcount=1)
    return db


def _sql(db: AsyncMock) -> str:
    return str(db.execute.await_args.args[0])


async def test_an_iphone_is_upserted_on_its_token() -> None:
    db = _db()
    await device_repo.upsert(db, user_id=uuid4(), token="ab" * 32)
    assert "ON CONFLICT (token) DO UPDATE" in _sql(db)


async def test_forgetting_is_the_owners_and_says_whether_there_was_one() -> None:
    db = _db()
    assert await device_repo.delete_for_user(db, user_id=uuid4(), token="ab" * 32)
    assert "apns_devices.user_id" in _sql(db) and "apns_devices.token" in _sql(db)
    db = _db(MagicMock(rowcount=0))
    assert not await device_repo.delete_for_user(db, user_id=uuid4(), token="ab" * 32)


async def test_the_rest_reads_and_writes_one_person_or_one_row() -> None:
    db = _db()
    await device_repo.delete_by_id(db, uuid4())
    assert "DELETE FROM apns_devices WHERE apns_devices.id" in _sql(db)
    db = _db()
    await device_repo.mark_sent(db, uuid4(), datetime.now(UTC))
    assert "SET last_sent_at" in _sql(db)
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = ["device"]
    db = _db(rows)
    assert await device_repo.list_for_user(db, uuid4()) == ["device"]
    assert "ORDER BY apns_devices.created_at" in _sql(db)


async def test_subscribed_reads_nothing_for_nobody() -> None:
    db = _db()
    assert await device_repo.subscribed(db, []) == set()
    db.execute.assert_not_called()
    someone = uuid4()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [someone]
    assert await device_repo.subscribed(_db(rows), [someone]) == {someone}
