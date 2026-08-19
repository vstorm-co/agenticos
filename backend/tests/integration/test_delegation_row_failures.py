"""What a delegate deleted mid-run does to the run that delegated to it.

A delegation is resolved when the run starts and its row is written when the run
ends, so between those two moments somebody can delete the delegate. The insert
then violates `agent_runs.agent_id -> agents.id`, and this is the only place that
can be observed: a mocked session raises whatever the test told it to and knows
nothing about what a failed statement does to the transaction around it.

Postgres does. An aborted transaction refuses every later statement, so catching
the Python exception is not enough - without a savepoint the parent's finished
row and its cost go down with the child row that could not be written, which is
the opposite of what guarding the write was for. The money is on the parent's
row, and that row is what must survive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.capabilities.budget import SpendEntry, SpendLedger
from app.agents.manifest import RunRecorder
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.agent_runner import AgentRunnerService, PreparedRun, RecordedDelegation

pytestmark = pytest.mark.anyio

PARENT_COST = Decimal("1.00")


async def _org(db: AsyncSession) -> Organization:
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


async def _published(
    db: AsyncSession, org: Organization, *, slug: str
) -> tuple[Agent, AgentVersion]:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=slug,
        name=slug.title(),
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={"name": agent.name},
    )
    db.add(version)
    await db.flush()
    return agent, version


def _delegation(agent: Agent, version: AgentVersion, *, task_id: str) -> RecordedDelegation:
    """One finished delegation, queued as the recorder queues it during the run."""
    moment = datetime.now(UTC)
    return RecordedDelegation(
        id=uuid.uuid4(),
        agent_id=agent.id,
        agent_version_id=version.id,
        task_id=task_id,
        status=RunStatus.COMPLETED,
        model_label="claude-sonnet-4-5",
        provider="anthropic",
        secret_id=None,
        input_tokens=500,
        output_tokens=50,
        cost_usd=Decimal("0.40"),
        cost_is_partial=False,
        started_at=moment,
        ended_at=moment,
    )


def _prepared(run: AgentRun, agent: Agent, delegations: list[RecordedDelegation]) -> PreparedRun:
    """A run ready to finish, with the ledger the parent's row is written from.

    `spec`, `built` and `approvals` are what the *run loop* used and this test
    does not run one: nothing on the path from `finish` to the two writes reads
    them apart from the ledger.
    """
    ledger = SpendLedger(
        entries=[
            SpendEntry(
                model_name="gpt-4.1",
                input_tokens=1000,
                output_tokens=100,
                cost_usd=PARENT_COST,
                priced=True,
            )
        ]
    )
    return PreparedRun(
        run=run,
        agent=agent,
        spec=MagicMock(),
        # An empty channel: this run parked no approvals, so `finish` has none to
        # write. A bare `MagicMock` would make `_write_approvals` try to iterate a
        # mock and fail before the delegation write under test ran. The recorder
        # is real for the same reason - `finish` stores what the run handed its
        # model, and an empty one is what a run that reached no model has.
        built=MagicMock(ledger=ledger, recorder=RunRecorder()),
        approvals=MagicMock(requested=[]),
        delegations=delegations,
    )


class TestADeletedDelegate:
    """Resolved at run start, gone by the time its row is written."""

    async def test_the_parent_keeps_its_cost_and_the_other_delegation_is_written(self, db, engine):
        """The whole point of guarding the delegation write.

        Wrapped in one `try` around the loop, the failed insert aborted the
        transaction: `commit` then raised, everything rolled back, and a run that
        completed and spent a dollar left no finished row at all - plus the second
        delegation, which was perfectly writable, was never attempted.
        """
        org = await _org(db)
        orchestrator, _ = await _published(db, org, slug="orchestrator")
        doomed, doomed_version = await _published(db, org, slug="doomed")
        survivor, survivor_version = await _published(db, org, slug="survivor")
        parent = await agent_run_repo.create_run(
            db,
            organization_id=org.id,
            agent_id=orchestrator.id,
            agent_version_id=None,
            user_id=None,
            conversation_id=None,
            surface="api",
            model_label="gpt-4.1",
            provider="openai",
            secret_id=None,
            started_at=datetime.now(UTC),
        )
        prepared = _prepared(
            parent,
            orchestrator,
            [
                # First, so that a guard around the whole loop also loses the
                # second - the row that had nothing wrong with it.
                _delegation(doomed, doomed_version, task_id="aaaaaaaa"),
                _delegation(survivor, survivor_version, task_id="bbbbbbbb"),
            ],
        )

        # Somebody deletes the delegate while the run is still going. The
        # delegation's ids are already fixed - the parent's model was handed one
        # of them - so the insert that follows has nothing to point at.
        await db.delete(doomed)
        await db.flush()

        await AgentRunnerService(db).finish(prepared, status=RunStatus.COMPLETED)
        await db.commit()

        # Read in another session, because the question is what was committed and
        # this one's identity map would answer with what it holds either way.
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as fresh:
            finished = await fresh.get(AgentRun, parent.id)
            children = (
                (await fresh.execute(select(AgentRun).where(AgentRun.parent_run_id == parent.id)))
                .scalars()
                .all()
            )

        assert finished is not None
        assert (finished.status, finished.cost_usd) == (RunStatus.COMPLETED.value, PARENT_COST)
        assert [child.subagent_task_id for child in children] == ["bbbbbbbb"]
        assert [child.agent_id for child in children] == [survivor.id]
