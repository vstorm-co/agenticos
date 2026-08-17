"""Inbound webhook that fires an event trigger - a GitHub issue, an email.

Authentication is the trigger's own HMAC secret, not a session, so these routes
carry no auth dependency - exactly like the channel webhooks. The decision to fire
is the service's; this layer only reads the raw body (the bytes the signature
covers), hands them over, and submits the fire as its own capped Prefect flow so
the provider gets a fast 202 while the agent run happens in the worker, out of the
API process.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AgentTriggerSvc
from app.worker.tasks.trigger_tasks import dispatch_trigger_fire

logger = logging.getLogger(__name__)

router = APIRouter()


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

    A matched delivery is submitted as its own `run-scheduled-trigger` flow -
    the same capped, isolated door the scheduled heartbeat uses - rather than run
    in this process. A burst of deliveries therefore starts capped worker runs
    instead of that many concurrent agent runs competing with request handling on
    the API's event loop. The submit is one fast Prefect call, well inside a
    provider's delivery timeout.
    """
    body = await request.body()
    decision = await service.prepare_event_fire(
        source, trigger_id, body=body, headers=dict(request.headers)
    )
    if decision is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)

    await dispatch_trigger_fire(str(decision.trigger_id), event_context=decision.event_context)
    return Response(status_code=status.HTTP_202_ACCEPTED)
