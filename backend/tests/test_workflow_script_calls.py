"""Crash recovery of a Python action uses its child row, never guessed effects."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.permissions import AuthContext
from app.db.models.workflow_run import NodeAttempt, NodeRun, WorkflowRun
from app.services.workflow_execution import dispatcher, script_calls
from app.services.workflow_execution.exceptions import (
    InvalidBindingError,
    ScriptActionUnavailableError,
    ScriptRetryUnsafeError,
)
from app.workflows.contracts.script import ScriptActionRequest
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio


@pytest.fixture
def call(monkeypatch):
    original = WorkflowRun(id=uuid4(), organization_id=uuid4())
    run = WorkflowRun(
        id=uuid4(), organization_id=original.organization_id, retry_of_run_id=original.id
    )
    parent = NodeRun(id=uuid4(), workflow_run_id=run.id, node_instance_id=uuid4(), scope_path=[])
    request = ScriptActionRequest(
        index=0,
        alias="save",
        inputs={"value": 42},
        checkpoint="private-cursor",
        stdout="private-log",
        resume_token=str(parent.id),
    )
    parent.resume_payload = request.model_dump(mode="json")
    child = NodeRun(
        id=uuid4(),
        workflow_run_id=run.id,
        node_instance_id=parent.node_instance_id,
        scope_path=script_calls.child_scope(parent, request),
    )
    repo = AsyncMock()
    monkeypatch.setattr(script_calls, "repo", repo)
    repo.get_run.return_value = original
    return run, parent, child, request, repo


def test_checkpoint_is_validated_but_not_written_into_attempt_history(call):
    _, _, _, request, _ = call
    outcome = dispatcher.HandlerOutcome(result=request)
    returned, history = dispatcher._persistable_outcome(outcome)
    assert returned is outcome
    assert history.keys() == {"status", "reason", "resume_token", "resume_at"}
    assert history["status"] == "waiting"


@pytest.mark.parametrize(
    "problem",
    ["missing-history", "changed-arguments", "unknown-write", "missing-output", "cyclic-history"],
)
async def test_a_new_run_will_not_repeat_an_unproven_write(call, problem):
    run, _, child, _, repo = call
    old = NodeRun(id=uuid4(), scope_path=child.scope_path, status="failed")
    repo.script_call_at.return_value = old
    repo.get_latest_attempt.return_value = NodeAttempt(status="uncertain")
    if problem == "missing-history":
        repo.get_run.return_value = None
    elif problem == "changed-arguments":
        old.scope_path = [{"action": "save", "index": 0, "arguments_digest": "other"}]
    elif problem == "missing-output":
        old.status = "succeeded"
    elif problem == "cyclic-history":
        repo.script_call_at.return_value = None
        repo.get_run.return_value.retry_of_run_id = run.retry_of_run_id
    with pytest.raises(ScriptRetryUnsafeError):
        await script_calls.retry_output(AsyncMock(), run, child, writes=True)


@pytest.mark.parametrize("writes,started", [(False, True), (True, False)])
async def test_recovery_can_run_an_unsent_write_or_a_failed_read(call, writes, started):
    run, _, child, _, repo = call
    repo.script_call_at.return_value = NodeRun(
        id=uuid4(), scope_path=child.scope_path, status="failed"
    )
    repo.get_latest_attempt.return_value = NodeAttempt(status="failed") if started else None
    assert await script_calls.retry_output(AsyncMock(), run, child, writes=writes) is None


@pytest.mark.parametrize(
    "problem", ["parent-missing", "scope-changed", "child-pending", "output-missing"]
)
async def test_resume_refuses_a_missing_or_mismatched_child(call, problem):
    run, parent, child, _, repo = call
    if problem == "parent-missing":
        repo.get_node_run_by_identity.return_value = None
    elif problem == "scope-changed":
        repo.get_node_run_by_identity.return_value = parent
        child.scope_path = [{"action": "unexpected", "index": 0}]
    else:
        repo.get_node_run_by_identity.return_value = child
        child.status = "pending" if problem == "child-pending" else "succeeded"
        repo.get_latest_attempt.return_value = None
    with pytest.raises(InvalidBindingError):
        if problem in ("parent-missing", "scope-changed"):
            await script_calls.pending_request(AsyncMock(), run, child)
        else:
            await script_calls.resume(AsyncMock(), run, parent)


@pytest.mark.parametrize("limit", ["count", "storage"])
async def test_oversized_calls_stop_before_an_action_is_queued(call, monkeypatch, limit):
    run, parent, _, request, _ = call
    updates = AsyncMock()
    monkeypatch.setattr(dispatcher, "workflow_run_repo", updates)
    failed = AsyncMock()
    monkeypatch.setattr(dispatcher, "_fail_node_and_run", failed)
    monkeypatch.setattr(dispatcher.settings, "WORKFLOW_RUN_MAX_NODE_RUNS", 5)
    updates.count_node_runs.return_value = 5 if limit == "count" else 4
    parent.resume_payload = None
    run.inline_result_bytes = 0
    monkeypatch.setattr(dispatcher.admission, "inline_storage_scope", AsyncMock(return_value="run"))
    assert await dispatcher._park_script(AsyncMock(), run, parent, request, datetime.now(UTC)) == []
    assert failed.await_args.kwargs["error"].code == (
        "NODE_RUN_LIMIT" if limit == "count" else "WORKFLOW_INLINE_RESULT_LIMIT"
    )
    updates.create_node_run.assert_not_awaited()


@pytest.mark.security
async def test_a_caller_without_table_creation_permission_cannot_dispatch_the_action(call):
    run, parent, child, _, repo = call
    request = ScriptActionRequest.model_validate(parent.resume_payload).model_copy(
        update={"inputs": {}}
    )
    child.scope_path = script_calls.child_scope(parent, request)
    parent.resume_payload = request.model_dump(mode="json")
    repo.get_node_run_by_identity.return_value = parent
    auth = AuthContext(user_id=uuid4(), organization_id=run.organization_id, role="viewer")
    node = NodeInstance(
        id=child.node_instance_id,
        definition_id="code.python.actions",
        definition_version=1,
        layout=NodePosition(x=0, y=0),
        config={
            "code": "save()",
            "actions": {
                "save": {
                    "type": "table.create",
                    "config": {"name": "cases", "columns": [{"label": "name", "type": "text"}]},
                }
            },
        },
    )
    graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,), edges=())
    with pytest.raises(ScriptActionUnavailableError):
        await dispatcher._script_action_call(AsyncMock(), run, child, graph, node, "save", auth)
