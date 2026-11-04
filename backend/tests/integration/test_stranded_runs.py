"""Runs decided but never continued are ended, and their chat told once (#2656).

Against Postgres because the safety net is a cross-tenant query on a status, a
surface and the last decision's time, and because what it must leave alone - a
run a continuation claimed first, a run with a call still pending - is decided
by that `WHERE` and by the run row's lock.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_prompt import APPROVAL, ChannelPrompt
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo, channel_prompt_repo
from app.services.approvals import STRANDED_AFTER, STRANDED_NOTICE_WITHIN, ApprovalService

pytestmark = pytest.mark.anyio


async def _stranded(
    db: AsyncSession,
    *,
    surface: str = "slack",
    modality: str = "text",
    status: RunStatus = RunStatus.AWAITING_APPROVAL,
    decided_ago: timedelta = timedelta(minutes=61),
    pending: bool = False,
    destination: bool = True,
    notice_sent: bool = False,
) -> tuple[AgentRun, ChannelPrompt]:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    bot = ChannelBot(organization_id=org.id, platform="slack", name="Support", token_encrypted="x")
    agent = Agent(organization_id=org.id, slug=f"a-{uuid.uuid4().hex[:6]}", name="A", draft_spec={})
    db.add_all([bot, agent])
    await db.flush()
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=user.id,
        conversation_id=None,
        surface=surface,
        modality=modality,
        model_label="m",
        provider="openai",
        secret_id=None,
        started_at=datetime.now(UTC) - timedelta(days=30),
    )
    call_id = str(uuid.uuid4())
    state: dict[str, object] = {
        "messages": [],
        "tool_call_ids": {call_id: "call-1"},
        "questions": [],
        "channel_destination": (
            {"bot_id": str(bot.id), "platform_chat_id": "C1", "private_chat": False}
            if destination
            else None
        ),
    }
    run = await agent_run_repo.finish_run(
        db,
        run=run,
        status=status.value,
        input_tokens=100,
        output_tokens=10,
        cost_usd=Decimal("0.01"),
        cost_is_partial=False,
        ended_at=datetime.now(UTC) - decided_ago - timedelta(minutes=5),
        paused_state=state,
    )
    decided_at = datetime.now(UTC) - decided_ago
    approvals = [
        ToolApproval(
            organization_id=org.id,
            run_id=run.id,
            agent_id=agent.id,
            tool_id="send_email",
            tool_args={},
            status=ApprovalStatus.APPROVED.value,
            decided_by_user_id=user.id,
            decided_at=decided_at,
        ),
        ToolApproval(
            organization_id=org.id,
            run_id=run.id,
            agent_id=agent.id,
            tool_id="send_email",
            tool_args={},
            status=(ApprovalStatus.PENDING if pending else ApprovalStatus.REJECTED).value,
            decided_by_user_id=None if pending else user.id,
            decided_at=None if pending else decided_at,
        ),
    ]
    db.add_all(approvals)
    await db.flush()
    prompt = await channel_prompt_repo.create(
        db,
        organization_id=org.id,
        bot_id=bot.id,
        run_id=run.id,
        platform_chat_id="C1",
        kind=APPROVAL,
        approval_id=approvals[0].id,
        choices=["Approve", "Reject"],
    )
    if notice_sent:
        await agent_run_repo.record_chat_notice(db, run=run, at=datetime.now(UTC))
    return run, prompt


@contextmanager
def _spawns() -> Generator[MagicMock]:
    """Patch the sweep's after-commit spawn and its notice task, recording both."""

    with (
        patch("app.services.approvals.spawn_after_commit") as spawn,
        patch(
            "app.services.approvals.queue_notices",
            new=AsyncMock(),
        ) as post,
    ):
        spawn.posted = post
        yield spawn


def _names(spawn: MagicMock) -> list[str]:
    """The run ids that were told: one task per sweep, posting each in turn."""
    told: list[str] = []
    for call in spawn.call_args_list:
        call.args[1].close()
    for call in spawn.posted.call_args_list:
        told.extend(str(notice.run_id) for notice in call.args[1])
    assert len(spawn.call_args_list) <= 1
    return told


async def test_a_chat_run_decided_over_an_hour_ago_and_never_continued_is_ended_and_its_chat_told(
    db: AsyncSession,
) -> None:
    run, prompt = await _stranded(db)

    with _spawns() as spawn:
        assert await ApprovalService(db).end_stranded() == 1
        names = _names(spawn)

    await db.refresh(run)
    await db.refresh(prompt)
    assert run.status == RunStatus.CANCELLED.value
    assert run.paused_state is None
    assert run.error == "Decided, but nothing continued the run within 1h"
    assert run.cost_usd == Decimal("0.01")
    assert prompt.answer == {"settled": "ended"}
    assert names == [str(run.id)]


async def test_a_refused_continuation_is_told_once_and_the_safety_net_ends_it_quietly(
    db: AsyncSession,
) -> None:
    run, _ = await _stranded(db, notice_sent=True)

    with _spawns() as spawn:
        assert await ApprovalService(db).end_stranded() == 1
        names = _names(spawn)

    await db.refresh(run)
    assert run.status == RunStatus.CANCELLED.value
    assert names == []


async def test_a_run_decided_long_before_the_upgrade_is_ended_without_a_notice(
    db: AsyncSession,
) -> None:
    old, _ = await _stranded(db, decided_ago=STRANDED_NOTICE_WITHIN + timedelta(days=1))
    recent, _ = await _stranded(db, decided_ago=timedelta(days=6))

    with _spawns() as spawn:
        assert await ApprovalService(db).end_stranded() == 2
        names = _names(spawn)

    await db.refresh(old)
    await db.refresh(recent)
    assert old.status == recent.status == RunStatus.CANCELLED.value
    assert old.error is not None and "7 days" in old.error
    assert recent.error == "Decided, but nothing continued the run within 1h"
    assert names == [str(recent.id)]


async def test_a_run_decided_under_an_hour_ago_is_left_for_its_continuation(
    db: AsyncSession,
) -> None:
    run, _ = await _stranded(db, decided_ago=STRANDED_AFTER - timedelta(minutes=10))

    with _spawns() as spawn:
        assert await ApprovalService(db).end_stranded() == 0
        assert _names(spawn) == []

    await db.refresh(run)
    assert run.status == RunStatus.AWAITING_APPROVAL.value


async def test_a_run_with_a_call_still_pending_is_left_to_the_expiry(db: AsyncSession) -> None:
    run, _ = await _stranded(db, pending=True)

    assert await ApprovalService(db).end_stranded() == 0

    await db.refresh(run)
    assert run.status == RunStatus.AWAITING_APPROVAL.value


@pytest.mark.parametrize(
    ("surface", "modality"),
    [("web", "text"), ("api", "text"), ("workflow", "text"), ("slack", "voice")],
)
async def test_web_api_workflow_and_voice_runs_are_never_swept_this_way(
    db: AsyncSession, surface: str, modality: str
) -> None:
    run, _ = await _stranded(db, surface=surface, modality=modality)

    assert await ApprovalService(db).end_stranded() == 0

    await db.refresh(run)
    assert run.status == RunStatus.AWAITING_APPROVAL.value


async def test_a_run_waiting_on_a_question_is_left_to_the_question_expiry(
    db: AsyncSession,
) -> None:
    run, _ = await _stranded(db, status=RunStatus.AWAITING_ANSWER)

    assert await ApprovalService(db).end_stranded() == 0

    await db.refresh(run)
    assert run.status == RunStatus.AWAITING_ANSWER.value


async def test_a_run_parked_before_its_chat_was_recorded_is_ended_without_a_notice(
    db: AsyncSession,
) -> None:
    run, _ = await _stranded(db, destination=False)

    with _spawns() as spawn:
        assert await ApprovalService(db).end_stranded() == 1
        assert _names(spawn) == []

    await db.refresh(run)
    assert run.status == RunStatus.CANCELLED.value


async def test_a_continuation_that_claimed_the_run_first_wins_against_the_sweep(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    run, _ = await _stranded(db)
    run_id, organization_id = run.id, run.organization_id
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as continuation, factory() as sweep_session:
        claimed = await agent_run_repo.claim_parked_run(
            continuation, run_id, organization_id=organization_id
        )
        assert claimed is not None
        await agent_run_repo.mark_running(continuation, run=claimed)

        with _spawns() as spawn:
            sweep = asyncio.create_task(ApprovalService(sweep_session).end_stranded())
            await asyncio.sleep(0.4)
            assert not sweep.done()
            await continuation.commit()
            assert await asyncio.wait_for(sweep, 5) == 0
            assert _names(spawn) == []
        await sweep_session.rollback()

    async with factory() as check:
        row = (await check.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
    assert row.status == RunStatus.RUNNING.value
    assert row.paused_state is not None


async def test_a_newly_decided_park_keeps_its_full_grace_period_after_an_old_listing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    run, _ = await _stranded(db)
    run_id, organization_id, agent_id, user_id = (
        run.id,
        run.organization_id,
        run.agent_id,
        run.user_id,
    )
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    selected = asyncio.Event()
    claim = agent_run_repo.claim_parked_run

    async def claim_after_listing(
        session: AsyncSession, run_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> AgentRun | None:
        selected.set()
        return await claim(session, run_id, organization_id=organization_id)

    async with factory() as continuation, factory() as sweep_session:
        current = await claim(continuation, run_id, organization_id=organization_id)
        assert current is not None
        with (
            patch.object(agent_run_repo, "claim_parked_run", new=claim_after_listing),
            _spawns() as spawn,
        ):
            sweep = asyncio.create_task(ApprovalService(sweep_session).end_stranded())
            try:
                await asyncio.wait_for(selected.wait(), 5)
                fresh = ToolApproval(
                    organization_id=organization_id,
                    run_id=run_id,
                    agent_id=agent_id,
                    tool_id="send_email",
                    tool_args={},
                    status=ApprovalStatus.APPROVED.value,
                    decided_by_user_id=user_id,
                    decided_at=datetime.now(UTC),
                )
                continuation.add(fresh)
                await continuation.flush()
                current.paused_state = {
                    **(current.paused_state or {}),
                    "tool_call_ids": {str(fresh.id): "fresh-call"},
                }
                await continuation.commit()
                assert await asyncio.wait_for(sweep, 5) == 0
                assert _names(spawn) == []
            finally:
                for call in spawn.call_args_list:
                    call.args[1].close()
                if not sweep.done():
                    sweep.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sweep
            await sweep_session.rollback()
    async with factory() as check:
        current = await check.get(AgentRun, run_id)
        assert current is not None and current.status == RunStatus.AWAITING_APPROVAL.value
        assert (
            current.paused_state is not None
            and str(fresh.id) in current.paused_state["tool_call_ids"]
        )


async def test_stranded_ending_and_required_notice_share_one_transaction(db: AsyncSession) -> None:
    from app.db.models.background_job import BackgroundJob
    from app.worker.jobs import DELIVER_CHANNEL_HANDBACK

    run, _ = await _stranded(db)
    savepoint = await db.begin_nested()
    assert await ApprovalService(db).end_stranded() == 1
    queued = (
        (
            await db.execute(
                select(BackgroundJob).where(BackgroundJob.kind == DELIVER_CHANNEL_HANDBACK.kind)
            )
        )
        .scalars()
        .all()
    )
    assert len(queued) == 1
    assert queued[0].payload["run_id"] == str(run.id)
    assert queued[0].max_attempts == 3
    assert run.status == RunStatus.CANCELLED.value
    await savepoint.rollback()
    await db.refresh(run)
    assert run.status == RunStatus.AWAITING_APPROVAL.value
    assert (
        not (
            await db.execute(
                select(BackgroundJob).where(BackgroundJob.kind == DELIVER_CHANNEL_HANDBACK.kind)
            )
        )
        .scalars()
        .all()
    )
