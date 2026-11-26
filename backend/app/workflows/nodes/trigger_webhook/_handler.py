"""`trigger.webhook`: a workflow a signed HTTP delivery starts.

Publishing with `source_id` subscribes this entry to a reusable event source.
Without it, the workflow keeps its own address and signing secret. Both modes
hand the authenticated event on unchanged, as `body` and `delivery_id`.
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
