"""`trigger.webhook`: a workflow a signed HTTP delivery starts.

Publishing with `source_id` subscribes this entry to a reusable event source.
Without it, the workflow keeps its own address and signing secret. Both modes
hand the authenticated event on unchanged, as `body` and `delivery_id`.
"""

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._triggers import WebhookTriggerConfig, WebhookTriggerOutput, run_input_as


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Require permission to use the selected source before publishing its subscription."""
    if not isinstance(config, WebhookTriggerConfig) or config.source_id is None:
        return []
    from app.services.event_sources import EventSourceService

    try:
        await EventSourceService(db).require_use(ctx, config.source_id)
    except AuthorizationError, NotFoundError:
        return [("source_id", "Choose an event source you have permission to use")]
    return []


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the delivery the run was started with."""
    delivery = run_input_as(WebhookTriggerOutput)
    if isinstance(delivery, Failed):
        return delivery
    return Completed[WebhookTriggerOutput](output=delivery)
