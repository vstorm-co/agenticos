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

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories.agent_run import ApprovalFilters
from app.services.approvals import ApprovalService

pytestmark = pytest.mark.anyio

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


class TestWhatTheQueueSays:
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
