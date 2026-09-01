"""The collection-teardown advisory lock actually serializes, against a real DB (#1355).

`KnowledgeBaseService`/`CollectionAccessService`'s claim path and the durable
teardown both take `hold_name(..., LockScope.COLLECTION_TEARDOWN, name)` so a base
created between the drop's reference re-check and its `DROP TABLE` keeps its table.
A mocked session cannot show a Postgres advisory lock blocking a second holder;
this proves the two contend on one collection name and do not on two.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.locks import LockScope, hold_name

pytestmark = pytest.mark.anyio


async def test_two_holders_of_one_name_serialize(engine: AsyncEngine) -> None:
    """A second transaction blocks on the same name until the first releases it."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as first, factory() as second:
        await hold_name(first, LockScope.COLLECTION_TEARDOWN, "docs")

        blocked = asyncio.ensure_future(hold_name(second, LockScope.COLLECTION_TEARDOWN, "docs"))
        try:
            await asyncio.sleep(0.25)
            assert not blocked.done()  # the first holder still has it

            await first.rollback()  # release, transaction-scoped
            await asyncio.wait_for(blocked, timeout=5.0)
            assert blocked.exception() is None
        finally:
            blocked.cancel()


async def test_two_holders_of_different_names_do_not_block(engine: AsyncEngine) -> None:
    """Different names hash to different keys, so unrelated teardowns never queue."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as first, factory() as second:
        await hold_name(first, LockScope.COLLECTION_TEARDOWN, "docs")
        # Would hang (and time out) if the key were shared across names.
        await asyncio.wait_for(
            hold_name(second, LockScope.COLLECTION_TEARDOWN, "wiki"), timeout=5.0
        )
