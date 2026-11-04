"""Decisions made outside a chat, and the locks that keep its run continued once (#2656).

A run asked in Slack parks on two calls. Two people deciding them in the console at
once, a press holding its button, a browser resuming at the same moment: each is a
row lock held by a different transaction, and a mocked session cannot tell whether
they wait for each other in the right order. These run on Postgres.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_prompt import ChannelPrompt
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo, channel_prompt_repo
from app.services.agent_runner import AgentRunnerService
from app.services.approvals import ApprovalService
from app.services.channels.continuation import continue_in_chat
from app.services.channels.router import Admission
from app.services.parked_runs import ParkedRunService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


class _Chat:
    """A Slack run parked on two approvals, each with its button in the chat."""

    org: Organization
    owner: User
    other: User
    bot: ChannelBot
    run: AgentRun
    approvals: list[ToolApproval]
    prompts: list[uuid.UUID]
    destination: ChannelDestination

    def ctx(self, user: User) -> AuthContext:
        return AuthContext(user_id=user.id, organization_id=self.org.id, role=OrgRoleName.OWNER)


async def _chat(db: AsyncSession) -> _Chat:
    chat = _Chat()
    users = []
    for _ in range(2):
        user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
        db.add(user)
        users.append(user)
    await db.flush()
    chat.owner, chat.other = users
    chat.org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=chat.owner.id
    )
    db.add(chat.org)
    await db.flush()
    for user in users:
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=chat.org.id, user_id=user.id, role="owner"
            )
        )
    chat.bot = ChannelBot(
        organization_id=chat.org.id, platform="slack", name="Support", token_encrypted="x"
    )
    agent = Agent(
        organization_id=chat.org.id, slug=f"a-{uuid.uuid4().hex[:6]}", name="A", draft_spec={}
    )
    db.add_all([chat.bot, agent])
    await db.flush()
    chat.destination = ChannelDestination(
        bot_id=chat.bot.id, platform_chat_id="C1:1.0", private_chat=False
    )
    chat.run = AgentRun(
        id=uuid.uuid4(),
        organization_id=chat.org.id,
        agent_id=agent.id,
        user_id=chat.owner.id,
        status=RunStatus.AWAITING_APPROVAL.value,
        surface="slack",
        started_at=_NOW,
        paused_state={"channel_destination": chat.destination.model_dump(mode="json")},
    )
    db.add(chat.run)
    await db.flush()
    chat.approvals = []
    chat.prompts = []
    for index in range(2):
        approval = ToolApproval(
            id=uuid.uuid4(),
            organization_id=chat.org.id,
            run_id=chat.run.id,
            agent_id=agent.id,
            tool_id="send_email",
            tool_args={"n": index},
            status=ApprovalStatus.PENDING.value,
            created_at=_NOW,
        )
        db.add(approval)
        chat.approvals.append(approval)
    await db.flush()
    chat.run.paused_state = {
        "channel_destination": chat.destination.model_dump(mode="json"),
        "tool_call_ids": {str(a.id): f"call-{a.id}" for a in chat.approvals},
    }
    for approval in chat.approvals:
        prompt = await channel_prompt_repo.create(
            db,
            organization_id=chat.org.id,
            bot_id=chat.bot.id,
            run_id=chat.run.id,
            platform_chat_id=chat.destination.platform_chat_id,
            kind="approval",
            choices=["Approve", "Reject"],
            approval_id=approval.id,
        )
        chat.prompts.append(prompt.id)
    await db.commit()
    return chat


class _Spawns:
    """`spawn_after_commit`, recorded with the session that queued it."""

    def __init__(self) -> None:
        self.queued: list[tuple[AsyncSession, str]] = []

    def __call__(self, session: AsyncSession, coro: Any, *, name: str) -> None:
        self.queued.append((session, name))
        coro.close()

    def names(self) -> list[str]:
        return [name for _, name in self.queued]


@contextlib.contextmanager
def _spawns() -> Any:
    spawns = _Spawns()
    with (
        patch("app.services.parked_runs.spawn_after_commit", new=spawns),
        patch("app.services.approvals.spawn_after_commit", new=lambda s, c, name: c.close()),
    ):
        yield spawns


def _service(session: AsyncSession) -> ParkedRunService:
    return ParkedRunService(session, runner=MagicMock(), approvals=ApprovalService(session))


async def test_two_people_deciding_a_chat_runs_two_calls_at_once_continue_it_exactly_once(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    chat = await _chat(db)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_a = factory()
    b_task: asyncio.Task[Any] | None = None
    try:
        with _spawns() as spawns:
            first = await _service(session_a).decide(
                chat.ctx(chat.owner), chat.approvals[0].id, approved=True, note=None
            )

            async def decide_b() -> Any:
                async with factory() as session_b:
                    decided = await _service(session_b).decide(
                        chat.ctx(chat.other), chat.approvals[1].id, approved=True, note=None
                    )
                    await session_b.commit()
                    return decided, session_b

            b_task = asyncio.create_task(decide_b())
            await asyncio.sleep(0.4)
            assert not b_task.done()  # B waits for the run A holds
            await session_a.commit()
            second, session_b = await asyncio.wait_for(b_task, 5)
            b_task = None
            names = spawns.names()
            queued_by = [session for session, _ in spawns.queued]
    finally:
        if b_task is not None:
            b_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await b_task
        await session_a.close()

    assert first.continues_in_chat and second.continues_in_chat
    assert names == [f"channel-continuation:{chat.run.id}"]
    assert queued_by == [session_b]
    async with factory() as check:
        statuses = [
            (await check.get(ToolApproval, approval.id)).status for approval in chat.approvals
        ]
    assert statuses == [ApprovalStatus.APPROVED.value] * 2


async def test_a_decision_waits_for_the_run_before_it_touches_the_approval(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    chat = await _chat(db)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_s, session_a, session_c = factory(), factory(), factory()
    task: asyncio.Task[Any] | None = None
    try:
        await agent_run_repo.claim_parked_run(session_s, chat.run.id, organization_id=chat.org.id)
        with _spawns():
            task = asyncio.create_task(
                _service(session_a).decide(
                    chat.ctx(chat.owner), chat.approvals[0].id, approved=True, note=None
                )
            )
            await asyncio.sleep(0.4)
            # The approval is still free, so the decide has not reached it.
            await session_c.execute(
                text("SELECT id FROM tool_approvals WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": chat.approvals[0].id},
            )
            await session_c.rollback()
            assert not task.done()
            await session_s.rollback()
            await asyncio.wait_for(task, 5)
            task = None
            await session_a.commit()
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, DBAPIError):
                await task
        for session in (session_s, session_a, session_c):
            await session.close()


async def test_a_press_holding_its_button_does_not_block_a_console_decision(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    chat = await _chat(db)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_p, session_a = factory(), factory()
    try:
        # A press claims its button first, as it does, and has not finished.
        held = await channel_prompt_repo.claim(session_p, chat.prompts[0], bot_id=chat.bot.id)
        assert held is not None
        with _spawns():
            decided = await asyncio.wait_for(
                _service(session_a).decide(
                    chat.ctx(chat.owner), chat.approvals[0].id, approved=True, note=None
                ),
                2,
            )
            await session_a.commit()
        assert decided.continues_in_chat

        # The press's button is still open: the settle skipped the row it holds.
        async with factory() as check:
            row = await check.get(ChannelPrompt, chat.prompts[0])
            assert row is not None
            assert row.answered_at is None
        # Its own run claim now sees the decision.
        await agent_run_repo.claim_parked_run(session_p, chat.run.id, organization_id=chat.org.id)
        approval = await agent_run_repo.get_approval(
            session_p, chat.approvals[0].id, organization_id=chat.org.id
        )
        assert approval is not None
        assert approval.status == ApprovalStatus.APPROVED.value
    finally:
        await session_p.rollback()
        await session_p.close()
        await session_a.close()


@asynccontextmanager
async def _context_on(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def test_a_continuation_that_finds_the_browser_already_resumed_says_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """(pinning) The run is read parked, then the browser's resume wins the claim."""
    chat = await _chat(db)
    for approval in chat.approvals:
        approval.status = ApprovalStatus.APPROVED.value
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    browser = factory()
    resume = AsyncMock()
    notice = AsyncMock()
    task: asyncio.Task[Any] | None = None
    try:
        claimed = await agent_run_repo.claim_parked_run(
            browser, chat.run.id, organization_id=chat.org.id
        )
        assert claimed is not None
        await agent_run_repo.mark_running(browser, run=claimed)
        module = "app.services.channels.continuation"
        router = MagicMock(admission=AsyncMock(return_value=Admission("admitted", "member")))
        with (
            patch(f"{module}.get_db_context", new=lambda: _context_on(engine)),
            patch(
                f"{module}.decider_context",
                new=AsyncMock(
                    return_value=AuthContext(
                        user_id=chat.owner.id, organization_id=chat.org.id, role=OrgRoleName.OWNER
                    )
                ),
            ),
            patch(f"{module}.incoming_for_run", new=AsyncMock(return_value=MagicMock())),
            patch(f"{module}.ChannelMessageRouter", return_value=router),
            patch(f"{module}.AgentRunnerService", return_value=MagicMock(resume=resume)),
            patch(f"{module}.queue_notices", new=notice),
        ):
            task = asyncio.create_task(
                continue_in_chat(
                    organization_id=chat.org.id,
                    run_id=chat.run.id,
                    decider_user_id=chat.owner.id,
                    impersonator_id=None,
                    destination=chat.destination,
                    approval_id=chat.approvals[-1].id,
                )
            )
            await asyncio.sleep(0.4)
            assert not task.done()  # waiting on the browser's row lock
            await browser.commit()
            await asyncio.wait_for(task, 5)
            task = None
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await browser.close()

    resume.assert_not_awaited()
    notice.assert_not_awaited()


async def test_a_continuation_that_finds_the_run_re_parked_on_a_question_says_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """(pinning) The browser's Resume wins the claim and the run waits on a question now."""
    chat = await _chat(db)
    for approval in chat.approvals:
        approval.status = ApprovalStatus.APPROVED.value
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    browser = factory()
    resume = AsyncMock()
    notice = AsyncMock()
    task: asyncio.Task[Any] | None = None
    try:
        claimed = await agent_run_repo.claim_parked_run(
            browser, chat.run.id, organization_id=chat.org.id
        )
        assert claimed is not None
        await agent_run_repo.mark_running(browser, run=claimed)
        claimed.status = RunStatus.AWAITING_ANSWER.value
        claimed.paused_state = {
            "channel_destination": chat.destination.model_dump(mode="json"),
            "tool_call_ids": {},
            "questions": ["q1"],
        }
        module = "app.services.channels.continuation"
        router = MagicMock(admission=AsyncMock(return_value=Admission("refused", "access_policy")))
        with (
            patch(f"{module}.get_db_context", new=lambda: _context_on(engine)),
            patch(
                f"{module}.decider_context",
                new=AsyncMock(
                    return_value=AuthContext(
                        user_id=chat.owner.id, organization_id=chat.org.id, role=OrgRoleName.OWNER
                    )
                ),
            ),
            patch(f"{module}.incoming_for_run", new=AsyncMock(return_value=MagicMock())),
            patch(f"{module}.ChannelMessageRouter", return_value=router),
            patch(f"{module}.AgentRunnerService", return_value=MagicMock(resume=resume)),
            patch(f"{module}.queue_notices", new=notice),
        ):
            task = asyncio.create_task(
                continue_in_chat(
                    organization_id=chat.org.id,
                    run_id=chat.run.id,
                    decider_user_id=chat.owner.id,
                    impersonator_id=None,
                    destination=chat.destination,
                    approval_id=chat.approvals[-1].id,
                )
            )
            await asyncio.sleep(0.4)
            assert not task.done()  # waiting on the browser's row lock
            await browser.commit()
            await asyncio.wait_for(task, 5)
            task = None
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await browser.close()

    resume.assert_not_awaited()
    notice.assert_not_awaited()
    async with factory() as check:
        row = await check.get(AgentRun, chat.run.id)
        assert row is not None
        assert row.chat_notice_sent_at is None


async def test_a_stray_resume_behind_the_servers_continuation_is_refused_with_the_runs_status(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """(pinning) The browser's resume that arrives second answers 400 and names `running`."""
    chat = await _chat(db)
    for approval in chat.approvals:
        approval.status = ApprovalStatus.APPROVED.value
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_a, session_b = factory(), factory()
    task: asyncio.Task[Any] | None = None
    try:
        claimed = await agent_run_repo.claim_parked_run(
            session_a, chat.run.id, organization_id=chat.org.id
        )
        assert claimed is not None
        await agent_run_repo.mark_running(session_a, run=claimed)
        task = asyncio.create_task(
            AgentRunnerService(session_b).resume(chat.ctx(chat.owner), chat.run.id)
        )
        await asyncio.sleep(0.4)
        assert not task.done()
        await session_a.commit()
        with pytest.raises(BadRequestError) as refused:
            await asyncio.wait_for(task, 5)
        task = None
        assert refused.value.details["status"] == RunStatus.RUNNING.value
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await session_b.rollback()
        await session_a.close()
        await session_b.close()
