"""Whether a scheduled source is due, asked without loading any (#2213).

`any_due_for_sync` is the worker's minute question; it must agree with
`get_due_for_sync`, which the sync check then runs over the same rows.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_job import BackgroundJob
from app.db.models.organization import Organization
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import sync_source as sync_source_repo
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio


async def _org(db: AsyncSession) -> Organization:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Org",
        slug=f"org-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _source(db: AsyncSession, organization: Organization, **fields: object) -> SyncSource:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": organization.id,
        "name": "Docs",
        "connector_type": "git",
        "config": {},
        "collection_name": "docs",
        "schedule_minutes": 60,
        "is_active": True,
    }
    values.update(fields)
    source = SyncSource(**values)
    db.add(source)
    await db.flush()
    return source


async def test_nothing_scheduled_is_nothing_due(db: AsyncSession) -> None:
    organization = await _org(db)
    await _source(db, organization, schedule_minutes=None)
    await _source(db, organization, is_active=False)
    await _source(db, organization, collection_name=None)

    assert await sync_source_repo.any_due_for_sync(db) is False
    assert await sync_source_repo.get_due_for_sync(db) == []


async def test_a_source_synced_within_its_schedule_is_not_due(db: AsyncSession) -> None:
    organization = await _org(db)
    await _source(db, organization, last_sync_at=datetime.now(UTC) - timedelta(minutes=10))

    assert await sync_source_repo.any_due_for_sync(db) is False
    assert await sync_source_repo.get_due_for_sync(db) == []


@pytest.mark.parametrize("synced_ago", [None, timedelta(minutes=61)])
async def test_a_never_synced_or_overdue_source_is_due(
    db: AsyncSession, synced_ago: timedelta | None
) -> None:
    organization = await _org(db)
    source = await _source(
        db,
        organization,
        last_sync_at=None if synced_ago is None else datetime.now(UTC) - synced_ago,
    )

    assert await sync_source_repo.any_due_for_sync(db) is True
    assert [due.id for due in await sync_source_repo.get_due_for_sync(db)] == [source.id]


async def test_the_schedule_queues_a_due_sync_with_the_log_it_opened(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The job names its own log, as a manual trigger's does: a job that dies then
    closes that log, not a later sync's (Codex, #2248). A second tick while the
    sync is still queued queues nothing and leaves no log behind."""

    @asynccontextmanager
    async def same_session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(rag_tasks, "get_worker_db_context", same_session)
    organization = await _org(db)
    source = await _source(db, organization)

    assert await rag_tasks.dispatch_due_syncs() == 1
    assert await rag_tasks.dispatch_due_syncs() == 0

    job = (
        await db.execute(
            select(BackgroundJob).where(
                BackgroundJob.kind == "sync-source",
                BackgroundJob.payload["source_id"].astext == str(source.id),
            )
        )
    ).scalar_one()
    logs = (
        (await db.execute(select(SyncLog).where(SyncLog.sync_source_id == source.id)))
        .scalars()
        .all()
    )
    assert [str(log.id) for log in logs] == [job.payload["sync_log_id"]]
    assert logs[0].status == "running"
