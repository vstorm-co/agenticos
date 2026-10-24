"""The push subscription repository's statements (#2097). What they do against
Postgres is `tests/integration/test_web_push_delivery.py`'s; this pins that each
one is scoped the way its docstring says."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories import push_subscription as push_repo

pytestmark = pytest.mark.anyio


def _db(result: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = result or MagicMock(rowcount=1)
    return db


def _sql(db: AsyncMock) -> str:
    return str(db.execute.await_args.args[0])


async def test_a_browser_is_upserted_on_its_endpoint() -> None:
    db = _db()
    await push_repo.upsert(
        db,
        user_id=uuid4(),
        endpoint="https://fcm.googleapis.com/x",
        p256dh="a",
        auth="b",
        user_agent=None,
    )
    assert "ON CONFLICT (endpoint) DO UPDATE" in _sql(db)


async def test_forgetting_is_the_owners_and_says_whether_there_was_one() -> None:
    db = _db()
    assert await push_repo.delete_for_user(db, user_id=uuid4(), endpoint="e")
    assert "push_subscriptions.user_id" in _sql(db)
    db.execute.return_value = MagicMock(rowcount=0)
    assert not await push_repo.delete_for_user(db, user_id=uuid4(), endpoint="e")
    await push_repo.delete_by_id(db, uuid4())
    assert "push_subscriptions.id" in _sql(db)


async def test_listing_and_marking_a_send() -> None:
    rows = [MagicMock(), MagicMock()]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db = _db(result)
    assert await push_repo.list_for_user(db, uuid4()) == rows
    assert "ORDER BY push_subscriptions.created_at" in _sql(db)
    result.scalars.return_value.all.return_value = [rows[0].user_id]
    assert await push_repo.subscribed(db, [uuid4()]) == {rows[0].user_id}
    assert await push_repo.subscribed(db, []) == set()
    await push_repo.mark_sent(db, uuid4(), datetime.now(UTC))
    assert "last_sent_at" in _sql(db)


async def test_push_sign_ins_merge_browsers_and_phones_within_the_requested_ids() -> None:
    db = _db()
    assert await push_repo.sessions_with_push(db, []) == set()
    db.execute.assert_not_awaited()
    first, second = uuid4(), uuid4()
    web, phones = MagicMock(), MagicMock()
    web.scalars.return_value = [first, None, first]
    phones.scalars.return_value = [second, first, None]
    db.execute.side_effect = [web, phones]

    assert await push_repo.sessions_with_push(db, [first, second]) == {first, second}
    for call, table in zip(
        db.execute.await_args_list, ("push_subscriptions", "apns_devices"), strict=True
    ):
        statement = call.args[0]
        assert f"{table}.session_id IN" in str(statement)
        assert list(statement.compile().params.values()) == [[first, second]]
