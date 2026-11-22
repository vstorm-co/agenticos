"""Teaching-session reads lock a row only when the caller asks, and a row names itself safely."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.browser_teaching import BrowserTeachingSession
from app.repositories import browser_teaching as repo

pytestmark = pytest.mark.anyio


def _sql(db: AsyncMock) -> str:
    statement = db.scalar.await_args.args[0]
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize("locked", [False, True])
async def test_get_locks_the_row_only_when_asked(locked: bool) -> None:
    row = object()
    db = AsyncMock()
    db.scalar.return_value = row
    assert await repo.get(db, uuid4(), uuid4(), locked=locked) is row
    assert ("FOR UPDATE" in _sql(db)) is locked


@pytest.mark.parametrize("locked", [False, True])
async def test_active_for_view_locks_the_row_only_when_asked(locked: bool) -> None:
    row = object()
    db = AsyncMock()
    db.scalar.return_value = row
    assert await repo.active_for_view(db, uuid4(), uuid4(), "call", locked=locked) is row
    sql = _sql(db)
    assert ("FOR UPDATE" in sql) is locked
    assert "status IN" in sql


def test_a_session_names_itself_by_id_status_and_revision_only() -> None:
    session_id = uuid4()
    session = BrowserTeachingSession(id=session_id, status="recording", revision=3)
    assert (
        repr(session) == f"<BrowserTeachingSession(id={session_id}, status=recording, revision=3)>"
    )
