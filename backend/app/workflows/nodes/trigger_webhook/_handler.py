"""`trigger.webhook`: a workflow a signed HTTP delivery starts.

Publishing a version with this trigger gives the workflow its own address and a
signing secret, shown once. Each delivery that verifies starts one run with its
JSON body; a retry that repeats the delivery id starts nothing.
"""

from pydantic import BaseModel

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._triggers import WebhookTriggerOutput, run_input_as


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the delivery the run was started with."""
    delivery = run_input_as(WebhookTriggerOutput)
    if isinstance(delivery, Failed):
        return delivery
    return Completed[WebhookTriggerOutput](output=delivery)
