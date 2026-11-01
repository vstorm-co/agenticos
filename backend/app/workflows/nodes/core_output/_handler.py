"""`core.output`: where a graph answers, naming what the run returns.

Its input has the shape `agent.run` produces - text, sources, artifacts and a
structured value - so an agent can feed the workflow's answer with nothing in
between. The handler records that input as the run's output, which the invoking
surface delivers back to its caller (#1792), and passes it on unchanged.
"""

from pydantic import BaseModel

from app.services.workflow_execution import context
from app.workflows.contracts.io import WorkflowOutputPayload
from app.workflows.contracts.results import Completed, NodeResult


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Record the bound answer as the run's output.

    Nothing bound is an answer too - a workflow that only writes to a table
    ends with nothing to say - so an unbound input is an empty payload, not a
    failure.
    """
    output = (
        node_input if isinstance(node_input, WorkflowOutputPayload) else WorkflowOutputPayload()
    )
    context.report_run_output(output.model_dump(mode="json"))
    return Completed[WorkflowOutputPayload](output=output)
