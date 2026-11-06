"""The collection-teardown advisory lock actually serializes, against a real DB (#1355).

`KnowledgeBaseService`/`CollectionAccessService`'s claim path and the durable
teardown both take `hold_name(..., LockScope.COLLECTION_TEARDOWN, name)` so a base
created between the drop's reference re-check and its `DROP TABLE` keeps its table.
A mocked session cannot show a Postgres advisory lock blocking a second holder;
this proves the two contend on one collection name and do not on two.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.locks import LockScope, hold_name, hold_name_within, try_hold_name
from app.db.models.collection_teardown import CollectionTeardown
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


async def test_list_stale_returns_only_reservations_older_than_the_cutoff(
    db: AsyncSession,
) -> None:
    """The sweep reaps a reservation only once it is older than the cutoff, so a
    teardown still legitimately in flight is left alone. A mocked session cannot show
    the timestamp predicate filtering; this drives it against real rows (#1364).
    """
    fresh = f"fresh{uuid.uuid4().hex[:12]}"
    stale = f"stale{uuid.uuid4().hex[:12]}"
    await collection_teardown_repo.reserve(db, fresh)
    db.add(
        CollectionTeardown(collection_name=stale, created_at=datetime.now(UTC) - timedelta(hours=2))
    )
    await db.flush()

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    names = {
        row.collection_name
        for row in await collection_teardown_repo.list_stale(db, older_than=cutoff)
    }

    assert stale in names
    assert fresh not in names


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


def _member() -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )


async def _lock_waiters(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        waiting = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )
    return int(waiting or 0)


# Far past the claim's own wait, so a claim with none fails here and not by hanging
# the suite; well inside it would be a timing test.
_NO_CLAIM_TAKES_THIS_LONG = 5.0


class TestAClaimOnAHeldName:
    """A name can be held for as long as a document takes to insert, and a claim
    waiting for it holds a pooled connection. Fifteen of them starve every other
    request of the API, so the wait is bounded and ends in a 409 (#2747)."""

    async def test_it_is_refused_and_leaves_the_session_usable(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        name = f"kbheld{uuid.uuid4().hex[:12]}"
        async with factory() as holder, factory() as claimant:
            await hold_name(holder, LockScope.COLLECTION_TEARDOWN, name)
            started = time.monotonic()
            with pytest.raises(AlreadyExistsError) as refused:
                await asyncio.wait_for(
                    CollectionAccessService(claimant).claim(_member(), name),
                    timeout=_NO_CLAIM_TAKES_THIS_LONG,
                )
            assert time.monotonic() - started < _NO_CLAIM_TAKES_THIS_LONG / 2
            assert await _lock_waiters(engine) == 0
            assert "try again" in refused.value.message
            assert "timeout" not in refused.value.message
            assert refused.value.details == {"collection": name}

            # The refusal aborted a savepoint and not the transaction, so what the
            # request wrote before it, and writes after it, are still committable.
            await collection_teardown_repo.reserve(claimant, name)
            await claimant.commit()
            await holder.rollback()
        async with factory() as reader:
            assert await collection_teardown_repo.is_reserved(reader, name)

    async def test_a_burst_gives_every_connection_back(self, engine: AsyncEngine) -> None:
        """Twice the pool's claims, all refused: the second half got a connection
        because the first gave theirs up, and an unrelated query is served after a
        wait of about one claim's, where an unbounded claim never lets it through."""
        small = create_async_engine(
            engine.url.render_as_string(hide_password=False),
            pool_size=2,
            max_overflow=0,
            pool_timeout=_NO_CLAIM_TAKES_THIS_LONG,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        pool = async_sessionmaker(small, expire_on_commit=False)
        name = f"kbburst{uuid.uuid4().hex[:12]}"

        async def claim() -> None:
            async with pool() as session:
                await CollectionAccessService(session).claim(_member(), name)

        async def unrelated() -> None:
            async with pool() as session:
                await session.execute(text("SELECT 1"))

        claims: list[asyncio.Future[None]] = []
        try:
            async with factory() as holder:
                await hold_name(holder, LockScope.COLLECTION_TEARDOWN, name)
                claims = [asyncio.ensure_future(claim()) for _ in range(4)]
                await asyncio.sleep(0.1)
                await asyncio.wait_for(unrelated(), timeout=_NO_CLAIM_TAKES_THIS_LONG - 1)
                outcomes = await asyncio.gather(*claims, return_exceptions=True)
                await holder.rollback()
            assert [type(outcome) for outcome in outcomes] == [AlreadyExistsError] * 4
            assert small.pool.checkedout() == 0  # ty: ignore[unresolved-attribute]
        finally:
            for pending in claims:
                pending.cancel()
            await small.dispose()

    async def test_a_name_freed_during_the_wait_is_claimed(self, engine: AsyncEngine) -> None:
        """A write of an ordinary document ends inside the wait, so it costs a claim a
        moment rather than a refusal. And the claim keeps the name once the savepoint
        it was taken in is gone: a teardown still has to wait for this request."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        name = f"kbfreed{uuid.uuid4().hex[:12]}"
        async with factory() as holder, factory() as claimant, factory() as teardown:
            await hold_name(holder, LockScope.COLLECTION_TEARDOWN, name)
            claim = asyncio.ensure_future(CollectionAccessService(claimant).claim(_member(), name))
            await asyncio.sleep(0.1)
            assert not claim.done()

            await holder.rollback()
            await asyncio.wait_for(claim, timeout=_NO_CLAIM_TAKES_THIS_LONG)

            assert not await try_hold_name(teardown, LockScope.COLLECTION_TEARDOWN, name)
            await claimant.rollback()
            assert await try_hold_name(teardown, LockScope.COLLECTION_TEARDOWN, name)

    @pytest.mark.parametrize("held", [False, True], ids=["claimed", "refused"])
    async def test_the_bound_stays_with_the_name(self, engine: AsyncEngine, held: bool) -> None:
        """The claim's later statements wait for a row or a table as they always did:
        one more lock of this request, cut short, would be a 500. A setting the
        session arrived with is put back rather than cleared."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        name = f"kbleak{uuid.uuid4().hex[:12]}"
        async with factory() as holder, factory() as claimant:
            if held:
                await hold_name(holder, LockScope.COLLECTION_TEARDOWN, name)
            await claimant.execute(text("SET LOCAL lock_timeout = '7s'"))
            try:
                await asyncio.wait_for(
                    CollectionAccessService(claimant).claim(_member(), name),
                    timeout=_NO_CLAIM_TAKES_THIS_LONG,
                )
            except AlreadyExistsError:
                assert held
            setting = await claimant.scalar(text("SELECT current_setting('lock_timeout')"))
            assert setting == "7s"
            await holder.rollback()


async def test_only_a_wait_that_ran_out_is_an_answer(db: AsyncSession) -> None:
    """Any other failure of the bounded hold is a bug to surface, not a busy name."""
    with pytest.raises(DBAPIError):
        await hold_name_within(db, LockScope.COLLECTION_TEARDOWN, "docs", wait_ms=-1)
