"""Whether a scheduled source is due, asked without loading any (#2213).

`any_due_for_sync` is the worker's minute question; it must agree with
`get_due_for_sync`, which the sync check then runs over the same rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import sync_source as sync_source_repo

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
