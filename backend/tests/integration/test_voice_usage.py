"""Call minutes by agent, read from the call rows the monthly limit counts (#54)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.voice_call import VoiceCall, VoiceEndReason
from app.repositories import voice_call_repo

pytestmark = pytest.mark.anyio


async def _organization(db) -> tuple[Organization, User]:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(organization)
    await db.flush()
    return organization, user


async def _agent(db, organization: Organization, owner: User, name: str) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=owner.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name=name).model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _call(
    db,
    agent: Agent,
    user: User,
    *,
    started: datetime,
    ended: datetime | None = None,
    heartbeat: datetime | None = None,
    resume_of: uuid.UUID | None = None,
) -> VoiceCall:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        status="running",
        started_at=started,
    )
    db.add(run)
    await db.flush()
    call = await voice_call_repo.create(
        db,
        organization_id=agent.organization_id,
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
        resume_of=resume_of,
        resume_token_hash="0" * 64,
        started_at=started,
    )
    if heartbeat is not None:
        await voice_call_repo.heartbeat(db, call.id, at=heartbeat, cost_usd=Decimal(0), seconds=0)
    if ended is not None:
        await voice_call_repo.end(
            db,
            call.id,
            at=ended,
            reason=VoiceEndReason.USER,
            cost_usd=Decimal(0),
            seconds=0,
            guardrail_hits=0,
        )
    return call


async def test_usage_by_agent_sums_seconds_and_counts_a_reconnect_as_the_same_call(db):
    now = datetime.now(UTC)
    organization, user = await _organization(db)
    support = await _agent(db, organization, user, "Support")
    sales = await _agent(db, organization, user, "Sales")
    # Support: a 5-minute call, dropped and resumed for 2 more minutes - one call.
    first = await _call(
        db, support, user, started=now - timedelta(minutes=20), ended=now - timedelta(minutes=15)
    )
    await _call(
        db,
        support,
        user,
        started=now - timedelta(minutes=15),
        ended=now - timedelta(minutes=13),
        resume_of=first.id,
    )
    # Sales: one call still open, counted up to its last heartbeat.
    await _call(
        db, sales, user, started=now - timedelta(minutes=3), heartbeat=now - timedelta(minutes=2)
    )
    # Another organization's call never shows.
    other, stranger = await _organization(db)
    elsewhere = await _agent(db, other, stranger, "Elsewhere")
    await _call(
        db,
        elsewhere,
        stranger,
        started=now - timedelta(minutes=9),
        ended=now - timedelta(minutes=1),
    )

    rows = await voice_call_repo.usage_by_agent(
        db, organization_id=organization.id, start=now - timedelta(days=1), end=now
    )

    assert rows == [(support.id, "Support", 420, 1), (sales.id, "Sales", 60, 1)]


async def test_calls_outside_the_window_are_left_out(db):
    now = datetime.now(UTC)
    organization, user = await _organization(db)
    support = await _agent(db, organization, user, "Support")
    for started in (now - timedelta(days=3), now + timedelta(hours=1)):
        await _call(db, support, user, started=started, ended=started + timedelta(minutes=1))

    rows = await voice_call_repo.usage_by_agent(
        db, organization_id=organization.id, start=now - timedelta(days=1), end=now
    )

    assert rows == []


async def test_a_deleted_agents_calls_still_count_without_a_name(db):
    now = datetime.now(UTC)
    organization, user = await _organization(db)
    support = await _agent(db, organization, user, "Support")
    gone = await _agent(db, organization, user, "Retired")
    await _call(
        db, support, user, started=now - timedelta(minutes=10), ended=now - timedelta(minutes=9)
    )
    await _call(
        db, gone, user, started=now - timedelta(minutes=8), ended=now - timedelta(minutes=5)
    )
    await db.delete(gone)
    await db.flush()

    rows = await voice_call_repo.usage_by_agent(
        db, organization_id=organization.id, start=now - timedelta(days=1), end=now
    )

    assert rows == [(None, None, 180, 1), (support.id, "Support", 60, 1)]
