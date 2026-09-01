"""The collection-teardown advisory lock actually serializes, against a real DB (#1355).

`KnowledgeBaseService`/`CollectionAccessService`'s claim path and the durable
teardown both take `hold_name(..., LockScope.COLLECTION_TEARDOWN, name)` so a base
created between the drop's reference re-check and its `DROP TABLE` keeps its table.
A mocked session cannot show a Postgres advisory lock blocking a second holder;
this proves the two contend on one collection name and do not on two.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.locks import LockScope, hold_name
from app.repositories import collection_teardown_repo
from app.services.collection_access import CollectionAccessService

pytestmark = pytest.mark.anyio


async def test_a_reserved_name_cannot_be_reclaimed_until_it_is_released(db: AsyncSession) -> None:
    """The tombstone a delete commits (#1362) blocks a claim of the name until the
    cleanup drops the table and releases it - so a concurrent claim cannot adopt the
    victim's still-populated table. A mocked session cannot show the reservation
    query refusing; this drives it against the real row.
    """
    ctx = AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    name = f"kbnine{uuid.uuid4().hex[:12]}"

    await collection_teardown_repo.reserve(db, name)
    with pytest.raises(AlreadyExistsError):
        await CollectionAccessService(db).claim(ctx, name)

    await collection_teardown_repo.release(db, name)
    await CollectionAccessService(db).claim(ctx, name)  # released, so no longer refused


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
