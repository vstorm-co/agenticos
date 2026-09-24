"""The per-source run lock, asked of a real Postgres.

What it promises - a second session cannot take it, and closing the first
releases it - is Postgres's behaviour and nothing a mock can show.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.locks import LockScope, try_hold_subject_on_connection

pytestmark = pytest.mark.anyio


class TestOneRunOfASourceAtATime:
    async def test_a_second_connection_cannot_take_the_lock_until_the_first_closes(
        self, engine: AsyncEngine
    ) -> None:
        """Held across the commit the check makes - the lock is the connection's,
        not the transaction's - and gone with the connection, with nothing to unlock."""
        subject = uuid.uuid4()
        scope = LockScope.SYNC_SOURCE_RUN
        async with engine.connect() as first:
            assert await try_hold_subject_on_connection(first, scope, subject)
            async with engine.connect() as second:
                assert not await try_hold_subject_on_connection(second, scope, subject)
                assert await try_hold_subject_on_connection(second, scope, uuid.uuid4())
            await first.invalidate()
        async with engine.connect() as third:
            assert await try_hold_subject_on_connection(third, scope, subject)

    async def test_a_worker_connection_holds_the_lock_for_its_whole_block(
        self, engine: AsyncEngine
    ) -> None:
        """What `_exclusive_source_run` stands on: through `get_worker_connection`,
        a NullPool engine of its own on the suite's database, the lock survives
        until the block exits."""
        from app.db.session import get_worker_connection

        subject = uuid.uuid4()
        scope = LockScope.SYNC_SOURCE_RUN
        async with get_worker_connection() as held:
            assert await try_hold_subject_on_connection(held, scope, subject)
            async with engine.connect() as other:
                assert not await try_hold_subject_on_connection(other, scope, subject)
        async with engine.connect() as after:
            assert await try_hold_subject_on_connection(after, scope, subject)
