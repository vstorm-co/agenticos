"""Guarantees about `run_manifests` that only a database can make.

Three, and each is a decision the schema carries rather than the code: one
record per run, so a run finished twice - once when it parks on an approval,
once when it is resumed and ends - replaces rather than accumulates; the record
goes when the run goes, so deleting a run cannot leave a document naming a run
that is not there; and it goes when the organization goes, which is the only
thing that makes "delete my tenant" mean what it says about a table holding a
copy of every prompt the tenant ever sent.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.manifest import RunRecorder
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.run_manifest import RunManifest
from app.db.models.user import User
from app.repositories import run_manifest_repo
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    return org


async def _run(db, org: Organization) -> AgentRun:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        surface="api",
        status="completed",
    )
    db.add(run)
    await db.flush()
    return run


async def test_a_run_has_at_most_one_record(db) -> None:
    org = await _org(db)
    run = await _run(db, org)
    db.add(RunManifest(run_id=run.id, organization_id=org.id, payload={}, truncated=False))
    await db.flush()

    db.add(RunManifest(run_id=run.id, organization_id=org.id, payload={}, truncated=False))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_recording_twice_replaces_rather_than_raises(db) -> None:
    """What a parked run does: finished once when it stops on an approval and
    again when it is resumed, and the second record is the one describing the
    whole run."""
    org = await _org(db)
    run = await _run(db, org)

    await run_manifest_repo.record(
        db,
        run_id=run.id,
        organization_id=org.id,
        payload={"instructions": "first"},
        truncated=False,
    )
    await run_manifest_repo.record(
        db,
        run_id=run.id,
        organization_id=org.id,
        payload={"instructions": "second"},
        truncated=True,
    )

    stored = (await db.execute(select(RunManifest).where(RunManifest.run_id == run.id))).scalars()
    rows = list(stored)
    assert [row.payload["instructions"] for row in rows] == ["second"]
    assert rows[0].truncated is True


async def test_a_deleted_run_takes_its_record_with_it(db) -> None:
    org = await _org(db)
    run = await _run(db, org)
    await run_manifest_repo.record(
        db, run_id=run.id, organization_id=org.id, payload={}, truncated=False
    )

    await db.delete(run)
    await db.flush()

    left = (await db.execute(select(RunManifest).where(RunManifest.run_id == run.id))).scalars()
    assert list(left) == []


async def test_a_record_from_another_organization_is_not_readable(db) -> None:
    """The row carries the tenant so the read can filter on it, and the read
    does. A manifest holds every prompt a run sent; reaching one through a
    neighbour's run id is the leak this column exists to prevent."""
    mine, theirs = await _org(db), await _org(db)
    run = await _run(db, theirs)
    await run_manifest_repo.record(
        db,
        run_id=run.id,
        organization_id=theirs.id,
        payload={"instructions": "theirs"},
        truncated=False,
    )

    assert await run_manifest_repo.get_by_run(db, run.id, mine.id) is None
    assert await run_manifest_repo.get_by_run(db, run.id, theirs.id) is not None


async def test_a_record_the_database_refuses_does_not_take_the_session_with_it(db) -> None:
    """The half that swallowing the exception does not buy on its own.

    A failed flush leaves the session unusable, so without a SAVEPOINT the next
    statement raises and the run's own terminal write is lost to a record nobody
    asked for. A NUL byte is a document Postgres genuinely refuses, which a mock
    raising on demand would not prove anything about.
    """
    org = await _org(db)
    run = await _run(db, org)
    recorder = RunRecorder()
    recorder.instructions = "Be brief.\x00"
    prepared = MagicMock(run=run, built=MagicMock(recorder=recorder))

    await AgentRunnerService(db)._record_manifest(prepared)

    assert await run_manifest_repo.get_by_run(db, run.id, org.id) is None
    # The session is still usable, which is the whole claim.
    run.status = "failed"
    await db.flush()
