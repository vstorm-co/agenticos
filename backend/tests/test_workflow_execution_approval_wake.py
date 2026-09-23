"""`app.services.workflow_execution.approval_wake.wake_after_approval_decision`.

The queued coroutine `ApprovalService.decide` hands to `spawn_after_commit` -
opens its own session (mocked here at `get_worker_db_context`), so it is
tested the same way a Prefect flow body is: the session factory is stubbed,
the repository is mocked at the database edge.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.workflow_run import NodeRunStatus
from app.repositories import workflow_run as workflow_run_repo_module
from app.services.workflow_execution.approval_wake import wake_after_approval_decision

pytestmark = pytest.mark.anyio

WAKE_PATH = "app.services.workflow_execution.approval_wake"


class _FakeNestedTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _node_run(**overrides: object):
    node_run = MagicMock()
    node_run.id = uuid.uuid4()
    node_run.workflow_run_id = uuid.uuid4()
    node_run.status = NodeRunStatus.WAITING.value
    for field, value in overrides.items():
        setattr(node_run, field, value)
    return node_run


def _run(**overrides: object):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.organization_id = uuid.uuid4()
    for field, value in overrides.items():
        setattr(run, field, value)
    return run


@pytest.fixture
def repo():
    mocked = create_autospec(workflow_run_repo_module, instance=False)
    with patch(f"{WAKE_PATH}.workflow_run_repo", new=mocked):
        yield mocked


@pytest.fixture
def worker_db():
    db = MagicMock()
    db.begin_nested = MagicMock(side_effect=lambda: _FakeNestedTxn())

    @asynccontextmanager
    async def _context():
        yield db

    with patch(f"{WAKE_PATH}.get_worker_db_context", new=_context):
        yield db


class TestWakeAfterApprovalDecision:
    async def test_no_node_run_waiting_on_this_agent_run_is_a_no_op(self, repo, worker_db):
        repo.find_node_run_waiting_on_agent_run.return_value = None
        await wake_after_approval_decision(uuid.uuid4(), organization_id=uuid.uuid4())
        repo.create_outbox.assert_not_called()

    async def test_a_node_run_no_longer_waiting_is_left_alone(self, repo, worker_db):
        repo.find_node_run_waiting_on_agent_run.return_value = _node_run(
            status=NodeRunStatus.SUCCEEDED.value
        )
        await wake_after_approval_decision(uuid.uuid4(), organization_id=uuid.uuid4())
        repo.create_outbox.assert_not_called()

    async def test_a_run_that_no_longer_exists_is_a_no_op(self, repo, worker_db):
        repo.find_node_run_waiting_on_agent_run.return_value = _node_run()
        repo.get_run_by_id_for_update.return_value = None
        await wake_after_approval_decision(uuid.uuid4(), organization_id=uuid.uuid4())
        repo.create_outbox.assert_not_called()

    async def test_a_waiting_node_run_gets_a_fresh_outbox_row(self, repo, worker_db):
        node_run = _node_run()
        run = _run(id=node_run.workflow_run_id)
        repo.find_node_run_waiting_on_agent_run.return_value = node_run
        repo.get_run_by_id_for_update.return_value = run

        await wake_after_approval_decision(uuid.uuid4(), organization_id=uuid.uuid4())

        repo.create_outbox.assert_awaited_once()
        assert repo.create_outbox.await_args.kwargs["node_run_id"] == node_run.id

    async def test_a_race_with_the_reconciler_backstop_is_swallowed(self, repo, worker_db):
        node_run = _node_run()
        run = _run(id=node_run.workflow_run_id)
        repo.find_node_run_waiting_on_agent_run.return_value = node_run
        repo.get_run_by_id_for_update.return_value = run
        repo.create_outbox.side_effect = IntegrityError("insert", {}, Exception("dup"))

        await wake_after_approval_decision(uuid.uuid4(), organization_id=uuid.uuid4())
