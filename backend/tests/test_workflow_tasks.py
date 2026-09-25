"""`app.worker.tasks.workflow_tasks`: the direct trigger and the poll/reconcile fan-out.

`workflow_dispatch_node_flow` itself is exercised end to end against a real
Postgres by `tests/integration/test_workflow_run_commit_boundary.py`, calling
`dispatcher.claim`/`begin_attempt`/`settle` directly rather than through this
flow wrapper - matching every other test of this module, none of which call
a `@flow`-decorated function here directly. What is worth unit-testing in
isolation is the *submission* mechanics this module owns: `trigger_dispatch`'s
defer-until-commit, `_submit_dispatch`'s `run_deployment` call, and that the
poll/reconcile sweeps submit each row through `_submit_dispatch` rather than
awaiting the whole dispatch flow inline - the fix for #1788's round 2 finding
that a hung handler in one row could block every later row in the same batch.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow_execution.context import ClaimState
from app.worker.tasks import workflow_tasks

pytestmark = pytest.mark.anyio

TASKS_PATH = "app.worker.tasks.workflow_tasks"


class TestTriggerDispatch:
    async def test_queues_a_submission_for_after_the_session_commits(self):
        db = MagicMock()
        workflow_run_id, node_run_id = uuid.uuid4(), uuid.uuid4()

        with patch("app.core.background.spawn_after_commit") as spawn_after_commit:
            workflow_tasks.trigger_dispatch(
                db, workflow_run_id=workflow_run_id, node_run_id=node_run_id
            )

        spawn_after_commit.assert_called_once()
        assert spawn_after_commit.call_args.args[0] is db
        assert spawn_after_commit.call_args.kwargs["name"] == "workflow-dispatch-node"
        # The deferred coroutine is `_submit_dispatch`'s own, never awaited by
        # this test - close it rather than leave it to warn at GC time.
        spawn_after_commit.call_args.args[1].close()


class TestSubmitDispatch:
    async def test_submits_to_the_registered_deployment_without_waiting_for_it(self):
        with patch(f"{TASKS_PATH}.run_deployment", new=AsyncMock()) as run_deployment:
            await workflow_tasks._submit_dispatch(workflow_run_id="r-1", node_run_id="n-1")

        run_deployment.assert_awaited_once_with(
            name="workflow-dispatch-node/workflow-dispatch-node",
            parameters={"workflow_run_id": "r-1", "node_run_id": "n-1"},
            timeout=0,
        )


class _AsyncDBContext:
    """A stand-in for `get_worker_db_context()` that hands back a plain mock session."""

    def __init__(self, db: object) -> None:
        self._db = db

    async def __aenter__(self) -> object:
        return self._db

    async def __aexit__(self, *_exc_info: object) -> None:
        return None


class TestPollFlowFanOut:
    async def test_submits_each_pending_row_independently_not_the_flow_inline(self):
        """Each row goes through `_submit_dispatch` (a `run_deployment` submit,

        not the flow function called directly) - one hung handler in an
        earlier row must not hold up claiming a later one in the same batch.
        """
        row_a = MagicMock(workflow_run_id=uuid.uuid4(), node_run_id=uuid.uuid4())
        row_b = MagicMock(workflow_run_id=uuid.uuid4(), node_run_id=uuid.uuid4())

        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.repositories.workflow_run.take_due_for_submission",
                new=AsyncMock(return_value=[row_a, row_b]),
            ),
            patch(f"{TASKS_PATH}._submit_dispatch", new=AsyncMock()) as submit,
        ):
            count = await workflow_tasks.workflow_dispatch_poll_flow()

        assert count == 2
        assert submit.await_count == 2
        submit.assert_any_await(
            workflow_run_id=str(row_a.workflow_run_id), node_run_id=str(row_a.node_run_id)
        )
        submit.assert_any_await(
            workflow_run_id=str(row_b.workflow_run_id), node_run_id=str(row_b.node_run_id)
        )


class TestReconcileFlowFanOut:
    async def test_submits_each_stale_claim_independently_not_the_flow_inline(self):
        pair = (uuid.uuid4(), uuid.uuid4())

        reconciler = MagicMock()
        reconciler.stale_claims = AsyncMock(return_value=[pair])
        reconciler.resolve_orphaned_attempts = AsyncMock(return_value=0)
        reconciler.wake_stale_approval_decisions = AsyncMock(return_value=0)

        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.reconciler.WorkflowReconcilerService",
                return_value=reconciler,
            ),
            patch(f"{TASKS_PATH}._submit_dispatch", new=AsyncMock()) as submit,
        ):
            result = await workflow_tasks.workflow_reconcile_flow()

        assert result["reclaimed_claims"] == 1
        submit.assert_awaited_once_with(workflow_run_id=str(pair[0]), node_run_id=str(pair[1]))


class TestSubmissionIsolation:
    async def test_one_failed_poll_submission_does_not_cost_the_rest_of_the_batch(self):
        rows = [MagicMock(workflow_run_id=uuid.uuid4(), node_run_id=uuid.uuid4()) for _ in range(3)]

        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.repositories.workflow_run.take_due_for_submission",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                f"{TASKS_PATH}._submit_dispatch",
                new=AsyncMock(side_effect=[RuntimeError("prefect down"), None, None]),
            ) as submit,
        ):
            submitted = await workflow_tasks.workflow_dispatch_poll_flow()

        assert submit.await_count == 3
        assert submitted == 2

    async def test_a_failed_reconcile_submission_still_reports_the_sweeps(self):
        reconciler = MagicMock()
        reconciler.stale_claims = AsyncMock(return_value=[(uuid.uuid4(), uuid.uuid4())] * 2)
        reconciler.resolve_orphaned_attempts = AsyncMock(return_value=1)
        reconciler.wake_stale_approval_decisions = AsyncMock(return_value=0)

        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.reconciler.WorkflowReconcilerService",
                return_value=reconciler,
            ),
            patch(
                f"{TASKS_PATH}._submit_dispatch",
                new=AsyncMock(side_effect=[RuntimeError("prefect down"), None]),
            ),
        ):
            result = await workflow_tasks.workflow_reconcile_flow()

        assert result == {"reclaimed_claims": 1, "resolved_attempts": 1, "woken_approvals": 0}


class TestLeaseRenewal:
    @pytest.fixture(autouse=True)
    def _fast_ticks(self, monkeypatch):
        monkeypatch.setattr(workflow_tasks.settings, "WORKFLOW_DISPATCH_LEASE_SECONDS", 0.03)

    async def test_a_lost_claim_stops_renewing_and_tells_the_handler(self):
        claim = ClaimState()
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.dispatcher.renew_lease",
                new=AsyncMock(side_effect=[True, False]),
            ) as renew,
        ):
            await workflow_tasks._renew_until_lost(uuid.uuid4(), uuid.uuid4(), claim)

        assert renew.await_count == 2
        assert claim.lost is True

    async def test_a_failed_renewal_is_retried_rather_than_giving_the_claim_up(self):
        claim = ClaimState()
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.dispatcher.renew_lease",
                new=AsyncMock(side_effect=[RuntimeError("db blip"), False]),
            ) as renew,
        ):
            await workflow_tasks._renew_until_lost(uuid.uuid4(), uuid.uuid4(), claim)

        assert renew.await_count == 2
        assert claim.lost is True

    async def test_renewal_stops_when_the_block_ends(self):
        claim = ClaimState()
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.dispatcher.renew_lease",
                new=AsyncMock(return_value=True),
            ) as renew,
        ):
            async with workflow_tasks._lease_kept_alive(uuid.uuid4(), uuid.uuid4(), claim):
                await asyncio.sleep(0.05)
            renewals = renew.await_count
            await asyncio.sleep(0.05)

        assert renewals >= 1
        assert renew.await_count == renewals
        assert claim.lost is False
