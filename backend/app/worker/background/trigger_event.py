"""In-process handler for a verified event-trigger delivery.

Dispatched with `asyncio.create_task` from the trigger webhook route so the
provider gets a fast 202 while the agent run happens in the background - the same
shape the channel webhooks use, and for the same reason: a GitHub delivery times
out after about ten seconds, far less than a run can take. The delivery was already
authenticated and matched in the request; this only fires it.
"""

import logging
from uuid import UUID

from app.db.session import get_db_context
from app.services.agent_trigger import AgentTriggerService

logger = logging.getLogger(__name__)


async def process_trigger_event(trigger_id: UUID, event_context: str) -> None:
    """Fire the trigger the delivery matched, on a fresh session.

    Errors are logged with a traceback but never re-raised: the 202 has already
    gone back to the provider, so an exception here would only be a noisy stack
    trace in the API process. `fire` itself already turns a budget or an
    authorization refusal into a disabled trigger rather than a raise, so what
    reaches here is an unexpected failure worth the log.
    """
    try:
        async with get_db_context() as db:
            await AgentTriggerService(db).fire(trigger_id, event_context=event_context)
    except Exception:
        logger.exception("trigger_event_processing_failed", extra={"trigger_id": str(trigger_id)})
