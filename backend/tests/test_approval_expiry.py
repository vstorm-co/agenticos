"""Tests for expiring a tool call nobody decided.

An approval waits on a person, so nothing in a request path can end one: the
whole point is that no request is coming. That leaves a schedule, and a schedule
is the one caller here with no tenant and no actor - which is what most of these
tests are about. What it writes has to be a denial by timeout on the *run*, in
the row's own organization, saying plainly that nobody decided.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai_harness.ask_user import TIMED_OUT

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import CHANNEL_SURFACES, ApprovalStatus, RunStatus
from app.db.models.secret_request import SecretRequestStatus
from app.services.approvals import ApprovalService
from app.services.channels.handback import EXPIRED_NOTICE, STRANDED_NOTICE
from app.worker.tasks.approval_tasks import expire_approvals

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture(autouse=True)
def _outcome_projection():
    # This file isolates expiry/run state; real case settlement is covered against Postgres.
    with patch(
        "app.services.approvals.OutcomeService.resolve_run_approvals", new=AsyncMock(return_value=0)
    ) as project:
        yield project


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
        decided_at=None
        if status == ApprovalStatus.PENDING.value
        else datetime.now(UTC) - timedelta(hours=2),
        tool_id="send_email",
        tool_args={"to": "customer@example.com"},
    )


def _parked_run(
    status: str = RunStatus.AWAITING_APPROVAL.value,
    *,
    paused_state: dict | None = None,
) -> MagicMock:
    """A run row as it looks while it waits on a decision."""
    return MagicMock(
        id=uuid.uuid4(),
        status=status,
        paused_state=(
            {"messages": [], "tool_call_ids": {str(uuid.uuid4()): "call-1"}}
            if paused_state is None
            else paused_state
        ),
        input_tokens=1200,
        output_tokens=340,
        cost_usd=Decimal("0.0210"),
        cost_is_partial=False,
    )


async def _erase(_db: object, *, run: MagicMock, **_kwargs: object) -> None:
    """What `finish_run` does to a run's parked state, so a late read finds nothing."""
    run.paused_state = None


async def _nothing() -> None:
    """Stands in for a notice coroutine, so a spawn has something to close."""


def _spawned_names(spawned: MagicMock) -> list[str]:
    return [call.kwargs["name"] for call in spawned.call_args_list]


def _chat_run(**overrides: object) -> MagicMock:
    """A parked run that came from a Slack channel and remembers which one."""
    state = {
        "messages": [],
        "tool_call_ids": {str(uuid.uuid4()): "call-1"},
        "questions": ["ask-1"],
        "channel_destination": {
            "bot_id": str(uuid.uuid4()),
            "platform_chat_id": "C1",
            "private_chat": False,
        },
    }
    run = _parked_run(paused_state=state)
    run.surface = "slack"
    run.chat_notice_sent_at = None
    for name, value in overrides.items():
        setattr(run, name, value)
    return run


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
        workflow_node_waiting: bool = False,
        runs: list[MagicMock] | None = None,
    ) -> None:
        self.runs = runs
        self.stale = stale
        self.run = run
        self.for_run = for_run if for_run is not None else stale
        self.workflow_node_waiting = workflow_node_waiting

    async def __aenter__(self) -> _Sweep:
        self._patches = {
            "list_stale_approvals": AsyncMock(return_value=self.stale),
            "claim_parked_run": AsyncMock(),
            "get_approval": AsyncMock(
                side_effect=lambda _db, approval_id, **kwargs: next(
                    (a for a in self.stale if a.id == approval_id), None
                )
            ),
            "decide_approval": AsyncMock(side_effect=self._decide),
            "get_run": AsyncMock(
                return_value=self.run, side_effect=iter(self.runs) if self.runs else None
            ),
            "list_approvals_for_run": AsyncMock(return_value=self.for_run),
            "finish_run": AsyncMock(side_effect=_erase),
        }
        self._ctx = patch.multiple("app.services.approvals.agent_run_repo", **self._patches)
        self._ctx.start()
        self._audit = patch("app.services.approvals.record_audit", new=AsyncMock())
        self.audit = self._audit.start()
        self._waiting = patch(
            "app.services.approvals.workflow_run_repo.find_node_run_waiting_on_agent_run",
            new=AsyncMock(return_value=MagicMock() if self.workflow_node_waiting else None),
        )
        self._waiting.start()
        self._spawn = patch("app.services.approvals.spawn_after_commit")
        self.spawned = self._spawn.start()
        self._settle = patch(
            "app.services.approvals.channel_prompt_repo.settle_open", new=AsyncMock()
        )
        self.settle = self._settle.start()
        self._post = patch(
            "app.services.approvals.queue_notices",
            new=AsyncMock(),
        )
        self.post = self._post.start()
        # The transcript write is the service's own, so it is stubbed at the same
        # boundary as the repository rather than left to fail into `record`'s
        # own exception handler - which is what "passing" would have meant.
        self._transcript = patch("app.services.approvals.TranscriptService")
        self.record = self._transcript.start().return_value.record = AsyncMock()
        self.expired = await ApprovalService(_db()).expire_stale()
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        for call in self.spawned.call_args_list:
            call.args[1].close()
        self._post.stop()
        self._settle.stop()
        self._spawn.stop()
        self._waiting.stop()
        self._transcript.stop()
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

    async def test_an_expired_chat_run_tells_its_chat_after_commit(self):
        run = _chat_run()

        async with _Sweep([_approval()], run=run) as sweep:
            pass

        sweep.post.assert_awaited_once()
        sweep.settle.assert_awaited_once_with(
            sweep.settle.await_args.args[0], run_id=run.id, by="expired"
        )
        (notice,) = sweep.post.call_args.args[1]
        assert notice.text == EXPIRED_NOTICE
        assert notice.run_id == run.id
        assert notice.organization_id == run.organization_id
        assert notice.destination.platform_chat_id == "C1"

    async def test_an_expired_run_outside_a_chat_posts_nothing(self):
        async with _Sweep([_approval()], run=_parked_run()) as sweep:
            pass

        assert not [n for n in _spawned_names(sweep.spawned) if n == "channel-expiry-notices"]
        sweep.settle.assert_not_awaited()

    async def test_a_workflow_node_waiting_on_the_ended_run_is_woken(self):
        """The node must see the run ended and fail, not wait on it for ever."""
        async with _Sweep([_approval()], run=_parked_run(), workflow_node_waiting=True) as sweep:
            pass

        sweep.spawned.assert_called_once()
        assert sweep.spawned.call_args.kwargs["name"] == "workflow-approval-wake"

    async def test_an_ended_run_no_workflow_waits_on_spawns_nothing(self):
        """A backlog sweep ends hundreds of runs; a wake - and the connection it
        opens - is only for those a workflow node is parked on."""
        async with _Sweep([_approval()], run=_parked_run()) as sweep:
            pass

        sweep.spawned.assert_not_called()

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

    async def test_the_step_it_parked_on_stops_looking_like_it_is_running(self):
        """Every other ending runs the call and records what came back. An expiry
        runs nothing, so the step written when the run parked stayed *open* - and
        a reader coming back to the conversation saw a command apparently still
        executing days after the run was cancelled.

        Written before `finish_run`, which clears the state the ids come from."""
        async with _Sweep([_approval()], run=_parked_run()) as sweep:
            pass

        written = sweep.record.await_args.kwargs
        assert list(written["settled"]) == ["call-1"]
        assert str(settings.APPROVAL_EXPIRY_HOURS) in written["settled"]["call-1"]
        # No turn is invented for it: nothing was said and nothing was called.
        assert (written["prompt"], written["answer"]) == (None, "")

    async def test_a_run_parked_before_the_step_map_existed_settles_nothing(self):
        """The map from approval to tool call is the only link there is. Without
        it the step cannot be closed - which is a step left open, not one to
        guess at."""
        async with _Sweep([_approval()], run=_parked_run(paused_state={"messages": []})) as sweep:
            pass

        assert sweep.record.await_args.kwargs["settled"] == {}

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
    swallow the count, since that is all a sweep reports."""

    @staticmethod
    def _service(unanswered: int = 0) -> MagicMock:
        return MagicMock(
            expire_stale=AsyncMock(return_value=3),
            nudge_unanswered=AsyncMock(return_value=0),
            expire_unanswered=AsyncMock(return_value=unanswered),
            end_stranded=AsyncMock(return_value=0),
        )

    @staticmethod
    def _context(db_context: MagicMock) -> None:
        db_context.return_value.__aenter__ = AsyncMock(return_value=_db())
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)

    @pytest.mark.parametrize("unanswered", [0, 2])
    async def test_the_flow_answers_with_what_it_expired(self, unanswered: int):
        service = self._service(unanswered)
        with (
            patch("app.worker.tasks.approval_tasks.get_db_context") as db_context,
            patch("app.worker.tasks.approval_tasks.ApprovalService", return_value=service),
            patch("app.worker.tasks.approval_tasks.ensure_channel_adapters"),
        ):
            self._context(db_context)

            assert await expire_approvals() == 3

        # The unanswered questions are swept in the same pass (#2064), reminded
        # once halfway to expiry first, and the four sweeps each get a
        # transaction of their own.
        service.nudge_unanswered.assert_awaited_once()
        service.expire_unanswered.assert_awaited_once()
        service.end_stranded.assert_awaited_once()
        assert db_context.call_count == 4

    async def test_the_worker_registers_its_chat_adapters_before_sweeping(self):
        service = self._service()
        calls: list[str] = []
        service.expire_stale.side_effect = lambda: calls.append("sweep") or 0
        with (
            patch("app.worker.tasks.approval_tasks.get_db_context") as db_context,
            patch("app.worker.tasks.approval_tasks.ApprovalService", return_value=service),
            patch(
                "app.worker.tasks.approval_tasks.ensure_channel_adapters",
                side_effect=lambda: calls.append("adapters"),
            ),
        ):
            self._context(db_context)
            await expire_approvals()

        assert calls == ["adapters", "sweep"]

    async def test_a_failed_adapter_bootstrap_still_runs_the_sweeps(self, caplog):
        service = self._service()
        with (
            patch("app.worker.tasks.approval_tasks.get_db_context") as db_context,
            patch("app.worker.tasks.approval_tasks.ApprovalService", return_value=service),
            patch(
                "app.worker.tasks.approval_tasks.ensure_channel_adapters",
                side_effect=RuntimeError("no adapter"),
            ),
            caplog.at_level("WARNING"),
        ):
            self._context(db_context)
            assert await expire_approvals() == 3

        service.expire_stale.assert_awaited_once()
        service.expire_unanswered.assert_awaited_once()
        service.end_stranded.assert_awaited_once()
        assert "chat adapters" in caplog.text

    async def test_a_stranded_run_is_worth_a_warning(self, caplog):
        service = self._service()
        service.end_stranded.return_value = 2
        with (
            patch("app.worker.tasks.approval_tasks.get_db_context") as db_context,
            patch("app.worker.tasks.approval_tasks.ApprovalService", return_value=service),
            patch("app.worker.tasks.approval_tasks.ensure_channel_adapters"),
            caplog.at_level("WARNING"),
        ):
            self._context(db_context)
            await expire_approvals()

        assert "2 run(s) ended" in caplog.text


class TestUnansweredQuestions:
    """The question sweep claims a run before it ends it, as a press does."""

    @staticmethod
    def _patches(runs: list[MagicMock], order: list[str]) -> dict[str, MagicMock]:
        by_id = {run.id: run for run in runs}

        async def claim(_db, run_id, **_kwargs):
            order.append(f"claim:{run_id}")
            return by_id[run_id]

        async def finish(_db, *, run, **_kwargs):
            order.append(f"finish:{run.id}")
            run.paused_state = None

        return {
            "list": patch(
                "app.services.approvals.agent_run_repo.list_unanswered_runs",
                new=AsyncMock(return_value=runs),
            ),
            "claim": patch(
                "app.services.approvals.agent_run_repo.claim_parked_run", side_effect=claim
            ),
            "finish": patch("app.services.approvals.agent_run_repo.finish_run", side_effect=finish),
            "transcript": patch("app.services.approvals.TranscriptService"),
            "settle": patch(
                "app.services.approvals.channel_prompt_repo.settle_open", new=AsyncMock()
            ),
            "spawn": patch("app.services.approvals.spawn_after_commit"),
            "post": patch(
                "app.services.approvals.queue_notices",
                new=AsyncMock(),
            ),
        }

    async def _sweep(self, runs: list[MagicMock]) -> tuple[int, dict[str, MagicMock], list[str]]:
        order: list[str] = []
        patches = self._patches(runs, order)
        started = {name: p.start() for name, p in patches.items()}
        try:
            started["transcript"].return_value.record = AsyncMock(
                side_effect=lambda *_a, **_k: order.append("transcript")
            )
            ended = await ApprovalService(_db()).expire_unanswered()
            for call in started["spawn"].call_args_list:
                call.args[1].close()
        finally:
            for p in patches.values():
                p.stop()
        return ended, started, order

    async def test_the_question_sweep_claims_each_run_before_ending_it(self):
        runs = sorted(
            (_chat_run(status=RunStatus.AWAITING_ANSWER.value) for _ in range(2)),
            key=lambda run: run.id,
        )
        ended, _, order = await self._sweep(list(reversed(runs)))

        assert ended == 2
        claims = [entry for entry in order if entry.startswith("claim")]
        assert claims == [f"claim:{run.id}" for run in runs]
        first_finish = min(i for i, entry in enumerate(order) if entry.startswith("finish"))
        assert order.index(claims[-1]) < first_finish

    async def test_a_run_a_press_continued_meanwhile_is_left_alone(self):
        run = _chat_run(status=RunStatus.AWAITING_ANSWER.value)

        async def claim(_db, run_id, **_kwargs):
            run.status = RunStatus.RUNNING.value
            return run

        patches = self._patches([run], [])
        started = {name: p.start() for name, p in patches.items()}
        started["claim"].side_effect = claim
        try:
            ended = await ApprovalService(_db()).expire_unanswered()
        finally:
            for p in patches.values():
                p.stop()

        assert ended == 0
        started["finish"].assert_not_called()
        started["spawn"].assert_not_called()
        started["settle"].assert_not_awaited()

    async def test_an_expired_question_in_a_chat_tells_the_chat(self):
        run = _chat_run(status=RunStatus.AWAITING_ANSWER.value)
        ended, started, _ = await self._sweep([run])

        assert ended == 1
        started["settle"].assert_awaited_once()
        assert started["settle"].await_args.kwargs == {"run_id": run.id, "by": "expired"}
        (notice,) = started["post"].call_args.args[1]
        assert notice.text == EXPIRED_NOTICE
        started["post"].assert_awaited_once()

    async def test_an_expired_question_outside_a_chat_posts_nothing(self):
        run = _parked_run(status=RunStatus.AWAITING_ANSWER.value)
        run.surface = "web"
        ended, started, _ = await self._sweep([run])

        assert ended == 1
        started["spawn"].assert_not_called()
        started["settle"].assert_not_awaited()

    async def test_an_accepted_answer_is_not_expired_while_its_workflow_is_queued(self) -> None:
        run = _parked_run(status=RunStatus.AWAITING_ANSWER.value)
        run.surface = "workflow"
        run.paused_state["question_results"] = {"ask-1": {"Answer": ["yes"]}}

        ended, started, _ = await self._sweep([run])

        assert ended == 0
        started["finish"].assert_not_called()
        started["spawn"].assert_not_called()

    async def test_a_workflow_is_woken_after_its_question_expires(self) -> None:
        run = _parked_run(status=RunStatus.AWAITING_ANSWER.value)
        run.surface = "workflow"

        ended, started, _ = await self._sweep([run])

        assert ended == 1
        assert _spawned_names(started["spawn"]) == ["workflow-question-expiry-wake"]

    async def test_expiring_a_secret_wait_settles_only_pending_requests_and_keeps_spend(
        self,
    ) -> None:
        run = _chat_run(status=RunStatus.AWAITING_ANSWER.value)
        run.paused_state["questions"] = []
        run.paused_state["secret_requests"] = ["secret-1"]
        pending = MagicMock(status=SecretRequestStatus.PENDING)
        fulfilled = MagicMock(status=SecretRequestStatus.FULFILLED)
        with (
            patch(
                "app.services.approvals.secret_request_repo.list_for_run",
                new=AsyncMock(return_value=[pending, fulfilled]),
            ) as listed,
            patch(
                "app.services.approvals.secret_request_repo.mark_expired", new=AsyncMock()
            ) as expired,
        ):
            ended, started, _ = await self._sweep([run])
        assert ended == 1 and run.paused_state is None
        assert listed.await_args is not None
        assert listed.await_args.kwargs == {
            "run_id": run.id,
            "organization_id": run.organization_id,
        }
        assert expired.await_args is not None
        assert expired.await_count == 1
        assert expired.await_args.kwargs["request"] is pending
        assert fulfilled.status == SecretRequestStatus.FULFILLED
        transcript = started["transcript"].return_value.record
        assert transcript.await_args is not None
        assert transcript.await_args.kwargs["settled"] == {"secret-1": TIMED_OUT}
        finish = started["finish"].call_args
        assert finish is not None
        assert finish.kwargs["status"] == RunStatus.CANCELLED.value
        assert finish.kwargs["cost_usd"] == run.cost_usd
        assert finish.kwargs["input_tokens"] == run.input_tokens
        assert finish.kwargs["output_tokens"] == run.output_tokens
        assert finish.kwargs["error"].endswith("the secret request expired")


class TestStrandedRuns:
    async def test_the_safety_net_audits_after_every_row_lock(self):
        runs = sorted((_chat_run(), _chat_run()), key=lambda run: run.id)
        by_id = {run.id: run for run in runs}
        order: list[str] = []

        async def claim(_db, run_id, **_kwargs):
            order.append("claim")
            return by_id[run_id]

        async def settle(*_a, **_k):
            order.append("settle")

        async def finish(_db, *, run, **_k):
            order.append("finish")
            run.paused_state = None

        async def record(*_a, **_k):
            order.append("record")

        decided = datetime.now(UTC) - timedelta(hours=2)
        with (
            patch(
                "app.services.approvals.agent_run_repo.list_stranded_runs",
                new=AsyncMock(return_value=[(run, decided) for run in reversed(runs)]),
            ),
            patch("app.services.approvals.agent_run_repo.claim_parked_run", side_effect=claim),
            patch(
                "app.services.approvals.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[_approval(status=ApprovalStatus.APPROVED.value)]),
            ),
            patch("app.services.approvals.channel_prompt_repo.settle_open", side_effect=settle),
            patch("app.services.approvals.agent_run_repo.finish_run", side_effect=finish),
            patch("app.services.approvals.TranscriptService") as transcript,
            patch("app.services.approvals.record_audit", side_effect=record) as audit,
            patch("app.services.approvals.spawn_after_commit") as spawn,
            patch(
                "app.services.approvals.queue_notices",
                new=AsyncMock(),
            ) as post,
        ):
            transcript.return_value.record = AsyncMock()
            ended = await ApprovalService(_db()).end_stranded()

        assert ended == 2
        # The mixed park's approval step and its question step are both closed.
        for call in transcript.return_value.record.await_args_list:
            assert set(call.kwargs["settled"]) == {"call-1", "ask-1"}
        # Every claim, and every row write, before the first audit.
        assert order[:2] == ["claim", "claim"]
        assert order.index("record") > max(i for i, e in enumerate(order) if e == "finish")
        assert order.count("record") == 2
        assert audit.call_args.kwargs["details"] == {
            "previous_status": "awaiting_approval",
            "by": "stranded",
        }
        assert audit.call_args.kwargs["actor_user_id"] is None
        # One task for the whole sweep, posting both notices in turn.
        spawn.assert_not_called()
        post.assert_awaited_once()
        notices = post.call_args.args[1]
        assert [n.run_id for n in notices] == [run.id for run in runs]
        assert {n.text for n in notices} == {STRANDED_NOTICE}

    async def test_a_sweep_with_many_runs_spawns_one_task_for_their_notices(self):
        async with _Sweep(
            [_approval(), _approval(), _approval()], runs=[_chat_run() for _ in range(3)]
        ) as sweep:
            pass

        sweep.post.assert_awaited_once()
        assert len(sweep.post.call_args.args[1]) == 3

    async def test_a_run_that_is_no_longer_stranded_when_claimed_is_left_alone(self):
        run = _chat_run()
        decided = datetime.now(UTC) - timedelta(hours=2)
        for status, approvals in (
            (RunStatus.RUNNING.value, [_approval(status=ApprovalStatus.APPROVED.value)]),
            (RunStatus.AWAITING_APPROVAL.value, [_approval()]),
        ):
            run.status = status
            with (
                patch(
                    "app.services.approvals.agent_run_repo.list_stranded_runs",
                    new=AsyncMock(return_value=[(run, decided)]),
                ),
                patch(
                    "app.services.approvals.agent_run_repo.claim_parked_run",
                    new=AsyncMock(return_value=run),
                ),
                patch(
                    "app.services.approvals.agent_run_repo.list_approvals_for_run",
                    new=AsyncMock(return_value=approvals),
                ),
                patch("app.services.approvals.agent_run_repo.finish_run") as finish,
                patch("app.services.approvals.record_audit") as audit,
            ):
                assert await ApprovalService(_db()).end_stranded() == 0
            finish.assert_not_called()
            audit.assert_not_called()

    async def test_a_claim_that_finds_no_run_is_skipped(self):
        decided = datetime.now(UTC) - timedelta(hours=2)
        with (
            patch(
                "app.services.approvals.agent_run_repo.list_stranded_runs",
                new=AsyncMock(return_value=[(_chat_run(), decided)]),
            ),
            patch(
                "app.services.approvals.agent_run_repo.claim_parked_run",
                new=AsyncMock(return_value=None),
            ),
        ):
            assert await ApprovalService(_db()).end_stranded() == 0

    async def test_nothing_stranded_writes_nothing(self):
        with patch(
            "app.services.approvals.agent_run_repo.list_stranded_runs",
            new=AsyncMock(return_value=[]),
        ) as listed:
            assert await ApprovalService(_db()).end_stranded() == 0
        assert set(listed.await_args.kwargs["surfaces"]) == {
            surface.value for surface in CHANNEL_SURFACES
        }


class TestALiveCallsApproval:
    """A call's approval is decided by the person on the call, nowhere else (#54)."""

    async def test_the_queue_refuses_an_approval_a_live_call_is_waiting_on(self):
        approval = _approval()
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=approval.organization_id, role=OrgRoleName.OWNER
        )
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            patch(
                "app.services.approvals.voice_call_repo.is_live_run",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.approvals.agent_run_repo.decide_approval", new=AsyncMock()
            ) as decided,
            pytest.raises(BadRequestError, match="decided in the call"),
        ):
            await ApprovalService(_db()).decide(ctx, approval.id, approved=True)

        decided.assert_not_awaited()

    async def test_the_call_itself_may_decide_it(self):
        approval = _approval()
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=approval.organization_id, role=OrgRoleName.OWNER
        )
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            patch(
                "app.services.approvals.voice_call_repo.is_live_run",
                new=AsyncMock(return_value=True),
            ) as live,
            patch(
                "app.services.approvals.agent_run_repo.decide_approval", new=AsyncMock()
            ) as decided,
            patch.object(ApprovalService, "_record_decision", new=AsyncMock()),
            patch.object(ApprovalService, "_settle_outcomes", new=AsyncMock()) as settled,
        ):
            await ApprovalService(_db()).decide(ctx, approval.id, approved=True, via_call=True)

        live.assert_not_awaited()
        settled.assert_awaited_once()
        assert decided.await_args.kwargs["status"] == ApprovalStatus.APPROVED.value

    async def test_an_approval_nobody_decided_in_the_call_expires_with_nobody_named(self):
        approval = _approval()
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            patch(
                "app.services.approvals.agent_run_repo.decide_approval", new=AsyncMock()
            ) as decided,
            patch.object(ApprovalService, "_record_decision", new=AsyncMock()) as audited,
            patch.object(ApprovalService, "_settle_outcomes", new=AsyncMock()) as settled,
        ):
            await ApprovalService(_db()).expire_now(
                approval.id, organization_id=approval.organization_id, note="n"
            )

        kwargs = decided.await_args.kwargs
        assert (kwargs["status"], kwargs["decided_by_user_id"], kwargs["note"]) == (
            ApprovalStatus.EXPIRED.value,
            None,
            "n",
        )
        assert audited.await_args.kwargs["actor_user_id"] is None
        settled.assert_awaited_once()

    @pytest.mark.parametrize("found", ["missing", "decided"])
    async def test_expiring_leaves_a_decided_or_missing_row_alone(self, found):
        approval = None if found == "missing" else _approval(status=ApprovalStatus.APPROVED.value)
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            patch(
                "app.services.approvals.agent_run_repo.decide_approval", new=AsyncMock()
            ) as decided,
        ):
            await ApprovalService(_db()).expire_now(uuid.uuid4(), organization_id=uuid.uuid4())

        decided.assert_not_awaited()


@pytest.mark.parametrize("found", [False, True])
async def test_the_sweep_locks_runs_first_and_rechecks_approvals_before_expiring(
    found: bool,
) -> None:
    stale = [_approval(run_id=uuid.UUID(int=2)), _approval(run_id=uuid.UUID(int=1))]
    events = []

    async def claim(_db, run_id, **kwargs):
        events.append(("run", run_id))

    async def current(_db, approval_id, **kwargs):
        events.append(("approval", approval_id))
        assert kwargs["for_update"] is True
        return _approval(status=ApprovalStatus.APPROVED.value) if found else None

    with (
        patch(
            "app.services.approvals.agent_run_repo.list_stale_approvals",
            AsyncMock(return_value=stale),
        ),
        patch(
            "app.services.approvals.agent_run_repo.claim_parked_run", AsyncMock(side_effect=claim)
        ),
        patch("app.services.approvals.agent_run_repo.get_approval", AsyncMock(side_effect=current)),
        patch("app.services.approvals.agent_run_repo.decide_approval", AsyncMock()) as decide,
    ):
        assert await ApprovalService(_db()).expire_stale() == 0
    assert events[:2] == [("run", uuid.UUID(int=1)), ("run", uuid.UUID(int=2))]
    assert all(kind == "approval" for kind, _ in events[2:])
    decide.assert_not_awaited()


@pytest.mark.parametrize("recent_decision", [True, False])
async def test_a_sweep_never_uses_a_stale_decision_time_from_its_listing(recent_decision: bool):
    run = _chat_run()
    approval = _approval(status=ApprovalStatus.APPROVED.value)
    approval.decided_at = datetime.now(UTC) if recent_decision else None
    with (
        patch(
            "app.services.approvals.agent_run_repo.list_stranded_runs",
            new=AsyncMock(return_value=[(run, datetime.now(UTC) - timedelta(hours=2))]),
        ),
        patch(
            "app.services.approvals.agent_run_repo.claim_parked_run",
            new=AsyncMock(return_value=run),
        ),
        patch(
            "app.services.approvals.agent_run_repo.list_approvals_for_run",
            new=AsyncMock(return_value=[approval]),
        ),
        patch("app.services.approvals.agent_run_repo.finish_run", new=AsyncMock()) as finish,
        patch("app.services.approvals.channel_prompt_repo.settle_open", new=AsyncMock()),
        patch("app.services.approvals.TranscriptService") as transcript,
        patch("app.services.approvals.record_audit", new=AsyncMock()),
        patch(
            "app.services.approvals.queue_notices",
            new=AsyncMock(),
        ),
        patch("app.services.approvals.spawn_after_commit") as spawn,
    ):
        transcript.return_value.record = AsyncMock()
        ended = await ApprovalService(_db()).end_stranded()
        for call in spawn.call_args_list:
            call.args[1].close()
    assert ended == 0
    finish.assert_not_awaited()
