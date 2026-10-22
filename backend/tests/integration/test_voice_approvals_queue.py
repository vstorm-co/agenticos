"""The stale-approval sweep leaves a call's approvals to the call (#54).

A voice run's approval is decided through the call's socket and expired by the
call's own 60-second timeout; the hourly sweep must not expire it out from under
the person deciding it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent_run_repo

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


async def _approval_on(db, *, modality: str) -> ToolApproval:
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
        status=RunStatus.AWAITING_APPROVAL.value,
        surface=RunSurface.WEB.value,
        modality=modality,
        started_at=_LONG_AGO,
    )
    db.add(run)
    await db.flush()
    approval = ToolApproval(
        id=uuid.uuid4(),
        organization_id=org.id,
        run_id=run.id,
        agent_id=agent.id,
        tool_id="send_email",
        tool_args={"to": "customer@example.com"},
        status=ApprovalStatus.PENDING.value,
        created_at=_LONG_AGO,
    )
    db.add(approval)
    await db.flush()
    return approval


async def test_the_sweep_finds_a_text_runs_stale_approval_and_not_a_calls(db):
    text_row = await _approval_on(db, modality="text")
    call_row = await _approval_on(db, modality="voice")

    stale = await agent_run_repo.list_stale_approvals(
        db, older_than=datetime.now(UTC) - timedelta(hours=1)
    )

    ids = {row.id for row in stale}
    assert text_row.id in ids
    assert call_row.id not in ids
