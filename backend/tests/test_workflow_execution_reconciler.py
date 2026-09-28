"""`app.services.workflow_execution.reconciler.WorkflowReconcilerService`.

Structurally `app.services.run_reaper`'s own test shape: the repository is
mocked at the database edge, and each method's job is proven by what it
finds and what it does about it - never by asserting a mock was called for
its own sake.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    RetryGuarantee,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo_module
from app.services.workflow_execution.reconciler import WorkflowReconcilerService

pytestmark = pytest.mark.anyio

RECONCILER_PATH = "app.services.workflow_execution.reconciler"


@pytest.fixture
def repo():
    """Patches `workflow_run_repo` in both `reconciler` and `dispatcher`'s own
    namespaces - `resolve_orphaned_attempts` calls into
    `dispatcher.resolve_orphaned_attempt`, which reads its own separate
    import binding of the repository, not reconciler's."""
    mocked = create_autospec(workflow_run_repo_module, instance=False)
    # This attempt is the node's first failure unless a test says otherwise.
    mocked.count_failed_attempts.return_value = 1
    with (
        patch(f"{RECONCILER_PATH}.workflow_run_repo", new=mocked),
        patch("app.services.workflow_execution.dispatcher.workflow_run_repo", new=mocked),
    ):
        yield mocked


@pytest.fixture
def event_log():
    with patch("app.services.workflow_execution.events.append", new=AsyncMock()):
        yield


def _run(**overrides: object) -> WorkflowRun:
    run_id = overrides.pop("id", uuid.uuid4())
    defaults: dict[str, object] = {
        "id": run_id,
        "organization_id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "workflow_version_id": uuid.uuid4(),
        "draft_graph_snapshot": None,
        "mode": "real",
        "status": WorkflowRunStatus.RUNNING.value,
        "triggered_by": "api",
        "execution_principal_user_id": uuid.uuid4(),
        "budget_limit": None,
        "spent_cost": Decimal("0"),
        "cost_is_partial": False,
        "deadline_at": None,
        "next_event_seq": 0,
        "paused_reason": None,
        "error": None,
        "root_run_id": run_id,
        "causation_run_id": None,
        "visited_trigger_ids": [],
        "depth": 0,
        "started_at": datetime.now(UTC),
        "ended_at": None,
    }
    defaults.update(overrides)
    return WorkflowRun(**defaults)


def _node_run(**overrides: object) -> NodeRun:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "workflow_run_id": uuid.uuid4(),
        "node_instance_id": uuid.uuid4(),
        "scope_path": [],
        "status": NodeRunStatus.WAITING.value,
        "waiting_reason": "approval",
        "resume_token": None,
        "waiting_agent_run_id": uuid.uuid4(),
        "started_at": None,
        "ended_at": None,
    }
    defaults.update(overrides)
    return NodeRun(**defaults)


def _outbox(*, node_run_id: uuid.UUID, **overrides: object) -> DispatchOutbox:
    """A claim whose lease has already run out - what the orphan sweep acts on."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "workflow_run_id": uuid.uuid4(),
        "node_run_id": node_run_id,
        "available_at": datetime.now(UTC),
        "claimed_by": uuid.uuid4(),
        "lease_expires_at": datetime.now(UTC) - timedelta(seconds=1),
        "status": DispatchOutboxStatus.CLAIMED.value,
    }
    defaults.update(overrides)
    return DispatchOutbox(**defaults)


def _attempt(**overrides: object) -> NodeAttempt:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "node_run_id": uuid.uuid4(),
        "attempt_no": 1,
        "idempotency_key": "key",
        "retry_guarantee": RetryGuarantee.IDEMPOTENT.value,
        "status": NodeAttemptStatus.IN_FLIGHT.value,
        "result": None,
        "cost": Decimal("0"),
        "cost_is_partial": False,
        "started_at": datetime.now(UTC),
        "ended_at": None,
    }
    defaults.update(overrides)
    return NodeAttempt(**defaults)


class TestStaleClaims:
    async def test_returns_the_run_and_node_run_ids_of_every_stale_claim(self, repo):
        run_id, node_run_id = uuid.uuid4(), uuid.uuid4()
        row = MagicMock(workflow_run_id=run_id, node_run_id=node_run_id)
        repo.take_stale_claims_for_resubmission.return_value = [row]

        service = WorkflowReconcilerService(object())
        pairs = await service.stale_claims()

        assert pairs == [(run_id, node_run_id)]

    async def test_nothing_stale_is_an_empty_list(self, repo):
        repo.take_stale_claims_for_resubmission.return_value = []
        service = WorkflowReconcilerService(object())
        assert await service.stale_claims() == []


class TestResolveOrphanedAttempts:
    async def test_resolves_each_orphan_it_finds(self, repo, event_log):
        node_run = _node_run(status=NodeRunStatus.RUNNING.value, waiting_agent_run_id=None)
        attempt = _attempt(node_run_id=node_run.id)
        run = _run(id=node_run.workflow_run_id)

        repo.list_orphaned_in_flight.return_value = [attempt]
        repo.get_node_run_by_id.return_value = node_run
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run_for_update.return_value = _outbox(node_run_id=node_run.id)
        repo.get_attempt.return_value = attempt
        repo.settle_attempt.side_effect = _settle_effect

        service = WorkflowReconcilerService(object())
        resolved = await service.resolve_orphaned_attempts()

        assert resolved == 1
        assert attempt.status == NodeAttemptStatus.UNCERTAIN.value

    @pytest.mark.parametrize(
        "outbox_overrides",
        [
            # Reclaimed by another worker between the scan and the lock - a
            # lease computed when the test runs, not when it is collected.
            pytest.param(
                lambda: {"lease_expires_at": datetime.now(UTC) + timedelta(minutes=2)},
                id="renewed",
            ),
            # Closed (a cancel, another sweep) only just now: a worker still
            # running the handler gets a lease to settle it first.
            pytest.param(
                lambda: {
                    "status": DispatchOutboxStatus.DONE.value,
                    "updated_at": datetime.now(UTC),
                },
                id="done-just-now",
            ),
            pytest.param(
                lambda: {
                    "status": DispatchOutboxStatus.CANCELLED.value,
                    "updated_at": datetime.now(UTC),
                },
                id="cancelled-just-now",
            ),
            pytest.param(lambda: {"status": DispatchOutboxStatus.PENDING.value}, id="pending"),
        ],
    )
    async def test_an_orphan_somebody_may_still_settle_is_left_alone(
        self, repo, event_log, outbox_overrides
    ):
        """Only an attempt nobody can still settle is resolved; resolving on the
        scan's word would close a live claim and let its holder run the node a
        second time."""
        node_run = _node_run(status=NodeRunStatus.RUNNING.value, waiting_agent_run_id=None)
        attempt = _attempt(node_run_id=node_run.id)
        run = _run(id=node_run.workflow_run_id)
        repo.list_orphaned_in_flight.return_value = [attempt]
        repo.get_node_run_by_id.return_value = node_run
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run_for_update.return_value = _outbox(
            node_run_id=node_run.id, **outbox_overrides()
        )
        repo.get_attempt.return_value = attempt

        resolved = await WorkflowReconcilerService(object()).resolve_orphaned_attempts()

        assert resolved == 0
        assert attempt.status == NodeAttemptStatus.IN_FLIGHT.value
        repo.mark_outbox_done.assert_not_called()

    @pytest.mark.parametrize(
        "outbox",
        [
            pytest.param(
                lambda node_run_id: _outbox(
                    node_run_id=node_run_id,
                    status=DispatchOutboxStatus.CANCELLED.value,
                    updated_at=datetime.now(UTC) - timedelta(hours=1),
                ),
                id="closed-long-ago",
            ),
            pytest.param(lambda _node_run_id: None, id="no-row"),
        ],
    )
    async def test_an_orphan_behind_a_row_closed_long_ago_is_resolved_and_the_row_kept(
        self, repo, event_log, outbox
    ):
        """A cancel while the worker was dead closed the row under the attempt;
        the attempt still settles, and the row keeps the status that records
        why it was closed."""
        node_run = _node_run(status=NodeRunStatus.RUNNING.value, waiting_agent_run_id=None)
        attempt = _attempt(node_run_id=node_run.id)
        run = _run(id=node_run.workflow_run_id, status=WorkflowRunStatus.CANCELLED.value)
        repo.list_orphaned_in_flight.return_value = [attempt]
        repo.get_node_run_by_id.return_value = node_run
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run_for_update.return_value = outbox(node_run.id)
        repo.get_attempt.return_value = attempt
        repo.settle_attempt.side_effect = _settle_effect

        resolved = await WorkflowReconcilerService(object()).resolve_orphaned_attempts()

        assert resolved == 1
        assert attempt.status == NodeAttemptStatus.UNCERTAIN.value
        repo.mark_outbox_done.assert_not_called()

    async def test_a_node_run_that_no_longer_exists_is_skipped(self, repo, event_log):
        attempt = _attempt()
        repo.list_orphaned_in_flight.return_value = [attempt]
        repo.get_node_run_by_id.return_value = None

        service = WorkflowReconcilerService(object())
        resolved = await service.resolve_orphaned_attempts()

        assert resolved == 0
        repo.settle_attempt.assert_not_called()

    async def test_a_run_that_no_longer_exists_is_skipped(self, repo, event_log):
        node_run = _node_run()
        attempt = _attempt(node_run_id=node_run.id)
        repo.list_orphaned_in_flight.return_value = [attempt]
        repo.get_node_run_by_id.return_value = node_run
        repo.get_run_by_id_for_update.return_value = None

        service = WorkflowReconcilerService(object())
        resolved = await service.resolve_orphaned_attempts()

        assert resolved == 0

    async def test_an_attempt_already_resolved_between_scan_and_lock_is_skipped(
        self, repo, event_log
    ):
        node_run = _node_run()
        attempt = _attempt(node_run_id=node_run.id)
        run = _run(id=node_run.workflow_run_id)
        repo.list_orphaned_in_flight.return_value = [attempt]
        repo.get_node_run_by_id.return_value = node_run
        repo.get_run_by_id_for_update.return_value = run
        # `begin_attempt`'s own inline check already resolved it first.
        repo.get_attempt.return_value = _attempt(
            id=attempt.id, node_run_id=node_run.id, status=NodeAttemptStatus.UNCERTAIN.value
        )

        service = WorkflowReconcilerService(object())
        resolved = await service.resolve_orphaned_attempts()

        assert resolved == 0
        repo.settle_attempt.assert_not_called()


async def _settle_effect(_db, *, attempt, status, result, cost, cost_is_partial, ended_at):
    attempt.status = status
    attempt.result = result
    attempt.cost = cost
    attempt.cost_is_partial = cost_is_partial
    attempt.ended_at = ended_at
    return attempt


class TestWakeStaleApprovalDecisions:
    async def test_inserts_an_outbox_row_for_each_stale_wait(self, repo):
        node_run = _node_run()
        run = _run(id=node_run.workflow_run_id)
        repo.list_stale_approval_waits.return_value = [node_run]
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        db = _nested_txn_db()

        service = WorkflowReconcilerService(db)
        woken = await service.wake_stale_approval_decisions()

        assert woken == 1
        repo.create_outbox.assert_awaited_once()

    async def test_a_run_that_no_longer_exists_is_skipped(self, repo):
        node_run = _node_run()
        repo.list_stale_approval_waits.return_value = [node_run]
        repo.get_run_by_id_for_update.return_value = None

        service = WorkflowReconcilerService(object())
        woken = await service.wake_stale_approval_decisions()

        assert woken == 0
        repo.create_outbox.assert_not_called()

    async def test_a_race_with_the_direct_wake_is_swallowed(self, repo):
        node_run = _node_run()
        run = _run(id=node_run.workflow_run_id)
        repo.list_stale_approval_waits.return_value = [node_run]
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.create_outbox.side_effect = IntegrityError("insert", {}, Exception("dup"))
        db = _nested_txn_db()

        service = WorkflowReconcilerService(db)
        woken = await service.wake_stale_approval_decisions()

        assert woken == 0

    async def test_a_node_that_moved_on_since_the_scan_gets_no_row(self, repo):
        """The scan is unlocked; a node the direct wake dispatched meanwhile must
        not get a second row, which would outlive it and strand the run."""
        scanned = _node_run()
        run = _run(id=scanned.workflow_run_id)
        repo.list_stale_approval_waits.return_value = [scanned]
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = _node_run(
            id=scanned.id, status=NodeRunStatus.SUCCEEDED.value
        )

        woken = await WorkflowReconcilerService(_nested_txn_db()).wake_stale_approval_decisions()

        assert woken == 0
        repo.create_outbox.assert_not_called()

    async def test_nothing_stale_wakes_nothing(self, repo):
        repo.list_stale_approval_waits.return_value = []
        service = WorkflowReconcilerService(object())
        assert await service.wake_stale_approval_decisions() == 0


class _FakeNestedTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _nested_txn_db() -> MagicMock:
    db = MagicMock()
    db.begin_nested = MagicMock(side_effect=lambda: _FakeNestedTxn())
    return db
