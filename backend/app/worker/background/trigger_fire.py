"""In-process handler for a trigger fire that must not happen inside a request.

Two doors reach it, for one reason. The webhook route dispatches a verified event
delivery here so the provider gets a fast 202 - a GitHub delivery times out after
about ten seconds, far less than a run can take - and `run_now` dispatches a manual
fire here so the button does not hold its own HTTP request open for the length of
the run, which behind an ordinary proxy is a 504 for a run that is still going and
still spending (#658). Both arrive with the fire already decided and authorized;
this only runs it, on a session of its own.
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
