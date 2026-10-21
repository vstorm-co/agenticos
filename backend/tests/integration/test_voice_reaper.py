"""The voice sweep against real rows: a dead worker's call is hung up and closed (#54).

The run's status, the approval's expiry and the call row's three columns are
each a `WHERE` that must land on the right row, which a mocked session cannot
show.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.voice_call import VoiceCall, VoiceEndReason
from app.repositories import agent_run_repo, voice_call_repo
from app.services.voice.reaper import REAPED_ERROR, VoiceCallReaper

pytestmark = pytest.mark.anyio


def _committing(engine: AsyncEngine):
    """The reaper's session factory: commit on the way out, as `get_db_context` does."""
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with factory() as own:
            yield own
            await own.commit()

    return session


async def test_a_call_whose_worker_died_is_hung_up_and_its_run_closed_at_the_recorded_cost(
    db, engine
):
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
        resume_token_hash="0" * 64,
        started_at=now - timedelta(minutes=10),
    )
    await voice_call_repo.set_provider_call_id(db, call.id, provider_call_id="rtc_dead")
    await voice_call_repo.heartbeat(
        db, call.id, at=now - timedelta(minutes=5), cost_usd=Decimal("0.42"), seconds=300
    )

    await db.commit()

    with patch("app.services.voice.reaper.hang_up_row", AsyncMock(return_value=True)) as hung:
        reaped = await VoiceCallReaper(_committing(engine)).reap(now=now)

    assert reaped == 1
    assert hung.await_args.args[1].provider_call_id == "rtc_dead"
    await db.refresh(run)
    await db.refresh(approval)
    row = (await db.execute(select(VoiceCall).where(VoiceCall.id == call.id))).scalar_one()
    await db.refresh(row)
    assert (run.status, run.cost_usd) == (RunStatus.FAILED.value, Decimal("0.42"))
    assert (approval.status, approval.decided_by_user_id) == (ApprovalStatus.EXPIRED.value, None)
    assert row.ended_at is not None and row.end_reason == "reaped" and row.hung_up_at is not None


async def _world(db):
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
    return org, agent, user


async def _live_call(db, org, agent, user, *, started_at, heartbeat_at, secret_id=None):
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        status=RunStatus.RUNNING.value,
        modality="voice",
        started_at=started_at,
    )
    db.add(run)
    await db.flush()
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
        secret_id=secret_id,
        worker_id="dead:1",
        resume_of=None,
        resume_token_hash="0" * 64,
        started_at=started_at,
    )
    await voice_call_repo.set_provider_call_id(db, call.id, provider_call_id=f"rtc_{call.id.hex}")
    await voice_call_repo.heartbeat(
        db, call.id, at=heartbeat_at, cost_usd=Decimal("0.10"), seconds=60
    )
    return call.id, run.id


async def _read(engine, call_id, run_id):
    async with _committing(engine)() as fresh:
        call = (await fresh.execute(select(VoiceCall).where(VoiceCall.id == call_id))).scalar_one()
        run = (await fresh.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
        return call, run


async def test_a_key_that_cannot_be_unsealed_does_not_stop_the_sweep(db, engine):
    """A master-key rotation leaves one row's envelope unreadable. That row used to
    raise out of the sweep, roll back the rows before it and, at the head of the
    oldest-first queue, stop every later sweep for every tenant (RR-c01)."""
    now = datetime.now(UTC)
    org, agent, user = await _world(db)
    unreadable = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Realtime key",
        kind="api_key",
        sealed_secret="not an envelope",
    )
    db.add(unreadable)
    await db.flush()
    poisoned = await _live_call(
        db,
        org,
        agent,
        user,
        started_at=now - timedelta(minutes=90),
        heartbeat_at=now - timedelta(minutes=80),
        secret_id=unreadable.id,
    )
    healthy = [
        await _live_call(
            db,
            org,
            agent,
            user,
            started_at=now - timedelta(minutes=10),
            heartbeat_at=now - timedelta(minutes=minutes),
        )
        for minutes in (5, 4)
    ]
    await db.commit()

    with patch("app.services.voice.hangup.hang_up", AsyncMock(return_value=True)):
        reaped = await VoiceCallReaper(_committing(engine)).reap(now=now)
        again = await VoiceCallReaper(_committing(engine)).reap(now=now)

    assert (reaped, again) == (2, 0)
    for call_id, run_id in healthy:
        call, run = await _read(engine, call_id, run_id)
        assert call.hung_up_at is not None and call.end_reason == "reaped"
        assert run.status == RunStatus.FAILED.value
    # Older than the provider's hour and still unhangable: retired, not retried for ever.
    call, run = await _read(engine, *poisoned)
    assert call.end_reason == "abandoned" and call.hung_up_at is not None
    assert run.status == RunStatus.FAILED.value


async def test_a_row_that_fails_mid_sweep_keeps_the_rows_before_it_closed(db, engine):
    now = datetime.now(UTC)
    org, agent, user = await _world(db)
    calls = [
        await _live_call(
            db,
            org,
            agent,
            user,
            started_at=now - timedelta(minutes=10),
            heartbeat_at=now - timedelta(minutes=minutes),
        )
        for minutes in (6, 5, 4)
    ]
    await db.commit()
    broken = calls[1][0]

    async def hang_up_row(session, row):
        if row.id == broken:
            raise RuntimeError("the provider client blew up")
        return True

    with patch("app.services.voice.reaper.hang_up_row", hang_up_row):
        reaped = await VoiceCallReaper(_committing(engine)).reap(now=now)

    assert reaped == 2
    first, _ = await _read(engine, *calls[0])
    middle, middle_run = await _read(engine, *calls[1])
    last, _ = await _read(engine, *calls[2])
    assert first.hung_up_at is not None and last.hung_up_at is not None
    assert (middle.ended_at, middle.hung_up_at, middle_run.status) == (
        None,
        None,
        RunStatus.RUNNING.value,
    )


async def test_a_teardown_still_hanging_up_is_not_reaped_from_under_it(db, engine):
    """`_teardown` commits the end, then hangs up for up to ~20 s before marking it.
    A sweep tick in that window used to fail the run with the sweep's error, which
    the teardown's `finish` then left in place on a `completed` run (RR-c04)."""
    now = datetime.now(UTC)
    org, agent, user = await _world(db)
    call_id, run_id = await _live_call(
        db,
        org,
        agent,
        user,
        started_at=now - timedelta(minutes=3),
        heartbeat_at=now - timedelta(seconds=10),
    )
    await voice_call_repo.end(
        db,
        call_id,
        at=now - timedelta(seconds=2),
        reason=VoiceEndReason.USER,
        cost_usd=Decimal("0.10"),
        seconds=170,
        guardrail_hits=0,
    )
    await db.commit()

    with patch("app.services.voice.reaper.hang_up_row", AsyncMock(return_value=True)) as hung:
        reaped = await VoiceCallReaper(_committing(engine)).reap(now=now)

    assert reaped == 0
    hung.assert_not_awaited()
    _, run = await _read(engine, call_id, run_id)
    assert (run.status, run.error) == (RunStatus.RUNNING.value, None)


async def test_an_ended_call_whose_hang_up_failed_is_reaped_once_its_end_is_stale(db, engine):
    now = datetime.now(UTC)
    org, agent, user = await _world(db)
    call_id, run_id = await _live_call(
        db,
        org,
        agent,
        user,
        started_at=now - timedelta(minutes=5),
        heartbeat_at=now - timedelta(minutes=3),
    )
    await voice_call_repo.end(
        db,
        call_id,
        at=now - timedelta(minutes=2),
        reason=VoiceEndReason.USER,
        cost_usd=Decimal("0.10"),
        seconds=170,
        guardrail_hits=0,
    )
    await db.commit()

    with patch("app.services.voice.reaper.hang_up_row", AsyncMock(return_value=True)):
        reaped = await VoiceCallReaper(_committing(engine)).reap(now=now)

    assert reaped == 1
    call, _ = await _read(engine, call_id, run_id)
    assert call.end_reason == "user" and call.hung_up_at is not None


async def test_a_finish_after_the_sweep_clears_the_sweeps_error(db, engine):
    """The run a teardown holds was loaded before a sweep failed it. `finish` writing
    `error=None` over an in-memory `None` emitted no UPDATE for the column, leaving a
    `completed` run that says the sweep hung it up (RR-c04)."""
    now = datetime.now(UTC)
    org, agent, user = await _world(db)
    _, run_id = await _live_call(
        db,
        org,
        agent,
        user,
        started_at=now - timedelta(minutes=3),
        heartbeat_at=now - timedelta(seconds=10),
    )
    await db.commit()
    held = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()

    async with _committing(engine)() as sweep:
        await agent_run_repo.close_voice_run(
            sweep,
            run_id=run_id,
            status=RunStatus.FAILED.value,
            cost_usd=Decimal("0.10"),
            ended_at=now,
            error=REAPED_ERROR,
        )
    await agent_run_repo.finish_run(
        db,
        run=held,
        status=RunStatus.COMPLETED.value,
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal("0.12"),
        cost_is_partial=False,
        ended_at=now,
        error=None,
    )
    await db.commit()

    async with _committing(engine)() as fresh:
        run = (await fresh.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
    assert (run.status, run.error) == (RunStatus.COMPLETED.value, None)


async def test_a_row_another_sweep_is_closing_is_skipped_not_waited_on(db, engine):
    """A worker's start-up sweep and the scheduled one overlap. One sweep holds each
    row it closes for the length of a provider hang-up; the other passes it by
    (`SKIP LOCKED`) rather than queueing behind it or hanging it up twice (RR-q12)."""
    import anyio

    now = datetime.now(UTC)
    org, agent, user = await _world(db)
    held_id, held_run = await _live_call(
        db,
        org,
        agent,
        user,
        started_at=now - timedelta(minutes=10),
        heartbeat_at=now - timedelta(minutes=5),
    )
    free_id, _ = await _live_call(
        db,
        org,
        agent,
        user,
        started_at=now - timedelta(minutes=10),
        heartbeat_at=now - timedelta(minutes=4),
    )
    await db.commit()
    stale_before = now - timedelta(seconds=45)

    async with async_sessionmaker(engine)() as other_sweep:
        assert await voice_call_repo.claim_unhung(other_sweep, held_id, stale_before=stale_before)
        with (
            anyio.fail_after(5),
            patch("app.services.voice.reaper.hang_up_row", AsyncMock(return_value=True)) as hung,
        ):
            reaped = await VoiceCallReaper(_committing(engine)).reap(now=now)
        await other_sweep.rollback()

    assert reaped == 1
    assert [call.args[1].id for call in hung.await_args_list] == [free_id]
    held, run = await _read(engine, held_id, held_run)
    assert (held.hung_up_at, run.status) == (None, RunStatus.RUNNING.value)
