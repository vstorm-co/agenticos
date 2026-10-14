"""The voice sweep against real rows: a dead worker's call is hung up and closed (#54).

The run's status, the approval's expiry and the call row's three columns are
each a `WHERE` that must land on the right row, which a mocked session cannot
show.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.voice_call import VoiceCall
from app.repositories import voice_call_repo
from app.services.voice.reaper import VoiceCallReaper

pytestmark = pytest.mark.anyio


async def test_a_call_whose_worker_died_is_hung_up_and_its_run_closed_at_the_recorded_cost(db):
    now = datetime.now(UTC)
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
        owner_user_id=user.id,
        name="Support",
        slug=f"support-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Support").model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        status=RunStatus.RUNNING.value,
        modality="voice",
        started_at=now - timedelta(minutes=10),
    )
    db.add(run)
    await db.flush()
    approval = ToolApproval(
        id=uuid.uuid4(),
        organization_id=org.id,
        run_id=run.id,
        agent_id=agent.id,
        tool_id="send_email",
        tool_args={},
        status=ApprovalStatus.PENDING.value,
    )
    db.add(approval)
    call = await voice_call_repo.create(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        run_id=run.id,
        user_id=user.id,
        conversation_id=None,
        embed_id=None,
        surface="web",
        provider="openai",
        model="gpt-realtime",
        transport="webrtc",
        secret_id=None,
        worker_id="dead:1",
        resume_of=None,
        started_at=now - timedelta(minutes=10),
    )
    await voice_call_repo.set_provider_call_id(db, call.id, provider_call_id="rtc_dead")
    await voice_call_repo.heartbeat(
        db, call.id, at=now - timedelta(minutes=5), cost_usd=Decimal("0.42"), seconds=300
    )

    with patch("app.services.voice.reaper.hang_up_row", AsyncMock(return_value=True)) as hung:
        reaped = await VoiceCallReaper(db).reap(now=now)

    assert reaped == 1
    assert hung.await_args.args[1].provider_call_id == "rtc_dead"
    await db.refresh(run)
    await db.refresh(approval)
    row = (await db.execute(select(VoiceCall).where(VoiceCall.id == call.id))).scalar_one()
    await db.refresh(row)
    assert (run.status, run.cost_usd) == (RunStatus.FAILED.value, Decimal("0.42"))
    assert (approval.status, approval.decided_by_user_id) == (ApprovalStatus.EXPIRED.value, None)
    assert row.ended_at is not None and row.end_reason == "reaped" and row.hung_up_at is not None
