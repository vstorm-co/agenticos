"""The approvals queue and its record of decisions, against Postgres.

Two views of the same rows. The queue is what somebody acts on; the decided list
is an accountability trail, and the difference between them is a `status`
parameter plus three names that live in other tables - the agent's, the person
whose run parked the call, and the person who decided it.

Those names are why this is an integration test rather than a unit one. Each is a
join, and a join is exactly the thing a mocked session will happily pretend to
have performed. A queue that shows `send_email` with no agent and no requester
beside it is a queue people approve blind, which is the failure this feature
exists to prevent.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_exposure import AgentExposure
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.repositories.agent_run import ApprovalFilters, ChatAsker
from app.services.agent_runner import AgentRunnerService
from app.services.approvals import ApprovalService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


async def _user(db, email: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db) -> tuple[Organization, User]:
    owner = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org, owner


async def _agent(db, org: Organization, name: str = "Clerk") -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        name=name,
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(db, org: Organization, agent: Agent, *, started_by: User | None) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        user_id=None if started_by is None else started_by.id,
        status=RunStatus.AWAITING_APPROVAL.value,
        surface=RunSurface.WEB.value,
        started_at=_NOW,
    )
    db.add(run)
    await db.flush()
    return run


async def _approval(db, org: Organization, run: AgentRun, **overrides) -> ToolApproval:
    row = {
        "id": uuid.uuid4(),
        "organization_id": org.id,
        "run_id": run.id,
        "agent_id": run.agent_id,
        "tool_id": "send_email",
        "tool_args": {"to": "customer@example.com"},
        "status": ApprovalStatus.PENDING.value,
        "created_at": _NOW,
    }
    row.update(overrides)
    approval = ToolApproval(**row)
    db.add(approval)
    await db.flush()
    return approval


def _ctx(org: Organization, user: User) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)


async def _chat_run(
    db,
    org: Organization,
    agent: Agent,
    *,
    publisher: User,
    fallback: bool = True,
    display_name: str | None = "Ana",
    username: str | None = None,
    with_bot: bool = True,
) -> AgentRun:
    """A run a chat account started, standing in under the binding's publisher."""
    identity = ChannelIdentity(
        id=uuid.uuid4(),
        platform="slack",
        platform_user_id=f"U{uuid.uuid4().hex[:8]}",
        platform_username=username,
        platform_display_name=display_name,
    )
    db.add(identity)
    await db.flush()
    exposure_id = None
    if with_bot:
        bot = ChannelBot(
            id=uuid.uuid4(),
            organization_id=org.id,
            platform="slack",
            name="Support",
            token_encrypted="sealed",
        )
        db.add(bot)
        await db.flush()
        exposure = AgentExposure(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            surface="slack",
            channel_bot_id=bot.id,
        )
        db.add(exposure)
        await db.flush()
        exposure_id = exposure.id
    run = await _run(db, org, agent, started_by=publisher)
    run.surface = "slack"
    run.initiated_by_publisher_fallback = fallback
    run.channel_identity_id = identity.id
    run.exposure_id = exposure_id
    await db.flush()
    return run


class TestWhatTheQueueSays:
    async def test_a_chat_strangers_call_names_their_chat_account_not_the_publisher(
        self, db
    ) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        publisher = await _user(db, email="publisher@example.com")
        await _approval(db, org, await _chat_run(db, org, agent, publisher=publisher))

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert rows[0].triggered_by_email is None
        assert rows[0].triggered_by_user_id is None
        assert rows[0].asked_in_chat == ChatAsker("slack", "Ana", "Support")

    async def test_a_stranger_without_a_display_name_falls_back_to_the_handle(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        publisher = await _user(db)
        run = await _chat_run(
            db, org, agent, publisher=publisher, display_name=None, username="ana", with_bot=False
        )
        await _approval(db, org, run)

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert rows[0].asked_in_chat == ChatAsker("slack", "@ana", None)

    async def test_a_stranger_with_neither_name_nor_handle_is_named_by_platform_id(
        self, db
    ) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        publisher = await _user(db)
        run = await _chat_run(db, org, agent, publisher=publisher, display_name=None)
        await _approval(db, org, run)
        identity = await db.get(ChannelIdentity, run.channel_identity_id)

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert identity is not None
        assert rows[0].asked_in_chat == ChatAsker("slack", identity.platform_user_id, "Support")

    async def test_a_linked_members_call_still_names_them(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        member = await _user(db, email="member@example.com")
        await _approval(db, org, await _chat_run(db, org, agent, publisher=member, fallback=False))

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert rows[0].triggered_by_email == "member@example.com"
        assert rows[0].asked_in_chat is None

    async def test_a_widget_visitors_call_is_unchanged(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        publisher = await _user(db, email="publisher@example.com")
        run = await _run(db, org, agent, started_by=publisher)
        run.initiated_by_publisher_fallback = True
        await db.flush()
        await _approval(db, org, run)

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert rows[0].triggered_by_email == "publisher@example.com"
        assert rows[0].asked_in_chat is None

    async def test_the_bubbles_count_still_counts_a_strangers_call(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        publisher = await _user(db)
        await _approval(db, org, await _chat_run(db, org, agent, publisher=publisher))

        rows, total = await agent_run_repo.list_approvals(db, organization_id=org.id, limit=1)

        assert (len(rows), total) == (1, 1)

    async def test_the_agent_and_the_person_who_triggered_it_are_named(self, db) -> None:
        """`agent_id` and a run id name nothing to an approver. The two columns a
        person reads before deciding both live in other tables."""
        org, owner = await _org(db)
        agent = await _agent(db, org, name="Billing clerk")
        asker = await _user(db, email="ada@example.com")
        await _approval(db, org, await _run(db, org, agent, started_by=asker))

        rows, total = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert total == 1
        assert rows[0].agent_name == "Billing clerk"
        assert (rows[0].triggered_by_user_id, rows[0].triggered_by_email) == (
            asker.id,
            "ada@example.com",
        )

    async def test_a_run_nobody_started_as_themselves_has_no_requester(self, db) -> None:
        """An embedded widget's visitor is anonymous, so the run carries the
        widget owner or nobody. The row still belongs on the queue - somebody has
        to decide it - so this is a blank rather than a missing row."""
        org, owner = await _org(db)
        agent = await _agent(db, org)
        await _approval(db, org, await _run(db, org, agent, started_by=None))

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert (rows[0].triggered_by_user_id, rows[0].triggered_by_email) == (None, None)

    async def test_a_pending_call_has_no_decider_yet(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        await _approval(db, org, await _run(db, org, agent, started_by=owner))

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert (rows[0].decided_by_user_id, rows[0].decided_by_email) == (None, None)

    async def test_only_what_is_waiting_in_the_callers_organization(self, db) -> None:
        """One approver deciding another tenant's tool call is the worst version of
        this feature."""
        mine, me = await _org(db)
        theirs, them = await _org(db)
        my_agent = await _agent(db, mine)
        their_agent = await _agent(db, theirs)
        ours = await _approval(db, mine, await _run(db, mine, my_agent, started_by=me))
        await _approval(db, theirs, await _run(db, theirs, their_agent, started_by=them))

        rows, total = await ApprovalService(db).list_approvals(_ctx(mine, me))

        assert ([row.id for row in rows], total) == ([ours.id], 1)

    async def test_the_queue_and_the_run_agree_on_which_runs_continue_in_chat(self, db) -> None:
        from app.services.channels.handback import continues_in_chat

        org, owner = await _org(db)
        agent = await _agent(db, org)
        destination = {"bot_id": str(uuid.uuid4()), "platform_chat_id": "C1", "private_chat": True}
        runs = []
        for surface, paused_state in (
            ("slack", {"channel_destination": destination}),
            ("slack", {"channel_destination": None}),
            ("slack", {}),
            ("web", {"channel_destination": destination}),
            ("slack", {"channel_destination": {"bot_id": str(uuid.uuid4())}}),
        ):
            run = await _run(db, org, agent, started_by=owner)
            run.surface = surface
            run.paused_state = paused_state
            await db.flush()
            await _approval(db, org, run)
            runs.append(run)
        person = _ctx(org, owner)
        key = AuthContext(
            user_id=owner.id,
            organization_id=org.id,
            role=OrgRoleName.OWNER,
            api_key_id=uuid.uuid4(),
        )

        for ctx, expected in ((person, [True, False, False, False, False]), (key, [False] * 5)):
            rows, _ = await ApprovalService(db).list_approvals(ctx)
            by_run = {row.run_id: row.continues_in_chat for row in rows}
            assert [by_run[run.id] for run in runs] == expected
            assert all(by_run[run.id] == continues_in_chat(run, ctx) for run in runs)


class TestTheQueueAndTheRecordAreTheSameRows:
    async def test_pending_only_by_default(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        run = await _run(db, org, agent, started_by=owner)
        waiting = await _approval(db, org, run)
        await _approval(db, org, run, status=ApprovalStatus.APPROVED.value)

        rows, total = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert ([row.id for row in rows], total) == ([waiting.id], 1)

    async def test_the_decided_view_names_who_decided(self, db) -> None:
        """A bare UUID is not an accountability trail."""
        org, owner = await _org(db)
        agent = await _agent(db, org)
        decider = await _user(db, email="grace@example.com")
        await _approval(
            db,
            org,
            await _run(db, org, agent, started_by=owner),
            status=ApprovalStatus.REJECTED.value,
            decided_by_user_id=decider.id,
            decided_at=_NOW,
            note="wrong recipient",
        )

        rows, total = await ApprovalService(db).list_approvals(
            _ctx(org, owner),
            filters=ApprovalFilters(
                statuses=[ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value]
            ),
        )

        assert total == 1
        assert rows[0].decided_by_email == "grace@example.com"
        assert (rows[0].status, rows[0].note) == ("rejected", "wrong recipient")

    async def test_the_queue_and_the_record_never_share_a_row(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        run = await _run(db, org, agent, started_by=owner)
        waiting = await _approval(db, org, run)
        decided = await _approval(db, org, run, status=ApprovalStatus.APPROVED.value)
        service = ApprovalService(db)

        queue, _ = await service.list_approvals(_ctx(org, owner))
        record, _ = await service.list_approvals(
            _ctx(org, owner),
            filters=ApprovalFilters(statuses=[ApprovalStatus.APPROVED.value]),
        )

        assert {row.id for row in queue} == {waiting.id}
        assert {row.id for row in record} == {decided.id}


class TestNarrowingTheQueue:
    async def test_whose_runs_parked_the_call(self, db) -> None:
        """Read off the run, not off the approval: an approval belongs to a run
        and a run belongs to a person."""
        org, owner = await _org(db)
        agent = await _agent(db, org)
        someone_else = await _user(db)
        theirs = await _approval(db, org, await _run(db, org, agent, started_by=someone_else))
        await _approval(db, org, await _run(db, org, agent, started_by=owner))

        rows, total = await ApprovalService(db).list_approvals(
            _ctx(org, owner),
            filters=ApprovalFilters(triggered_by_user_id=someone_else.id),
        )

        assert ([row.id for row in rows], total) == ([theirs.id], 1)

    async def test_asking_for_the_publishers_runs_leaves_out_the_strangers_they_stood_in_for(
        self, db
    ) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        publisher = await _user(db)
        own = await _approval(db, org, await _run(db, org, agent, started_by=publisher))
        await _approval(db, org, await _chat_run(db, org, agent, publisher=publisher))

        rows, total = await ApprovalService(db).list_approvals(
            _ctx(org, owner), filters=ApprovalFilters(triggered_by_user_id=publisher.id)
        )

        assert ([row.id for row in rows], total) == ([own.id], 1)

    async def test_a_window_over_when_the_call_was_parked(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        run = await _run(db, org, agent, started_by=owner)
        recent = await _approval(db, org, run, created_at=_NOW)
        await _approval(db, org, run, created_at=_NOW - timedelta(days=90))

        rows, total = await ApprovalService(db).list_approvals(
            _ctx(org, owner),
            filters=ApprovalFilters(created_from=_NOW - timedelta(days=7)),
        )

        assert ([row.id for row in rows], total) == ([recent.id], 1)

    async def test_the_count_narrows_with_the_page(self, db) -> None:
        """Two queries. A filter reaching one and not the other gives a total that
        describes different rows from the page under it."""
        org, owner = await _org(db)
        agent = await _agent(db, org)
        run = await _run(db, org, agent, started_by=owner)
        for _ in range(3):
            await _approval(db, org, run)
        await _approval(db, org, run, status=ApprovalStatus.APPROVED.value)

        rows, total = await ApprovalService(db).list_approvals(_ctx(org, owner), limit=2)

        assert (len(rows), total) == (2, 3)


class TestTheOrderTheQueueDrainsIn:
    async def test_oldest_first_by_default(self, db) -> None:
        """Nothing expires a parked call, so the oldest row can be from months ago
        - and it is the one somebody most needs to see. A newest-first queue would
        bury it."""
        org, owner = await _org(db)
        agent = await _agent(db, org)
        run = await _run(db, org, agent, started_by=owner)
        ancient = await _approval(db, org, run, created_at=_NOW - timedelta(days=60))
        fresh = await _approval(db, org, run, created_at=_NOW)

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner))

        assert [row.id for row in rows] == [ancient.id, fresh.id]

    async def test_newest_first_when_asked(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org)
        run = await _run(db, org, agent, started_by=owner)
        ancient = await _approval(db, org, run, created_at=_NOW - timedelta(days=60))
        fresh = await _approval(db, org, run, created_at=_NOW)

        rows, _ = await ApprovalService(db).list_approvals(_ctx(org, owner), oldest_first=False)

        assert [row.id for row in rows] == [fresh.id, ancient.id]

    async def test_calls_parked_by_one_run_still_have_a_total_order(self, db) -> None:
        """A run parks on *all* of its outstanding calls at once, in one loop
        inside one transaction, and `created_at` is `server_default=func.now()` -
        the transaction timestamp. So a fan-out's approvals share an instant
        exactly, not by coincidence, and `ORDER BY created_at` alone leaves their
        relative order to the planner: a page boundary drawn through them lets a
        row come back on two pages or on neither. `id` is the secondary key that
        makes the order total."""
        org, owner = await _org(db)
        agent = await _agent(db, org)
        run = await _run(db, org, agent, started_by=owner)
        parked = [await _approval(db, org, run) for _ in range(5)]

        expected = sorted(str(approval.id) for approval in parked)

        service = ApprovalService(db)
        paged: list[str] = []
        for skip in (0, 2, 4):
            rows, _ = await service.list_approvals(_ctx(org, owner), skip=skip, limit=2)
            paged.extend(str(row.id) for row in rows)

        # No row repeats or is skipped across the three pages, and the order is
        # the one the tiebreaker fixes.
        assert paged == expected
        assert len(set(paged)) == 5


class TestDecidingTwiceIsRefused:
    """Two approvers, one decision: the row is locked so the second is refused.

    `decide` reads the approval, checks it is pending, and writes - a check-then-act
    that, unlocked, lets a concurrent reject and approve both pass the guard and
    both write, leaving the audit trail with two contradictory entries for one
    decision (#17). The `with_for_update` in `get_approval` serializes them.

    Deterministic on purpose: one approver's decision is held open (uncommitted,
    lock still on the row) while the other's runs. With the lock the second
    blocks on the *read* and, once the first commits, re-reads a decided row and
    is refused - one audit entry. Without it the second blocks on the *write*
    instead, having already passed the guard against a `pending` read, and writes
    a second, contradictory decision. Racing the two through `gather` alone does
    not reproduce this: the pair serialises, and the first commits before the
    second reads.
    """

    async def test_a_held_decision_blocks_the_second_which_is_then_refused(
        self, db, engine
    ) -> None:
        import asyncio
        import contextlib

        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.core.exceptions import BadRequestError
        from app.db.models.audit_log import AppAdminAuditLog

        org, owner = await _org(db)
        approver_a = await _user(db)
        approver_b = await _user(db)
        db.add_all(
            [
                OrganizationMember(
                    id=uuid.uuid4(), organization_id=org.id, user_id=approver_a.id, role="admin"
                ),
                OrganizationMember(
                    id=uuid.uuid4(), organization_id=org.id, user_id=approver_b.id, role="admin"
                ),
            ]
        )
        await db.flush()
        agent = await _agent(db, org)
        run = await _run(db, org, agent, started_by=owner)
        approval = await _approval(db, org, run)
        await db.commit()

        factory = async_sessionmaker(engine, expire_on_commit=False)
        session_a = factory()
        b_task: asyncio.Task[None] | None = None
        try:
            # A decides and holds it open: the row lock stays on the approval.
            await ApprovalService(session_a).decide(
                _ctx(org, approver_a), approval.id, approved=True
            )

            async def decide_b() -> None:
                async with factory() as session_b:
                    await ApprovalService(session_b).decide(
                        _ctx(org, approver_b), approval.id, approved=False
                    )
                    await session_b.commit()

            b_task = asyncio.create_task(decide_b())
            await asyncio.sleep(0.4)
            assert not b_task.done()  # blocked on A's lock

            await session_a.commit()

            with pytest.raises(BadRequestError):
                await b_task
            b_task = None
        finally:
            if b_task is not None:
                b_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await b_task
            await session_a.close()

        async with factory() as session:
            decided = await session.get(ToolApproval, approval.id)
            assert decided.status == ApprovalStatus.APPROVED.value
            audit_rows = await session.scalar(
                select(func.count())
                .select_from(AppAdminAuditLog)
                .where(AppAdminAuditLog.target_id == str(approval.id))
            )
            assert audit_rows == 1


async def test_expiry_waits_for_a_stop_before_locking_its_approvals(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    org, owner = await _org(db)
    agent = await _agent(db, org)
    run = await _run(db, org, agent, started_by=owner)
    approval = await _approval(db, org, run)
    run.cost_usd = Decimal("2.50")
    run.input_tokens = 7
    run.output_tokens = 3
    run.paused_state = {"messages": [], "tool_call_ids": {str(approval.id): "call-1"}}
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    waiting_for_run = asyncio.Event()
    claim_run = agent_run_repo.claim_parked_run

    async def claim(
        session: AsyncSession, run_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> AgentRun | None:
        waiting_for_run.set()
        return await claim_run(session, run_id, organization_id=organization_id)

    async def sweep() -> int:
        async with factory() as session:
            result = await ApprovalService(session).expire_stale()
            await session.commit()
            return result

    async with factory() as stopping:
        service = AgentRunnerService(stopping)
        await service.cancel_parked(_ctx(org, owner), run.id)
        # Stop still owns the run and approval locks. The sweeper must wait on
        # the run before locking any approval, then re-read its committed status.
        with patch.object(agent_run_repo, "claim_parked_run", claim):
            task = asyncio.create_task(sweep())
            try:
                async with asyncio.timeout(10):
                    await waiting_for_run.wait()
                    assert not task.done()
                    await stopping.commit()
                    assert await task == 0
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await service.cancel_parked(_ctx(org, owner), run.id)
        await stopping.commit()
    async with factory() as session:
        ended = await session.get(AgentRun, run.id)
        decided = await session.get(ToolApproval, approval.id)
        assert ended is not None and decided is not None
        assert ended.status == RunStatus.CANCELLED.value
        assert ended.cost_usd == Decimal("2.50")
        assert (ended.input_tokens, ended.output_tokens) == (7, 3)
        assert ended.paused_state is None
        assert decided.status == ApprovalStatus.EXPIRED.value


@pytest.mark.parametrize("status", [RunStatus.AWAITING_ANSWER, RunStatus.AWAITING_APPROVAL])
async def test_continuation_refreshes_a_preloaded_run_after_stop(
    db: AsyncSession, engine: AsyncEngine, status: RunStatus
) -> None:
    """A second tab must observe Stop even with the run in its identity map."""
    from app.core.exceptions import BadRequestError

    org, owner = await _org(db)
    agent = await _agent(db, org)
    run = await _run(db, org, agent, started_by=owner)
    run.status = status.value
    run.paused_state = {"messages": [], "tool_call_ids": {}}
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as answering, factory() as stopping:
        service = AgentRunnerService(answering)
        loaded = await service.get_run(_ctx(org, owner), run.id)
        assert loaded.status == status.value
        await AgentRunnerService(stopping).cancel_parked(_ctx(org, owner), run.id)
        await stopping.commit()
        assert loaded.status == status.value
        with pytest.raises(BadRequestError) as refused:
            if status == RunStatus.AWAITING_ANSWER:
                await service.answer(_ctx(org, owner), run.id, {})
            else:
                await service.resume(_ctx(org, owner), run.id)
        assert loaded.status == RunStatus.CANCELLED.value
        assert refused.value.details["status"] == RunStatus.CANCELLED.value


async def _consent_chat(db: AsyncSession):
    from app.db.models.agent import AgentVersion
    from app.db.models.conversation import Conversation

    org, user = await _org(db)
    org.chat_may_waive_approvals = True
    agent = await _agent(db, org)
    version = AgentVersion(
        id=uuid.uuid4(), organization_id=org.id, agent_id=agent.id, version=1, spec={}
    )
    chat = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=user.id)
    db.add_all([version, chat])
    await db.flush()
    run = await _run(db, org, agent, started_by=user)
    run.agent_version_id = version.id
    run.conversation_id = chat.id
    await db.flush()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    return org, user, run, ctx


@pytest.mark.parametrize("scope", ["conversation", "agent"])
async def test_remembered_tool_choice_is_scoped_versioned_and_revocable(
    db: AsyncSession, scope: str
):
    from app.core.exceptions import NotFoundError
    from app.db.models.agent import AgentVersion
    from app.db.models.conversation import Conversation

    org, user, run, ctx = await _consent_chat(db)
    approval = await _approval(db, org, run)
    service = ApprovalService(db)
    with patch("app.services.approvals.spawn_after_commit") as spawn:
        spawn.side_effect = lambda _, coroutine, **kwargs: coroutine.close()
        await service.decide(ctx, approval.id, approved=True, remember_scope=scope)
    assert (
        await service.remembered_consent(ctx, run.id, tool_name="send_email", account=None)
        == user.id
    )
    assert (
        await service.remembered_consent(ctx, run.id, tool_name="delete_email", account=None)
        is None
    )
    assert (
        await service.remembered_consent(ctx, run.id, tool_name="send_email", account="another")
        is None
    )
    another = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=user.id)
    db.add(another)
    await db.flush()
    second = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=run.agent_id,
        agent_version_id=run.agent_version_id,
        user_id=user.id,
        conversation_id=another.id,
        surface="web",
    )
    db.add(second)
    await db.flush()
    assert await service.remembered_consent(
        ctx, second.id, tool_name="send_email", account=None
    ) == (user.id if scope == "agent" else None)
    version = AgentVersion(
        id=uuid.uuid4(), organization_id=org.id, agent_id=run.agent_id, version=2, spec={}
    )
    db.add(version)
    await db.flush()
    second.agent_version_id = version.id
    await db.flush()
    assert (
        await service.remembered_consent(ctx, second.id, tool_name="send_email", account=None)
        is None
    )
    org.chat_may_waive_approvals = False
    assert (
        await service.remembered_consent(ctx, run.id, tool_name="send_email", account=None) is None
    )
    org.chat_may_waive_approvals = True
    with pytest.raises(NotFoundError, match="Remembered approval not found"):
        await service.revoke_consent(
            AuthContext(user_id=uuid.uuid4(), organization_id=org.id, role="owner"), approval.id
        )
    await service.revoke_consent(ctx, approval.id)
    assert approval.status == "approved"
    assert await service.list_consents(ctx) == []
    assert (
        await service.remembered_consent(ctx, run.id, tool_name="send_email", account=None) is None
    )


@pytest.mark.parametrize(
    "changed",
    [
        "surface",
        "user",
        "delegate",
        "version",
        "test",
        "policy",
        "permission",
        "key",
        "fallback",
        "impersonation",
        "reject",
    ],
)
async def test_remembering_approval_refuses_unattended_or_changed_authority(
    db: AsyncSession, changed: str
):
    from dataclasses import replace

    from app.core.audit import set_impersonator
    from app.core.exceptions import AppException

    org, user, run, ctx = await _consent_chat(db)
    approval = await _approval(db, org, run)
    if changed == "surface":
        run.surface = "schedule"
    if changed == "user":
        run.user_id = None
    if changed == "delegate":
        approval.subagent_name = "Architect"
    if changed == "version":
        run.agent_version_id = None
    if changed == "test":
        run.test_spec = {}
    if changed == "policy":
        org.chat_may_waive_approvals = False
    if changed == "permission":
        member = await db.scalar(
            select(OrganizationMember).where(OrganizationMember.organization_id == org.id)
        )
        member.role = "member"
    if changed == "key":
        ctx = replace(ctx, api_key_id=uuid.uuid4())
    if changed == "fallback":
        ctx = replace(ctx, subject_is_publisher_fallback=True)
    if changed == "impersonation":
        set_impersonator(uuid.uuid4())
    await db.flush()
    try:
        with pytest.raises(AppException):
            await ApprovalService(db).decide(
                ctx, approval.id, approved=changed != "reject", remember_scope="conversation"
            )
    finally:
        set_impersonator(None)
    assert approval.status == "pending"
    assert approval.remember_scope is None


@pytest.mark.parametrize("scope", ["principal", "organization", "anonymous"])
async def test_checkpoint_quota_is_atomic_across_workers(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    import json

    org, owner = await _org(db)
    agent = await _agent(db, org)
    other = await _user(db) if scope == "organization" else owner
    first = await _run(db, org, agent, started_by=None if scope == "anonymous" else owner)
    second = await _run(db, org, agent, started_by=None if scope == "anonymous" else other)
    await db.commit()
    monkeypatch.setattr(
        agent_run_repo, "CODE_CHECKPOINT_PRINCIPAL_BYTES", 150 if scope == "principal" else 1000
    )
    monkeypatch.setattr(
        agent_run_repo, "CODE_CHECKPOINT_ORGANIZATION_BYTES", 1000 if scope == "principal" else 150
    )
    payload = {"snapshot": "x" * 80}
    size = len(json.dumps(payload).encode())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def park(run_id: uuid.UUID) -> bool:
        async with factory() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            accepted = await agent_run_repo.code_checkpoint_capacity(
                session, run=run, requested_bytes=size
            )
            if accepted:
                run.paused_state = {"code_checkpoints": payload}
            await session.commit()
            return accepted

    with pytest.MonkeyPatch.context():
        results = await asyncio.wait_for(asyncio.gather(park(first.id), park(second.id)), timeout=5)
    assert sorted(results) == [False, True]
    winner = first if results[0] else second
    loser = second if results[0] else first
    async with factory() as session:
        run = await session.get(AgentRun, winner.id)
        assert run is not None
        # Updating one's own reservation does not count it twice.
        assert await agent_run_repo.code_checkpoint_capacity(session, run=run, requested_bytes=size)
        run.paused_state = None
        await session.commit()
    assert await park(loser.id)


async def test_a_remembered_choice_never_answers_a_tool_that_always_asks(db: AsyncSession):
    """A stored "agent" choice answers a call - unless the row says it always asks."""
    org, user, run, ctx = await _consent_chat(db)
    remembered = await _approval(
        db,
        org,
        run,
        tool_id="share_memory",
        capability_tool_id="share_memory",
        status=ApprovalStatus.APPROVED.value,
        decided_by_user_id=user.id,
        decided_at=datetime.now(UTC),
        remember_scope="agent",
    )
    service = ApprovalService(db)
    assert (
        await service.remembered_consent(ctx, run.id, tool_name="share_memory", account=None)
        == user.id
    )

    remembered.always_asks = True
    await db.flush()

    assert (
        await service.remembered_consent(ctx, run.id, tool_name="share_memory", account=None)
        is None
    )


class TestWhatAQueueReaderMaySeeOfAFact:
    """The fact `share_memory` would share reaches only somebody who may see its run."""

    async def _parked_share(self, db: AsyncSession):
        org, owner = await _org(db)
        asker = await _user(db)
        reader = await _user(db)
        db.add_all(
            [
                OrganizationMember(
                    id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="member"
                )
                for user in (asker, reader)
            ]
        )
        await db.flush()
        run = await _run(db, org, await _agent(db, org), started_by=asker)
        await _approval(
            db,
            org,
            run,
            tool_id="share_memory",
            capability_tool_id="share_memory",
            tool_args={"claim_id": str(uuid.uuid4()), "to": "organization"},
            context={"claim": "The Acme renewal is due in March", "audience": "organization"},
            always_asks=True,
        )
        return org, owner, asker, reader

    async def _read_as(self, db: AsyncSession, org: Organization, user: User, role: str):
        ctx = AuthContext(user_id=user.id, organization_id=org.id, role=role)
        [row], _ = await ApprovalService(db).list_approvals(ctx)
        return row

    async def test_a_member_who_cannot_see_the_run_reads_only_the_audience(self, db) -> None:
        org, _, _, reader = await self._parked_share(db)

        row = await self._read_as(db, org, reader, OrgRoleName.MEMBER)

        assert row.content_hidden
        assert row.context == {"audience": "organization"}

    async def test_the_person_who_asked_reads_the_fact(self, db) -> None:
        org, _, asker, _ = await self._parked_share(db)

        row = await self._read_as(db, org, asker, OrgRoleName.MEMBER)

        assert not row.content_hidden
        assert row.context["claim"] == "The Acme renewal is due in March"

    async def test_an_owner_who_reads_every_run_reads_the_fact(self, db) -> None:
        org, owner, _, _ = await self._parked_share(db)

        row = await self._read_as(db, org, owner, OrgRoleName.OWNER)

        assert not row.content_hidden

    async def _decide_as(self, db: AsyncSession, org, user: User, role: str, *, approved: bool):
        ctx = AuthContext(user_id=user.id, organization_id=org.id, role=role)
        [row], _ = await ApprovalService(db).list_approvals(ctx)
        with patch("app.services.approvals.spawn_after_commit") as spawn:
            spawn.side_effect = lambda _, coroutine, **kwargs: coroutine.close()
            return await ApprovalService(db).decide(ctx, row.id, approved=approved)

    async def test_a_reader_who_cannot_see_the_fact_may_not_approve_sharing_it(self, db) -> None:
        from app.core.exceptions import AuthorizationError

        org, _, _, reader = await self._parked_share(db)

        with pytest.raises(AuthorizationError, match="may approve it; you may reject it"):
            await self._decide_as(db, org, reader, OrgRoleName.MEMBER, approved=True)

    async def test_they_may_still_reject_it(self, db) -> None:
        org, _, _, reader = await self._parked_share(db)

        decided = await self._decide_as(db, org, reader, OrgRoleName.MEMBER, approved=False)

        assert decided.status == ApprovalStatus.REJECTED.value

    async def test_the_person_who_asked_may_approve_it(self, db) -> None:
        org, _, asker, _ = await self._parked_share(db)

        decided = await self._decide_as(db, org, asker, OrgRoleName.MEMBER, approved=True)

        assert decided.status == ApprovalStatus.APPROVED.value

    async def test_the_queue_says_the_call_always_asks(self, db) -> None:
        org, owner, _, _ = await self._parked_share(db)

        assert (await self._read_as(db, org, owner, OrgRoleName.OWNER)).always_asks

    async def test_the_run_s_parked_calls_hide_the_fact_from_the_same_reader(self, db) -> None:
        org, _, asker, reader = await self._parked_share(db)
        [run] = (await db.scalars(select(AgentRun).where(AgentRun.organization_id == org.id))).all()
        runner = AgentRunnerService(db)

        [hidden] = await runner.parked_calls(
            AuthContext(user_id=reader.id, organization_id=org.id, role=OrgRoleName.MEMBER), run
        )
        [shown] = await runner.parked_calls(
            AuthContext(user_id=asker.id, organization_id=org.id, role=OrgRoleName.MEMBER), run
        )

        assert hidden.content_hidden and hidden.context == {"audience": "organization"}
        assert not shown.content_hidden
        assert shown.context is not None and "claim" in shown.context
