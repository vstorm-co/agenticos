"""A call being set up is not a dead call: the sweep against a slow setup (#54).

Until its first heartbeat a call's row says only when it started. Setup can take
a while - a long thread is summarised by a model before the call is seeded - and
the sweep reads a quiet row as a dead worker's, so the real rows and the real
sweep are what show whether a live call survives it.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.voice_call import VoiceCall
from app.repositories import voice_call_repo
from app.services.voice.reaper import VoiceCallReaper
from app.services.voice.session import VoiceCallSession
from app.services.voice.starter import VoiceCaller
from tests.test_voice_session import _START, FakeRealtime, FakeSocket, _started

pytestmark = pytest.mark.anyio


def _committing(engine: AsyncEngine):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with factory() as own:
            yield own
            await own.commit()

    return session


async def _call(db: AsyncSession) -> tuple[Organization, User, uuid.UUID, uuid.UUID]:
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
    now = datetime.now(UTC)
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        status=RunStatus.RUNNING.value,
        modality="voice",
        started_at=now,
    )
    db.add(run)
    await db.flush()
    # As the starter writes it: the heartbeat is the start until something beats.
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
        worker_id="this:1",
        resume_of=None,
        resume_token_hash="0" * 64,
        started_at=now,
    )
    await db.commit()
    return org, user, call.id, run.id


async def test_a_summary_slower_than_the_sweeps_patience_does_not_get_a_live_call_reaped(
    db, engine
):
    """The review's recipe (RR-c08): the seed's summary takes longer than the sweep's
    staleness threshold, and the sweep runs while it does. The call must come out of
    setup alive and end as its caller ended it, not as `reaped`."""
    org, user, call_id, run_id = await _call(db)
    sessions = _committing(engine)
    swept: list[int] = []

    async def slow_seed(own, *, conversation_id, context_window, summarise):
        await asyncio.sleep(0.8)
        swept.append(await VoiceCallReaper(sessions).reap())
        return []

    started = _started(FakeRealtime(hold=True))
    started.call_id = call_id
    started.prepared.run.id = run_id
    caller = VoiceCaller(
        ctx=AuthContext(user_id=user.id, organization_id=org.id, role="owner"),
        user_id=user.id,
        user_name="Ann",
        surface="web",
        anonymous=False,
        auth_token=None,
        embed_id=None,
        agent_id=started.prepared.agent.id,
        conversation_id=None,
    )
    # The end comes once the summary is done: one during setup would cancel it.
    socket = FakeSocket([_START, 1.5, json.dumps({"type": "end"})])
    with (
        patch("app.services.voice.reaper.STALE_AFTER_SECONDS", 0.4),
        patch("app.services.voice.session.VoiceCallStarter.start", AsyncMock(return_value=started)),
        patch("app.services.voice.session.seed_history", slow_seed),
        patch("app.services.voice.session.hang_up", AsyncMock(return_value=True)),
    ):
        session = VoiceCallSession(
            socket,
            caller,
            sessions=sessions,
            reauthorize=AsyncMock(return_value=caller.ctx),
            heartbeat_seconds=0.1,
        )
        await asyncio.wait_for(session.run(), timeout=10)

    async with sessions() as fresh:
        row = (await fresh.execute(select(VoiceCall).where(VoiceCall.id == call_id))).scalar_one()
        run = (await fresh.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
    assert swept == [0]
    assert row.end_reason == "user"
    assert run.status == RunStatus.RUNNING.value  # `finish` is the runner's, faked here
    assert socket.sent[-1] == {"type": "ended", "reason": "user"}


async def _run_through_setup(engine, org, user, call_id, run_id, seed, frames):
    started = _started(FakeRealtime(hold=True))
    started.call_id = call_id
    started.prepared.run.id = run_id
    caller = VoiceCaller(
        ctx=AuthContext(user_id=user.id, organization_id=org.id, role="owner"),
        user_id=user.id,
        user_name="Ann",
        surface="web",
        anonymous=False,
        auth_token=None,
        embed_id=None,
        agent_id=started.prepared.agent.id,
        conversation_id=None,
    )
    sessions = _committing(engine)
    with (
        patch("app.services.voice.session.VoiceCallStarter.start", AsyncMock(return_value=started)),
        patch("app.services.voice.session.seed_history", seed),
        patch("app.services.voice.session.hang_up", AsyncMock(return_value=True)),
    ):
        session = VoiceCallSession(
            FakeSocket(frames),
            caller,
            sessions=sessions,
            reauthorize=AsyncMock(return_value=caller.ctx),
            heartbeat_seconds=0.1,
        )
        await asyncio.wait_for(session.run(), timeout=10)
    async with sessions() as fresh:
        row = (await fresh.execute(select(VoiceCall).where(VoiceCall.id == call_id))).scalar_one()
        usage = await voice_call_repo.usage_by_agent(
            fresh,
            organization_id=org.id,
            start=datetime(2000, 1, 1, tzinfo=UTC),
            end=datetime.now(UTC) + timedelta(days=1),
        )
    return row, sum(seconds for _agent, _name, seconds, _calls in usage)


async def test_a_calls_row_starts_when_the_call_is_ready_so_setup_is_not_its_minutes(db, engine):
    """The caller's timer starts at `ready`; the month's minutes count from the same moment."""
    org, user, call_id, run_id = await _call(db)
    seeded: list[datetime] = []

    async def slow_seed(own, *, conversation_id, context_window, summarise):
        await asyncio.sleep(1.2)
        seeded.append(datetime.now(UTC))
        return []

    row, used = await _run_through_setup(
        engine, org, user, call_id, run_id, slow_seed, [_START, 1.6, json.dumps({"type": "end"})]
    )

    assert row.end_reason == "user"
    assert row.started_at >= seeded[0]
    assert (row.ended_at - row.started_at).total_seconds() < 1.2
    assert used == row.seconds == 0


async def test_a_call_that_fails_in_setup_counts_no_minutes(db, engine):
    """Its setup beats carry its start along, and its end stamps it: zero, as its seconds."""
    org, user, call_id, run_id = await _call(db)

    async def failing_seed(own, *, conversation_id, context_window, summarise):
        await asyncio.sleep(0.5)
        raise RuntimeError("summary failed")

    row, used = await _run_through_setup(engine, org, user, call_id, run_id, failing_seed, [_START])

    assert row.end_reason == "error"
    assert row.started_at == row.ended_at
    assert used == row.seconds == 0
