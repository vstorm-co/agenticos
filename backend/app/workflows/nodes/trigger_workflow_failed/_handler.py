"""`trigger.workflow_failed`: a workflow another one's failed run starts.

A workflow whose settings name this one as its error workflow starts it once for
each of its runs that ends failed, with the run, its workflow, the step that
failed and the error. A run this trigger started never starts an error workflow
itself, so a failing error workflow cannot start itself again.
"""

from pydantic import BaseModel

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._triggers import WorkflowFailedTriggerOutput, run_input_as


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the failed run the error workflow was started with."""
    failure = run_input_as(WorkflowFailedTriggerOutput)
    if isinstance(failure, Failed):
        return failure
    return Completed[WorkflowFailedTriggerOutput](output=failure)
