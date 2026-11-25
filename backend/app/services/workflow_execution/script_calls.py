"""The private hand-off between a script node and its sequential, native child actions.

The graph instance stays the parent's; one extra scope segment distinguishes
every call (and every retry of that call) in the existing NodeRun identity.
Only the current continuation is kept, in the parent's private resume payload.
A parent and its child never both hold a live dispatch.
"""

import hashlib
import json
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import NodeRun, NodeRunStatus, WorkflowRun
from app.repositories import workflow_run as repo
from app.services.workflow_execution.exceptions import InvalidBindingError, ScriptRetryUnsafeError
from app.workflows.contracts.script import ScriptActionRequest, ScriptResume
from app.workflows.files import import_output_files
from app.workflows.graph.model import NodeInstance


def child_alias(row: NodeRun) -> str | None:
    if row.scope_path:
        alias = row.scope_path[-1].get("action")
        if isinstance(alias, str):
            return alias
    return None


def configured_step(
    nodes: dict[UUID, NodeInstance], row: NodeRun
) -> tuple[str, dict[str, JsonValue]] | None:
    """Identify the actual step that owns a wait, not the graph node shared by its calls."""
    node = nodes.get(row.node_instance_id)
    if node is None:
        return None
    alias = child_alias(row)
    if alias is None:
        return node.definition_id, node.config
    actions = node.config.get("actions")
    bound = actions.get(alias) if isinstance(actions, dict) else None
    if node.definition_id != "code.python.actions" or not isinstance(bound, dict):
        return None
    kind, config = bound.get("type"), bound.get("config", {})
    return (kind, config) if isinstance(kind, str) and isinstance(config, dict) else None


def child_scope(parent: NodeRun, request: ScriptActionRequest) -> list[dict[str, JsonValue]]:
    args = json.dumps(request.inputs, sort_keys=True, separators=(",", ":")).encode()
    return [
        *parent.scope_path,
        {
            "action": request.alias,
            "index": request.index,
            "arguments_digest": hashlib.sha256(args).hexdigest(),
        },
    ]


async def parent_of(db: AsyncSession, run: WorkflowRun, child: NodeRun) -> NodeRun:
    parent = await repo.get_node_run_by_identity(
        db,
        workflow_run_id=run.id,
        node_instance_id=child.node_instance_id,
        scope_path=child.scope_path[:-1],
    )
    if parent is None:
        raise InvalidBindingError(node_instance_id=child.node_instance_id, field="action")
    return parent


async def pending_request(
    db: AsyncSession, run: WorkflowRun, child: NodeRun
) -> ScriptActionRequest:
    parent = await parent_of(db, run, child)
    request = ScriptActionRequest.model_validate(parent.resume_payload)
    if child.scope_path != child_scope(parent, request):
        raise InvalidBindingError(node_instance_id=child.node_instance_id, field="action")
    return request


async def resume(db: AsyncSession, run: WorkflowRun, parent: NodeRun) -> ScriptResume:
    request = ScriptActionRequest.model_validate(parent.resume_payload)
    child = await repo.get_node_run_by_identity(
        db,
        workflow_run_id=run.id,
        node_instance_id=parent.node_instance_id,
        scope_path=child_scope(parent, request),
    )
    if child is None or child.status != NodeRunStatus.SUCCEEDED.value:
        raise InvalidBindingError(node_instance_id=parent.node_instance_id, field="action")
    latest = await repo.get_latest_attempt(db, node_run_id=child.id)
    output = latest.result.get("output") if latest is not None and latest.result else None
    if not isinstance(output, dict):
        raise InvalidBindingError(node_instance_id=parent.node_instance_id, field="action")
    return ScriptResume(
        alias=request.alias,
        index=request.index,
        checkpoint=request.checkpoint,
        stdout=request.stdout,
        output=output,
    )


async def retry_output(
    db: AsyncSession,
    run: WorkflowRun,
    child: NodeRun,
    *,
    writes: bool,
) -> dict[str, JsonValue] | None:
    """Reuse settled calls across retry runs. Never repeat an unconfirmed write.

    A retry of a retry can stop before reaching this call: walk back through
    those runs too. The old key was derived from the *old run*, so even an
    idempotent write with an unknown outcome is not safe to repeat in a new run.
    """
    previous_id = run.retry_of_run_id
    visited: set[UUID] = set()
    while previous_id is not None and previous_id not in visited:
        visited.add(previous_id)
        previous = await repo.get_run(db, previous_id, organization_id=run.organization_id)
        if previous is None:
            break
        old = await repo.script_call_at(
            db,
            workflow_run_id=previous.id,
            node_instance_id=child.node_instance_id,
            parent_scope=child.scope_path[:-1],
            index=child.scope_path[-1]["index"],
        )
        if old is not None:
            if old.scope_path != child.scope_path:
                raise ScriptRetryUnsafeError()
            latest = await repo.get_latest_attempt(db, node_run_id=old.id)
            if old.status == NodeRunStatus.SUCCEEDED.value:
                output = (
                    latest.result.get("output") if latest is not None and latest.result else None
                )
                if not isinstance(output, dict):
                    raise ScriptRetryUnsafeError()
                await import_output_files(
                    db,
                    organization_id=run.organization_id,
                    source_run_id=previous.id,
                    target_run_id=run.id,
                    output=output,
                    node_instance_id=child.node_instance_id,
                )
                return output
            if writes and latest is not None:
                raise ScriptRetryUnsafeError()
        previous_id = previous.retry_of_run_id
    if previous_id is not None:
        raise ScriptRetryUnsafeError()
    return None
