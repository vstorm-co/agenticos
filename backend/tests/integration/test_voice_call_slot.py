"""One person, one call: two starts at once leave one call (#54).

The concurrency check counts open calls under a transaction-scoped advisory
lock taken first. Without the lock, both starts count zero and both connect -
two billed sessions for one person. A mocked session cannot show a lock
serialising two transactions; Postgres can.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import anyio
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import voice_call_repo
from app.services.voice.exceptions import VoiceRefused
from app.services.voice.starter import VoiceCallStarter

pytestmark = pytest.mark.anyio


async def _rows(factory) -> tuple[Organization, Agent, AgentRun, User]:
    async with factory() as db:
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
            status="running",
            modality="voice",
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.commit()
        return org, agent, run, user


async def test_two_starts_at_once_leave_one_call(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    org, agent, run, user = await _rows(factory)
    now = datetime.now(UTC)
    outcomes: list[str] = []

    async def start_one() -> None:
        async with factory() as db:
            starter = VoiceCallStarter(db, sessions=factory, send=AsyncMock(), heard=lambda: None)
            try:
                await starter._claim_slot(user.id, now=now)
                await voice_call_repo.create(
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
                    worker_id="host:1",
                    resume_of=None,
                    started_at=now,
                )
                await db.commit()
                outcomes.append("started")
            except VoiceRefused as refused:
                await db.rollback()
                outcomes.append(refused.reason)

    async with anyio.create_task_group() as group:
        group.start_soon(start_one)
        group.start_soon(start_one)

    assert sorted(outcomes) == ["busy", "started"]
