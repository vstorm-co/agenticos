"""Only an expected busy-row refusal may be skipped by automatic promotion."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import agent_repo

pytestmark = pytest.mark.anyio


async def test_try_lock_does_not_hide_a_database_failure(
    mock_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = DBAPIError(
        "SELECT", {}, RuntimeError("Database unavailable"), connection_invalidated=True
    )

    @asynccontextmanager
    async def nested() -> AsyncIterator[None]:
        yield

    monkeypatch.setattr(mock_db_session, "begin_nested", nested)
    monkeypatch.setattr(mock_db_session, "execute", AsyncMock(side_effect=failure))
    with pytest.raises(DBAPIError) as refused:
        await agent_repo.try_lock(mock_db_session, uuid4(), organization_id=uuid4())
    assert refused.value is failure
