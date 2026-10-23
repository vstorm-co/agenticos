"""The tombstones a failed sandbox destroy leaves, on a real Postgres (#2209).

What is due, in which order, and that two sweeps never take the same row are
`WHERE`, `ORDER BY` and `FOR UPDATE SKIP LOCKED` - Postgres's answers, not a
mock's. The cascades are the schema's.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.organization import Organization
from app.db.models.pending_sandbox_destroy import PendingSandboxDestroy
from app.db.models.sandbox_connection import SandboxConnection
from app.db.models.user import User
from app.repositories import pending_sandbox_destroy as repo

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)


async def _connection(db: AsyncSession) -> SandboxConnection:
    founder = User(
        id=uuid.uuid4(), email=f"f-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x"
    )
    db.add(founder)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    connection = SandboxConnection(
        id=uuid.uuid4(), organization_id=org.id, name="Daytona", kind="daytona"
    )
    db.add(connection)
    await db.flush()
    return connection


async def _tombstone(
    db: AsyncSession, connection: SandboxConnection, ref_id: str
) -> PendingSandboxDestroy:
    return await repo.add(
        db,
        organization_id=connection.organization_id,
        connection_id=connection.id,
        ref_id=ref_id,
        scope_key=f"sc-{ref_id}",
    )


async def test_a_new_tombstone_is_due_at_once_and_reads_back(db: AsyncSession) -> None:
    connection = await _connection(db)
    added = await _tombstone(db, connection, "dt-1")

    due = await repo.claim_due(db, now=datetime.now(UTC) + timedelta(seconds=1), limit=10)

    assert [row.id for row in due] == [added.id]
    assert due[0].attempts == 0
    assert "dt-1" in repr(due[0])


async def test_a_postponed_one_waits_and_the_oldest_due_comes_first(db: AsyncSession) -> None:
    connection = await _connection(db)
    later = await _tombstone(db, connection, "later")
    sooner = await _tombstone(db, connection, "sooner")
    await repo.postpone(db, later.id, attempts=2, until=NOW + timedelta(minutes=4))
    await repo.postpone(db, sooner.id, attempts=1, until=NOW + timedelta(minutes=2))

    assert await repo.claim_due(db, now=NOW + timedelta(minutes=1), limit=10) == []
    due = await repo.claim_due(db, now=NOW + timedelta(minutes=5), limit=10)

    assert [row.ref_id for row in due] == ["sooner", "later"]
    assert due[1].attempts == 2


async def test_a_removed_one_is_gone_and_removing_it_again_is_fine(db: AsyncSession) -> None:
    connection = await _connection(db)
    added = await _tombstone(db, connection, "dt-1")

    await repo.remove(db, added.id)
    await repo.remove(db, added.id)

    assert (await db.execute(select(PendingSandboxDestroy))).scalars().all() == []


async def test_a_connections_tombstones_are_counted_for_its_deletion(db: AsyncSession) -> None:
    """What `SandboxConnectionService.delete` refuses on, one connection's alone."""
    connection = await _connection(db)
    other = await _connection(db)
    await _tombstone(db, connection, "c-1")
    await _tombstone(db, connection, "c-2")
    await _tombstone(db, other, "o-1")

    assert await repo.count_on_connection(db, connection_id=connection.id) == 2


async def test_a_connection_holding_a_tombstone_cannot_be_deleted_under_it(
    db: AsyncSession,
) -> None:
    """#2250: the cascade used to erase a tombstone written while the delete ran."""
    from sqlalchemy.exc import IntegrityError

    connection = await _connection(db)
    await _tombstone(db, connection, "dt-1")

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(delete(SandboxConnection).where(SandboxConnection.id == connection.id))

    assert await repo.count_on_connection(db, connection_id=connection.id) == 1


async def test_forgetting_a_connections_tombstones_leaves_the_others(db: AsyncSession) -> None:
    connection = await _connection(db)
    other = await _connection(db)
    await _tombstone(db, connection, "c-1")
    await _tombstone(db, connection, "c-2")
    await _tombstone(db, other, "o-1")

    assert await repo.remove_on_connection(db, connection_id=connection.id) == 2

    assert await repo.count_on_connection(db, connection_id=connection.id) == 0
    assert await repo.count_on_connection(db, connection_id=other.id) == 1


async def test_a_deleted_organization_takes_its_tombstones_with_it(db: AsyncSession) -> None:
    """The cascade is for an organization going with everything in it; a
    connection alone is refused by the service while it holds any."""
    connection = await _connection(db)
    await _tombstone(db, connection, "dt-1")

    await db.execute(delete(Organization).where(Organization.id == connection.organization_id))
    db.expunge_all()

    assert (await db.execute(select(PendingSandboxDestroy))).scalars().all() == []


async def test_two_sweeps_at_once_take_different_rows(engine: AsyncEngine) -> None:
    """`SKIP LOCKED`: the second sweep does not wait for the first, and does not
    destroy the same sandbox twice."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        connection = await _connection(setup)
        await _tombstone(setup, connection, "one")
        await _tombstone(setup, connection, "two")
        await setup.commit()

    later = datetime.now(UTC) + timedelta(seconds=1)
    async with sessions() as first, sessions() as second:
        taken = [row.ref_id for row in await repo.claim_due(first, now=later, limit=1)]
        also = {row.ref_id for row in await repo.claim_due(second, now=later, limit=10)}
        await first.rollback()
        await second.rollback()

    assert len(taken) == 1
    assert also == {"one", "two"} - set(taken)
