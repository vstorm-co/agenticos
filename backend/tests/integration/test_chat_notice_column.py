"""The record that a parked chat run's chat was told it could not continue (#2656)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_run import RunStatus
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent_run_repo

pytestmark = pytest.mark.anyio


async def _parked_run(db: AsyncSession):
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(organization_id=org.id, slug=f"a-{uuid.uuid4().hex[:6]}", name="A", draft_spec={})
    db.add(agent)
    await db.flush()
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=user.id,
        conversation_id=None,
        surface="slack",
        model_label="m",
        provider="openai",
        secret_id=None,
        started_at=datetime.now(UTC),
    )
    run.status = RunStatus.AWAITING_APPROVAL.value
    await db.flush()
    return run


async def test_recording_the_chat_notice_stamps_the_run(db: AsyncSession) -> None:
    run = await _parked_run(db)
    at = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)

    run_id, organization_id = run.id, run.organization_id

    await agent_run_repo.record_chat_notice(db, run=run, at=at)
    await db.commit()

    db.expire_all()
    fresh = await agent_run_repo.get_run(db, run_id, organization_id=organization_id)
    assert fresh is not None and fresh.chat_notice_sent_at == at


async def test_taking_the_run_out_of_the_queue_clears_the_stamp(db: AsyncSession) -> None:
    run = await _parked_run(db)
    await agent_run_repo.record_chat_notice(db, run=run, at=datetime.now(UTC))

    await agent_run_repo.mark_running(db, run=run)

    assert run.chat_notice_sent_at is None
