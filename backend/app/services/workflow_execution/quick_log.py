"""Write a step's Quick Log line while the step settles.

The dispatcher calls these in the transaction that settles the step, so the line
commits - or rolls back - with the step it describes. Writing never changes a run:
no dispatch, no retry, no budget, no node count, and a message that reads something
that has no value renders it empty instead of raising. A step that was skipped,
switched off, or never started writes nothing, and a step a retry run reuses writes
nothing new; its line is in the run it succeeded in.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.models.workflow_log_entry import MAX_LOG_MESSAGE_CHARS
from app.db.models.workflow_run import NodeRun, NodeRunStatus, WorkflowRun, WorkflowRunMode
from app.repositories import workflow_log_entry as workflow_log_repo
from app.workflows import _registry
from app.workflows.contracts.definition import NodeDefinition
from app.workflows.contracts.policy import ERROR_PORT
from app.workflows.contracts.results import WorkflowError
from app.workflows.graph.model import NodeInstance, QuickLog, WorkflowGraph
from app.workflows.graph.quick_log import render
from app.workflows.graph.validate import instance_ports


def _step_label(node: NodeInstance, definition: NodeDefinition | None) -> str:
    return node.label or (definition.name if definition is not None else node.definition_id)


def _left_by(
    graph: WorkflowGraph, node: NodeInstance, definition: NodeDefinition, output: dict[str, Any]
) -> list[str]:
    """The output ports a step that completed left by, in the order the step lists them."""
    ports = [
        port.id
        for port in instance_ports(graph, {node.id: definition})[node.id]
        if port.kind == "output" and port.id != ERROR_PORT
    ]
    if definition.routes is None:
        return ports
    chosen = definition.routes(output)
    return [port for port in ports if port in chosen] or sorted(chosen)


async def _write(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node: NodeInstance,
    quick_log: QuickLog,
    label: str,
    outcome: str,
    status: NodeRunStatus,
    output: dict[str, Any] | None,
    error: WorkflowError | None,
    is_pinned: bool,
) -> None:
    message = render(
        quick_log.message,
        step=label,
        outcome=outcome,
        output=output,
        error=error.model_dump(mode="json", include={"code", "message"}) if error else None,
        limit=MAX_LOG_MESSAGE_CHARS,
    )
    await workflow_log_repo.create(
        db,
        organization_id=run.organization_id,
        workflow_id=run.workflow_id,
        run_id=run.id,
        node_instance_id=node.id,
        step_label=label[:128],
        outcome=outcome[:256],
        status=status.value,
        message=message,
        is_test=run.mode == WorkflowRunMode.TEST.value,
        is_pinned=is_pinned,
    )


async def log_completed(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    graph: WorkflowGraph,
    node_run: NodeRun,
    definition: NodeDefinition,
    output: dict[str, Any],
    is_pinned: bool,
) -> None:
    """The line of a step that completed, when the ports it left by log."""
    node = graph.node_by_id.get(node_run.node_instance_id)
    quick_log = node.quick_log if node is not None else None
    if node is None or quick_log is None:
        return
    left = _left_by(graph, node, definition, output)
    outputs = quick_log.outputs
    if outputs is not None and not any(port in outputs for port in left):
        return
    await _write(
        db,
        run=run,
        node=node,
        quick_log=quick_log,
        label=_step_label(node, definition),
        outcome=", ".join(left),
        status=NodeRunStatus.SUCCEEDED,
        output=output,
        error=None,
        is_pinned=is_pinned,
    )


async def log_failed(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    graph: WorkflowGraph,
    node_run: NodeRun,
    error: WorkflowError,
    routed: bool,
) -> None:
    """The line of a step that failed for good, whether it routes the error or ends the run.

    A failure that is not routed - one that ends the run, or that a loop absorbs - is
    logged whatever `outputs` says: it leaves by no output. A routed `error` port
    follows the filter.
    """
    node = graph.node_by_id.get(node_run.node_instance_id)
    quick_log = node.quick_log if node is not None else None
    if node is None or quick_log is None:
        return
    outputs = quick_log.outputs
    if routed and outputs is not None and ERROR_PORT not in outputs:
        return
    try:
        definition: NodeDefinition | None = _registry.get(
            node.definition_id, node.definition_version
        )
    except BadRequestError:
        # Removed in a deploy since the graph was published; the line is still worth writing.
        definition = None
    await _write(
        db,
        run=run,
        node=node,
        quick_log=quick_log,
        label=_step_label(node, definition),
        outcome=ERROR_PORT,
        status=NodeRunStatus.FAILED,
        output=None,
        error=error,
        is_pinned=False,
    )
