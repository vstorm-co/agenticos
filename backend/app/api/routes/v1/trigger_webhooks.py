"""Inbound webhook that fires an event trigger - a GitHub issue, an email.

Authentication is the trigger's own HMAC secret, not a session, so these routes
carry no auth dependency - exactly like the channel webhooks. The decision to fire
is the service's; this layer only reads the raw body (the bytes the signature
covers), hands them over, and dispatches the fire to a background task so the
provider gets a fast 202 while the agent run happens out of the request.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AgentTriggerSvc
from app.worker.background.trigger_event import process_trigger_event

logger = logging.getLogger(__name__)

router = APIRouter()

# Holds a strong reference to each in-flight fire so the event loop cannot garbage
# -collect the task mid-run, discarded when it finishes. The same guard the Slack
# webhook keeps.
_background_tasks: set[asyncio.Task[None]] = set()


@router.post(
    "/triggers/{source}/{trigger_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
)
async def ingest_trigger_event(
    source: str,
    trigger_id: UUID,
    request: Request,
    service: AgentTriggerSvc,
) -> Any:
    """Receive a signed delivery and fire the event trigger it matches.

    Among *verified* deliveries the response gives nothing away: one with nothing
    to do - an unknown or inactive trigger, one that is not an event trigger of
    this source, or a payload the filter does not match - answers 202 exactly as a
    fired one does, so a caller who holds the secret cannot tell an existing
    trigger from a missing one. A signature that does *not* verify is a 403 (and a
    body that is not a JSON object a 400) - a deliberate trade for the integrator,
    whose provider surfaces that failure so a mistyped secret is fixable; the
    trigger ids are unguessable UUIDs, so the 403 is not a practical oracle. Both
    come from the service.
    """
    body = await request.body()
    decision = await service.prepare_event_fire(
        source, trigger_id, body=body, headers=dict(request.headers)
    )
    if decision is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)

    task = asyncio.create_task(process_trigger_event(decision.trigger_id, decision.event_context))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return Response(status_code=status.HTTP_202_ACCEPTED)
