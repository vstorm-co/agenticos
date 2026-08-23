"""Where the run's transaction ends, against Postgres (#3, #12).

Only a second session can tell a flush from a commit: a flushed-but-uncommitted
row is invisible to every other connection and gone the moment the transaction
rolls back. The unit suite asserts the *order* of the commits; these assert the
consequence - the run row is readable from another session while the model is
still being called, and a run that failed or was cancelled is still in history,
with its cost, for a reader who arrives later on a connection of their own.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.usage import RequestUsage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.budget import SpendLedger
from app.agents.capabilities.compaction import ContextGauge
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.agent_runner import AgentRunnerService, ApprovalChannel, PreparedRun

pytestmark = pytest.mark.anyio


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


async def _agent(db: AsyncSession, org: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _prepared(db: AsyncSession, *, ledger: SpendLedger | None = None) -> PreparedRun:
    """A run row opened the way `prepare` opens one, with the agent stubbed.

    The recorder is emptied so `_record_manifest` returns before writing - a
    `MagicMock` there reads as a run that captured requests and sends `fit()`
    into a mock payload.
    """
    org = await _org(db)
    agent = await _agent(db, org)
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=None,
        conversation_id=None,
        surface="api",
        model_label="gpt-4.1",
        provider="openai",
        started_at=datetime.now(UTC),
    )
    built = MagicMock()
    built.ledger = ledger or SpendLedger()
    built.model_label = "gpt-4.1"
    built.context = ContextGauge()
    built.recorder = MagicMock(requests=[], instructions=None)
    return PreparedRun(
        run=run,
        agent=agent,
        spec=MagicMock(),
        built=built,
        approvals=ApprovalChannel(organization_id=org.id, agent_id=agent.id, run_id=run.id),
    )


async def _row(engine: AsyncEngine, run_id: uuid.UUID) -> AgentRun | None:
    """The run row as a connection of its own sees it - committed data only."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as fresh:
        result = await fresh.execute(select(AgentRun).where(AgentRun.id == run_id))
        return result.scalar_one_or_none()


async def test_the_run_row_is_visible_from_another_session_mid_run(
    engine: AsyncEngine, db: AsyncSession
):
    """The row is committed before the model is asked anything (#12).

    Asserted from inside the model call, on a second session: that is the whole
    window in which an operator, a budget query or a delegation panel needs the
    run to exist, and it used to be exactly the window in which it did not.
    """
    service = AgentRunnerService(db)
    prepared = await _prepared(db)
    seen: dict[str, str | None] = {}

    async def model(*_args: object, **_kwargs: object) -> MagicMock:
        row = await _row(engine, prepared.run.id)
        seen["status"] = None if row is None else row.status
        return MagicMock(output="hi")

    prepared.built.agent.run = AsyncMock(side_effect=model)
    await service._run(
        prepared,
        user_prompt="hello",
        said="hello",
        message_history=None,
        deferred_tool_results=None,
    )

    assert seen["status"] == "running"


async def test_a_failed_run_is_still_accounted_on_a_fresh_connection(
    engine: AsyncEngine, db: AsyncSession
):
    """The regression #3 names: `finish` flushed, nothing committed, the session
    exit rolled the row back - so a provider failure erased the run, its cost,
    and the budget baseline the *next* run would be checked against."""
    ledger = SpendLedger()
    ledger.record("gpt-4.1", RequestUsage(input_tokens=1_000_000), "openai")
    service = AgentRunnerService(db)
    prepared = await _prepared(db, ledger=ledger)
    prepared.built.agent.run = AsyncMock(side_effect=RuntimeError("the provider 500d"))

    with pytest.raises(RuntimeError):
        await service._run(
            prepared,
            user_prompt="hello",
            said="hello",
            message_history=None,
            deferred_tool_results=None,
        )

    row = await _row(engine, prepared.run.id)
    assert row is not None
    assert row.status == "failed"
    assert row.cost_usd == Decimal("2.00")


async def test_a_cancelled_run_is_still_accounted_on_a_fresh_connection(
    engine: AsyncEngine, db: AsyncSession
):
    """`CancelledError` is a `BaseException`: it skips the session's own
    commit-on-clean-exit entirely, so only the explicit commit in `_run` puts
    the row where a fresh connection can read it."""
    service = AgentRunnerService(db)
    prepared = await _prepared(db)
    prepared.built.agent.run = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await service._run(
            prepared,
            user_prompt="hello",
            said="hello",
            message_history=None,
            deferred_tool_results=None,
        )

    row = await _row(engine, prepared.run.id)
    assert row is not None
    assert row.status == "cancelled"
