"""`core.input`: where a graph begins, holding what the run was started with.

It has no configuration and no input of its own. The invoking surface - an API
call, a chat message, a webhook, a new table record - supplied a payload when it
admitted the run, and this node hands it to the graph as `payload`, with
`triggered_by` naming the surface. Nodes downstream bind to fields of it by path
(`payload.question`); a path the payload does not have is refused when that node
is dispatched, not here, because the payload's shape is the caller's.
"""

from pydantic import BaseModel

from app.services.workflow_execution import context
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.contracts.results import Completed, NodeResult


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand the graph the run's frozen input."""
    current = context.current()
    return Completed[WorkflowInputPayload](
        output=WorkflowInputPayload(payload=current.run_input, triggered_by=current.triggered_by)
    )
