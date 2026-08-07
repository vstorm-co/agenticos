"""Tests for expiring a tool call nobody decided.

An approval waits on a person, so nothing in a request path can end one: the
whole point is that no request is coming. That leaves a schedule, and a schedule
is the one caller here with no tenant and no actor - which is what most of these
tests are about. What it writes has to be a denial by timeout on the *run*, in
the row's own organization, saying plainly that nobody decided.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import ApprovalStatus, RunStatus
from app.services.approvals import ApprovalService
from app.worker.tasks.approval_tasks import approval_expiry_sweep_flow

pytestmark = pytest.mark.anyio


def _db() -> MagicMock:
    return MagicMock(flush=AsyncMock(), refresh=AsyncMock(), add=MagicMock())


def _approval(
    *,
    run_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    status: str = ApprovalStatus.PENDING.value,
) -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        run_id=run_id or uuid.uuid4(),
        organization_id=organization_id or uuid.uuid4(),
        status=status,
        tool_id="send_email",
        tool_args={"to": "customer@example.com"},
    )


def _parked_run(status: str = RunStatus.AWAITING_APPROVAL.value) -> MagicMock:
    """A run row as it looks while it waits on a decision."""
    return MagicMock(
        id=uuid.uuid4(),
        status=status,
        input_tokens=1200,
        output_tokens=340,
        cost_usd=Decimal("0.0210"),
        cost_is_partial=False,
    )


class _Sweep:
    """One `expire_stale` run with the repository stubbed around it.

    Every patch target is on the service's own module, so what is exercised is
    the service: which rows it asks for, what it writes on each, and which runs
    it decides to end.
    """

    def __init__(
        self,
        stale: list[MagicMock],
        *,
        run: MagicMock | None = None,
        for_run: list[MagicMock] | None = None,
    ) -> None:
        self.stale = stale
        self.run = run
        self.for_run = for_run if for_run is not None else stale

    async def __aenter__(self) -> _Sweep:
        self._patches = {
            "list_stale_approvals": AsyncMock(return_value=self.stale),
            "decide_approval": AsyncMock(side_effect=self._decide),
            "get_run": AsyncMock(return_value=self.run),
            "list_approvals_for_run": AsyncMock(return_value=self.for_run),
            "finish_run": AsyncMock(),
        }
        self._ctx = patch.multiple("app.services.approvals.agent_run_repo", **self._patches)
        self._ctx.start()
        self._audit = patch("app.services.approvals.record_audit", new=AsyncMock())
        self.audit = self._audit.start()
        self.expired = await ApprovalService(_db()).expire_stale()
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        self._audit.stop()
        self._ctx.stop()
        return False

    @staticmethod
    async def _decide(db, *, approval, status, **kwargs) -> MagicMock:
        """Write the status onto the row, the way the repository would.

        Without this the row stays `pending` in memory and the run would be
        settled by a test that had not actually expired anything.
        """
        approval.status = status
        return approval

    def __getattr__(self, name: str) -> AsyncMock:
        return self._patches[name]


class TestWhichApprovalsAreSweptUp:
    async def test_the_window_moves_with_the_setting(self):
        """ "Configurable age" is the whole of what the operator controls here."""
        with patch.object(settings, "APPROVAL_EXPIRY_HOURS", 5):
            before = datetime.now(UTC)
            async with _Sweep([]) as sweep:
                after = datetime.now(UTC)

            cutoff = sweep.list_stale_approvals.await_args.kwargs["older_than"]
            assert before - timedelta(hours=5) <= cutoff <= after - timedelta(hours=5)

    async def test_a_sweep_that_finds_nothing_writes_nothing(self):
        """The ordinary case, hourly, for ever. It must not touch a row or a run."""
        async with _Sweep([]) as sweep:
            pass

        assert sweep.expired == 0
        sweep.decide_approval.assert_not_awaited()
        sweep.finish_run.assert_not_awaited()
        sweep.audit.assert_not_awaited()


class TestWhatAnExpiryRecords:
    async def test_an_expired_call_names_nobody_as_its_decider(self):
        """Nobody decided - that is the whole fact. Writing the run's owner here
        would record a rejection they never made."""
        approval = _approval()

        async with _Sweep([approval], run=_parked_run()) as sweep:
            pass

        written = sweep.decide_approval.await_args.kwargs
        assert written["status"] == ApprovalStatus.EXPIRED.value
        assert written["decided_by_user_id"] is None
        assert written["decided_at"] is not None

    async def test_every_expiry_reaches_the_audit_trail_in_its_own_organization(self):
        """A schedule crosses tenants to find the rows; what it writes must not."""
        first, second = _approval(), _approval()

        async with _Sweep([first, second], run=_parked_run()) as sweep:
            pass

        entries = {call.kwargs["target_id"]: call.kwargs for call in sweep.audit.await_args_list}
        assert set(entries) == {str(first.id), str(second.id)}
        for approval in (first, second):
            entry = entries[str(approval.id)]
            assert entry["organization_id"] == approval.organization_id
            assert entry["action"] == "approval.expired"
            assert entry["actor_user_id"] is None
            assert entry["details"]["tool_args"] == {"to": "customer@example.com"}


class TestTheRunBehindIt:
    """The point of the sweep. A row flipped to `expired` above a run still
    parked would have moved the problem rather than fixed it."""

    async def test_the_parked_run_is_ended(self):
        approval = _approval()
        run = _parked_run()

        async with _Sweep([approval], run=run) as sweep:
            pass

        ended = sweep.finish_run.await_args.kwargs
        assert ended["run"] is run
        assert ended["status"] == RunStatus.CANCELLED.value
        assert str(settings.APPROVAL_EXPIRY_HOURS) in ended["error"]

    async def test_the_ended_run_cannot_be_resumed(self):
        """`paused_state` is what a resume replays from. Left behind, a run
        expired for want of a decision can still be continued by anyone who
        knows its id."""
        async with _Sweep([_approval()], run=_parked_run()) as sweep:
            pass

        assert sweep.finish_run.await_args.kwargs["paused_state"] is None

    async def test_what_the_run_spent_before_it_parked_stands(self):
        """It reached a gated tool, so the model requests before it were real.
        A settle that zeroed them would take money out of the month."""
        run = _parked_run()

        async with _Sweep([_approval()], run=run) as sweep:
            pass

        ended = sweep.finish_run.await_args.kwargs
        assert (ended["input_tokens"], ended["output_tokens"]) == (1200, 340)
        assert (ended["cost_usd"], ended["cost_is_partial"]) == (Decimal("0.0210"), False)

    async def test_a_run_with_a_second_call_still_inside_the_window_is_left_parked(self):
        """A run parks on all of its outstanding calls at once. Ending it while
        one is still decidable takes the decision away from whoever was going to
        make it."""
        run_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        stale = _approval(run_id=run_id, organization_id=organization_id)
        fresh = _approval(run_id=run_id, organization_id=organization_id)

        async with _Sweep([stale], run=_parked_run(), for_run=[stale, fresh]) as sweep:
            assert sweep.expired == 1

        sweep.finish_run.assert_not_awaited()

    async def test_a_run_that_is_no_longer_parked_is_left_alone(self):
        """It was resumed between the read and the write - the decision that
        settled it was somebody's, and the sweep must not write over it."""
        async with _Sweep(
            [_approval()], run=_parked_run(status=RunStatus.COMPLETED.value)
        ) as sweep:
            pass

        sweep.finish_run.assert_not_awaited()

    async def test_an_approval_whose_run_has_gone_expires_anyway(self):
        """The row outlives nothing here - a deleted run cascades - but a read
        that answers `None` must not stop the sweep partway through a batch."""
        async with _Sweep([_approval()], run=None) as sweep:
            assert sweep.expired == 1

        sweep.finish_run.assert_not_awaited()

    async def test_two_runs_are_each_settled_once(self):
        """Two calls on one run must not end it twice, and two runs must both end."""
        shared = uuid.uuid4()
        organization_id = uuid.uuid4()
        together = [
            _approval(run_id=shared, organization_id=organization_id),
            _approval(run_id=shared, organization_id=organization_id),
        ]
        alone = _approval(organization_id=organization_id)

        async with _Sweep([*together, alone], run=_parked_run()) as sweep:
            assert sweep.expired == 3

        assert sweep.finish_run.await_count == 2


class TestASweptRowIsDecided:
    async def test_a_person_deciding_a_call_the_sweep_expired_is_refused(self):
        """The race is real: a decision arriving a second after the sweep. One
        approval, one outcome - a second decision would make the trail ambiguous
        about what authorised the action."""
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OPERATOR
        )
        expired = _approval(status=ApprovalStatus.EXPIRED.value)

        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=expired),
            ),
            patch(
                "app.services.approvals.agent_run_repo.decide_approval", new=AsyncMock()
            ) as decide,
            pytest.raises(BadRequestError, match="already expired"),
        ):
            await ApprovalService(_db()).decide(ctx, expired.id, approved=True)

        decide.assert_not_awaited()


class TestTheScheduledSweep:
    """The flow around the service. Thin on purpose - what it must not do is
    swallow the count, since that is all a Prefect run reports."""

    async def test_the_flow_answers_with_what_it_expired(self):
        with (
            patch("app.worker.tasks.approval_tasks.get_db_context") as db_context,
            patch(
                "app.worker.tasks.approval_tasks.ApprovalService",
                return_value=MagicMock(expire_stale=AsyncMock(return_value=3)),
            ),
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=_db())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)

            assert await approval_expiry_sweep_flow() == 3
