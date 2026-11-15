"""A question halfway to expiry gets one reminder, and only one (#2064).

Against Postgres because the nudge is a cross-tenant query on a status, a
timestamp and a stamp column, and what it must leave alone - a question
asked an hour ago, a run already reminded, a run parked on an approval - is
decided by that `WHERE`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.approvals import ApprovalService

pytestmark = pytest.mark.anyio


async def _agent(db: AsyncSession) -> Agent:
    user = User(
        email=f"{uuid.uuid4().hex}@example.com", hashed_password="<redacted>", is_active=True
    )
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
        surface="slack",
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
        paused_state={
            "messages": [],
            "tool_call_ids": {},
            "questions": ["ask-1"],
            "channel_destination": {
                "bot_id": str(uuid.uuid4()),
                "platform_chat_id": "C1",
                "private_chat": False,
            },
        },
    )


async def test_a_question_halfway_to_expiry_is_reminded_once_and_only_once(
    db: AsyncSession,
) -> None:
    agent = await _agent(db)
    halfway = timedelta(hours=settings.QUESTION_NUDGE_HOURS)
    due = await _parked(
        db, agent, status=RunStatus.AWAITING_ANSWER, parked_for=halfway + timedelta(minutes=5)
    )
    fresh = await _parked(
        db, agent, status=RunStatus.AWAITING_ANSWER, parked_for=timedelta(hours=1)
    )
    approval = await _parked(
        db, agent, status=RunStatus.AWAITING_APPROVAL, parked_for=halfway + timedelta(hours=1)
    )
    reminded = await _parked(
        db, agent, status=RunStatus.AWAITING_ANSWER, parked_for=halfway + timedelta(hours=1)
    )
    reminded.question_nudged_at = datetime.now(UTC) - timedelta(hours=1)
    db.add(reminded)
    await db.flush()

    assert await ApprovalService(db).nudge_unanswered() == 1
    assert await ApprovalService(db).nudge_unanswered() == 0

    await db.refresh(due)
    assert due.question_nudged_at is not None
    await db.refresh(fresh)
    assert fresh.question_nudged_at is None
    await db.refresh(approval)
    assert approval.question_nudged_at is None
