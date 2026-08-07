"""A failed transcript write must not take the run row down with it.

`TranscriptService.record` runs inside `AgentRunnerService.finish`, on the session
`finish` then commits the run row through. A transcript write is best-effort - the
answer was produced and the money was spent whether or not a row describes it - so
`record` swallows its own failures. Swallowing is not enough on a real database: a
failed flush leaves the session in an aborted transaction, and the very next
statement raises `InFailedSqlTransaction` however carefully the original error was
caught. Without a SAVEPOINT around the write, catching the exception still loses the
run - its cost, its status, the fact that it happened.

Only a real database exercises this: a mocked session cannot be put into an aborted
transaction, so the unit tests in `tests/test_transcript.py` prove what gets written
and this proves the session survives what does not.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.organization import Organization
from app.db.models.user import User
from app.services.transcript import TranscriptService

pytestmark = pytest.mark.anyio


async def _org_and_agent(db) -> tuple[Organization, Agent, AgentVersion]:
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(owner)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={"name": "Clerk"},
    )
    db.add(version)
    await db.flush()
    return org, agent, version


async def test_a_failed_transcript_write_leaves_the_run_committable(db) -> None:
    """The run row commits even though recording its transcript raised.

    The transcript write is aimed at a conversation that does not exist, so
    `create_message` violates the `messages.conversation_id` foreign key and
    aborts the transaction. If `record` did not wrap that in a SAVEPOINT, the
    `db.commit()` below - standing in for `finish`'s own - would raise instead of
    persisting the run, and the run would be lost along with the transcript.
    """
    org, agent, version = await _org_and_agent(db)

    # A run object `record` will read but that is not in the session: real ids,
    # so `messages.run_id` would satisfy its own FK, and a conversation id that
    # points at nothing, so the write fails on the conversation FK alone.
    detached_run = SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        agent_id=agent.id,
        agent_version_id=version.id,
    )

    await TranscriptService(db).record(
        detached_run, prompt="how many are open?", answer="two", model_label="gpt-4.1"
    )

    # The session survived, so the run row - the record that it happened and cost
    # what it cost - lands. This is the statement that raises without the savepoint.
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        status=RunStatus.COMPLETED.value,
        surface=RunSurface.API.value,
    )
    db.add(run)
    await db.commit()

    persisted = (
        await db.execute(select(AgentRun).where(AgentRun.id == run.id))
    ).scalar_one_or_none()
    assert persisted is not None
    assert persisted.status == RunStatus.COMPLETED.value

    # And nothing from the failed transcript was left behind.
    orphan = (
        await db.execute(select(AgentRun).where(AgentRun.id == uuid.UUID(str(detached_run.id))))
    ).scalar_one_or_none()
    assert orphan is None
