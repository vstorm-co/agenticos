"""`doctor`'s query-statistics line on a real Postgres (#2228).

The check reads a view that may not exist. Postgres aborts the transaction on
that error, and every check after this one shares the session - so the read is
taken under a savepoint, and only a real server can say the session survives it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands.doctor import _query_statistics

pytestmark = pytest.mark.anyio


async def test_the_session_still_answers_after_the_check(db: AsyncSession) -> None:
    status, _detail = await _query_statistics(db)

    # Recording where the test server preloads the library; otherwise reported.
    assert status in {"healthy", "unconfigured"}
    assert (await db.execute(text("SELECT 1"))).scalar() == 1
