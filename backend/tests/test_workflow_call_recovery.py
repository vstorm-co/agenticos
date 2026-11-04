"""Called-workflow recovery refuses lost history instead of replaying effects."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.permissions import AuthContext
from app.db.models.workflow import Workflow
from app.db.models.workflow_run import NodeRun, WorkflowRun
from app.services.workflow_execution import context
from app.workflows.contracts.results import Failed
from app.workflows.nodes.workflow_run import _handler as calls

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def recovery(monkeypatch):
    org, node_id, workflow_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    current = context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid.uuid4(),
        node_run_id=node_id,
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=None,
    )
    caller = WorkflowRun(
        id=current.workflow_run_id,
        organization_id=org,
        workflow_id=uuid.uuid4(),
        retry_of_run_id=uuid.uuid4(),
        budget_limit=None,
        depth=0,
        visited_trigger_ids=[],
    )
    step = NodeRun(id=node_id, scope_path=[{"loop_node_id": str(uuid.uuid4()), "index": 2}])
    previous = WorkflowRun(id=caller.retry_of_run_id, organization_id=org, retry_of_run_id=None)
    workflow = Workflow(
        id=workflow_id,
        organization_id=org,
        status="published",
        live_trigger="trigger.workflow_call",
        current_version_id=uuid.uuid4(),
    )
    monkeypatch.setattr(calls.workflow_run_repo, "get_node_run_by_id", AsyncMock(return_value=step))
    monkeypatch.setattr(
        calls.workflow_run_repo, "get_node_run_by_identity", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(calls.workflow_run_repo, "get_run_called_by", AsyncMock(return_value=None))
    monkeypatch.setattr(
        calls.workflow_run_repo, "call_history_requires_child", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(calls.workflow_run_repo, "get_run", AsyncMock(return_value=previous))
    monkeypatch.setattr(calls.workflow_repo, "get", AsyncMock(return_value=workflow))
    monkeypatch.setattr(calls, "resolve_access", AsyncMock(return_value=True))
    with context.dispatching_as(current):
        yield caller, previous, step, workflow


async def test_a_missing_current_step_refuses_a_call_instead_of_starting_it(recovery, monkeypatch):
    caller, _previous, _step, _workflow = recovery
    monkeypatch.setattr(calls.workflow_run_repo, "get_node_run_by_id", AsyncMock(return_value=None))
    result = await calls._previous_call(MagicMock(), caller)
    assert isinstance(result, Failed) and result.error.code == "CALLED_WORKFLOW_UNAVAILABLE"


async def test_an_unstarted_previous_call_can_be_started_once(recovery, monkeypatch):
    caller, _previous, step, _workflow = recovery
    monkeypatch.setattr(
        calls.workflow_run_repo, "get_node_run_by_identity", AsyncMock(return_value=step)
    )
    assert await calls._previous_call(MagicMock(), caller) is None
    assert (
        calls.workflow_run_repo.get_node_run_by_identity.await_args.kwargs["scope_path"]
        == step.scope_path
    )


async def test_a_missing_child_with_confirmed_history_refuses_the_call(recovery, monkeypatch):
    caller, _previous, step, workflow = recovery
    monkeypatch.setattr(calls.workflow_run_repo, "get_run", AsyncMock(return_value=caller))
    monkeypatch.setattr(
        calls.workflow_run_repo, "get_node_run_by_identity", AsyncMock(return_value=step)
    )
    monkeypatch.setattr(
        calls.workflow_run_repo, "call_history_requires_child", AsyncMock(return_value=True)
    )
    result = await calls._call(MagicMock(), calls.WorkflowRunConfig(workflow_id=workflow.id), {})
    assert isinstance(result, Failed) and result.error.code == "CALLED_WORKFLOW_HISTORY_UNAVAILABLE"


async def test_missing_retry_ancestry_refuses_recovery(recovery, monkeypatch):
    caller, _previous, _step, _workflow = recovery
    monkeypatch.setattr(calls.workflow_run_repo, "get_run", AsyncMock(return_value=None))
    result = await calls._previous_call(MagicMock(), caller)
    assert isinstance(result, Failed) and result.error.code == "CALLED_WORKFLOW_HISTORY_UNAVAILABLE"


async def test_cyclic_retry_ancestry_is_not_a_fresh_call(recovery):
    caller, previous, _step, _workflow = recovery
    previous.retry_of_run_id = previous.id
    result = await calls._previous_call(MagicMock(), caller)
    assert isinstance(result, Failed) and result.error.code == "CALLED_WORKFLOW_HISTORY_UNAVAILABLE"


async def test_an_unpublished_target_is_not_started_during_recovery(recovery, monkeypatch):
    caller, _previous, _step, workflow = recovery
    caller.retry_of_run_id = None
    workflow.current_version_id = None
    monkeypatch.setattr(calls.workflow_run_repo, "get_run", AsyncMock(return_value=caller))
    result = await calls._call(MagicMock(), calls.WorkflowRunConfig(workflow_id=workflow.id), {})
    assert isinstance(result, Failed) and result.error.code == "CALLED_WORKFLOW_UNAVAILABLE"


async def test_a_successful_child_is_reused_after_the_caller_lost_its_result(recovery, monkeypatch):
    caller, _previous, step, workflow = recovery
    child = WorkflowRun(id=uuid.uuid4(), status="succeeded", output={"already": "done"})
    monkeypatch.setattr(calls.workflow_run_repo, "get_run", AsyncMock(return_value=caller))
    monkeypatch.setattr(
        calls.workflow_run_repo, "get_node_run_by_identity", AsyncMock(return_value=step)
    )
    monkeypatch.setattr(calls.workflow_run_repo, "get_run_called_by", AsyncMock(return_value=child))
    assert (
        await calls._call(MagicMock(), calls.WorkflowRunConfig(workflow_id=workflow.id), {})
        is child
    )


@pytest.mark.parametrize(
    "status,error",
    [
        ("cancelled", {}),
        ("budget_exceeded", {}),
        ("failed", {"code": "PRINCIPAL_REVOKED"}),
        ("failed", {"code": "PARENT_RUN_STOPPED"}),
        ("failed", {"code": "ORG_LIMIT", "bypassable": False}),
    ],
)
async def test_called_run_governance_failures_cannot_be_hidden_by_an_error_branch(status, error):
    called = WorkflowRun(id=uuid.uuid4(), status=status, error=error)
    result = calls._answer(called, wait=True)
    assert isinstance(result, Failed) and not result.error.bypassable
