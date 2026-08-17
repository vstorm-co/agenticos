"""In-process handler for a `run_now` fire that must not happen inside a request.

`run_now` reaches it because a run held open inside its own HTTP request is a 504
from any ordinary proxy (#658), so the fire is queued for after the request's
commit and runs here, on a session of its own. The fire arrives already decided
and authorized; this only runs it.

The event-delivery path used to share this door, but a webhook burst starting
concurrent agent runs in the API process is what `run-scheduled-trigger` (the
capped Prefect flow) exists to prevent, so it is dispatched there instead - see
:func:`app.worker.tasks.trigger_tasks.dispatch_trigger_fire`. A single deliberate
`run_now` press carries no such burst, so it stays in-process.
"""

import logging
from uuid import UUID

from app.db.session import get_db_context
from app.services.agent_trigger import AgentTriggerService

logger = logging.getLogger(__name__)


async def fire_trigger(trigger_id: UUID, *, event_context: str | None = None) -> None:
    """Fire the trigger, on a fresh session, with no caller left to raise into.

    Errors are logged with a traceback but never re-raised: the response has
    already gone back to the provider or the browser, so an exception here would
    only be a noisy stack trace in the API process. `fire` itself already turns a
    budget or an authorization refusal into a disabled trigger rather than a raise,
    so what reaches here is an unexpected failure worth the log.
    """
    try:
        async with get_db_context() as db:
            await AgentTriggerService(db).fire(trigger_id, event_context=event_context)
    except Exception:
        logger.exception("trigger_fire_failed", extra={"trigger_id": str(trigger_id)})
