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
from app.workflows.contracts.payload import json_byte_size
from app.workflows.contracts.script import ScriptActionRequest, ScriptResume
from app.workflows.files import import_output_files
from app.workflows.graph.model import NodeInstance


def cursor_bytes(parent: NodeRun) -> int:
    return json_byte_size(parent.resume_payload, limit=2**63 - 1) if parent.resume_payload else 0


async def discard_cursor(
    db: AsyncSession,
    run: WorkflowRun,
    node: NodeRun,
    *,
    known_script: bool = False,
) -> None:
    """Release only a script parent's private state, under the run's row lock.

    Bulk cancellation might not even have a resolvable graph. The first child
    and the cursor were inserted atomically: its existence proves ownership,
    unlike inspecting a Wait payload that a caller can fill with arbitrary JSON.
    """
    if node.resume_payload is None or child_alias(node) is not None:
        return
    if (
        not known_script
        and await repo.script_call_at(
            db,
            workflow_run_id=run.id,
            node_instance_id=node.node_instance_id,
            parent_scope=node.scope_path,
            index=0,
        )
        is None
    ):
        return
    await repo.update_run(
        db,
        run=run,
        update_data={"inline_result_bytes": run.inline_result_bytes - cursor_bytes(node)},
    )
    await repo.update_node_run(db, node_run=node, update_data={"resume_payload": None})


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


def produces_resume_link(node: NodeInstance) -> bool:
    """A retry must regenerate its own URL, even inside a previously completed script."""
    if node.definition_id == "flow.resume_link":
        return True
    bindings = node.config.get("actions")
    return (
        node.definition_id == "code.python.actions"
        and isinstance(bindings, dict)
        and any(
            isinstance(binding, dict) and binding.get("type") == "flow.resume_link"
            for binding in bindings.values()
        )
    )


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
    reuse_result: bool = True,
    can_recompute: bool = False,
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
                # Position and enclosing scope matched in script_call_at. The
                # same alias in this frozen graph still names the same action.
                if not can_recompute or child_alias(old) != child_alias(child):
                    raise ScriptRetryUnsafeError()
                # Recompute with the new inputs, but check older calls as well:
                # an interrupted intermediate retry is not proof of safe history.
                reuse_result = False
                previous_id = previous.retry_of_run_id
                continue
            if old.status == NodeRunStatus.SUCCEEDED.value:
                if not reuse_result:
                    # Regenerate the run-local value only after matching the call.
                    return None
                latest = await repo.get_latest_attempt(db, node_run_id=old.id)
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
            if writes and await repo.may_have_dispatched(db, node_run_id=old.id):
                raise ScriptRetryUnsafeError()
        previous_id = previous.retry_of_run_id
    if previous_id is not None:
        raise ScriptRetryUnsafeError()
    return None
