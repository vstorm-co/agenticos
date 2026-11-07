"""A run parked on an unanswered question ends after a day (#2064).

Against Postgres because the sweep is a cross-tenant query on a status and a
timestamp, and what it must leave alone - a question asked an hour ago, a run
parked on an approval - is decided by that `WHERE`.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic_ai_harness.ask_user import TIMED_OUT
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.approvals import ApprovalService

pytestmark = pytest.mark.anyio


async def _agent(db: AsyncSession) -> Agent:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    agent = Agent(
        organization_id=org.id, slug=f"clerk-{uuid.uuid4().hex[:8]}", name="Clerk", draft_spec={}
    )
    db.add(agent)
    await db.flush()
    return agent


async def _parked(
    db: AsyncSession, agent: Agent, *, status: RunStatus, parked_for: timedelta
) -> AgentRun:
    run = await agent_run_repo.create_run(
        db,
        organization_id=agent.organization_id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=None,
        conversation_id=None,
        surface="api",
        model_label="gpt-4.1",
        provider="openai",
        secret_id=None,
        started_at=datetime.now(UTC) - parked_for,
    )
    return await agent_run_repo.finish_run(
        db,
        run=run,
        status=status.value,
        input_tokens=100,
        output_tokens=10,
        cost_usd=Decimal("0.01"),
        cost_is_partial=False,
        ended_at=datetime.now(UTC) - parked_for,
        paused_state={"messages": [], "tool_call_ids": {}, "questions": ["ask-1"]},
    )


async def test_a_question_left_a_day_ends_its_run_and_nothing_younger_or_else(
    db: AsyncSession,
) -> None:
    agent = await _agent(db)
    day = timedelta(hours=settings.QUESTION_EXPIRY_HOURS)
    stale = await _parked(
        db, agent, status=RunStatus.AWAITING_ANSWER, parked_for=day + timedelta(minutes=5)
    )
    fresh = await _parked(
        db, agent, status=RunStatus.AWAITING_ANSWER, parked_for=timedelta(hours=1)
    )
    approval = await _parked(db, agent, status=RunStatus.AWAITING_APPROVAL, parked_for=day * 2)

    ended = await ApprovalService(db).expire_unanswered()

    assert ended == 1
    for run in (stale, fresh, approval):
        await db.refresh(run)
    assert stale.status == RunStatus.CANCELLED.value
    assert stale.paused_state is None
    assert stale.error is not None and "No answer within" in stale.error
    # What it spent stands.
    assert stale.cost_usd == Decimal("0.01")
    assert fresh.status == RunStatus.AWAITING_ANSWER.value
    assert approval.status == RunStatus.AWAITING_APPROVAL.value


async def test_an_empty_sweep_ends_nothing(db: AsyncSession) -> None:
    assert await ApprovalService(db).expire_unanswered() == 0


async def test_a_saved_workflow_answer_is_not_selected_for_question_expiry(
    db: AsyncSession,
) -> None:
    agent = await _agent(db)
    accepted = await _parked(
        db,
        agent,
        status=RunStatus.AWAITING_ANSWER,
        parked_for=timedelta(hours=settings.QUESTION_EXPIRY_HOURS + 1),
    )
    await agent_run_repo.keep_paused_state(
        db,
        run=accepted,
        paused_state={
            "messages": [],
            "tool_call_ids": {},
            "questions": ["ask-1"],
            "question_results": {"ask-1": {"Audience": ["My team"]}},
        },
    )

    assert await ApprovalService(db).expire_unanswered() == 0
    await db.refresh(accepted)
    assert accepted.status == RunStatus.AWAITING_ANSWER.value
    assert accepted.paused_state["question_results"] == {"ask-1": {"Audience": ["My team"]}}


async def test_a_press_that_continued_the_run_at_the_last_moment_is_not_overwritten_by_the_sweep(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    agent = await _agent(db)
    stale = await _parked(
        db,
        agent,
        status=RunStatus.AWAITING_ANSWER,
        parked_for=timedelta(hours=settings.QUESTION_EXPIRY_HOURS + 1),
    )
    run_id, organization_id = stale.id, stale.organization_id
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as press, factory() as sweep_session:
        claimed = await agent_run_repo.claim_parked_run(
            press, run_id, organization_id=organization_id
        )
        assert claimed is not None
        await agent_run_repo.mark_running(press, run=claimed)

        sweep = asyncio.create_task(ApprovalService(sweep_session).expire_unanswered())
        await asyncio.sleep(0.4)
        assert not sweep.done()
        await press.commit()
        assert await asyncio.wait_for(sweep, 5) == 0
        await sweep_session.rollback()

    async with factory() as check:
        row = (await check.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
    assert row.status == RunStatus.RUNNING.value
    assert row.paused_state is not None


def test_the_model_is_told_the_question_timed_out() -> None:
    """What the closed step reads, for the next turn in the conversation."""
    assert "did not answer in time" in TIMED_OUT
