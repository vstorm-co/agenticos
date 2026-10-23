"""Inbound webhook that fires an event trigger - a GitHub issue, an email.

Authentication is the trigger's own HMAC secret, not a session, so these routes
carry no auth dependency - exactly like the channel webhooks. The decision to fire
is the service's; this layer only reads the raw body (the bytes the signature
covers) and hands it over. The service queues the fire as a job, so the provider
gets a fast 202 while the agent run happens in a worker, out of the API process.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AgentTriggerSvc

router = APIRouter()


@router.post("/github-app", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def ingest_github_app_event(request: Request, service: AgentTriggerSvc) -> Any:
    """The one URL a GitHub App delivers to, for every installation (#1072).

    An App has one webhook URL and one signing secret per installation, so unlike
    `/triggers/{source}/{trigger_id}` this path names nothing: the installation
    id in the payload selects the grant, that organization's own App secret
    verifies the signature, and the repository and event choose the triggers.

    **One delivery can fire several triggers**, which the per-trigger URL cannot
    by construction - two triggers on the same repository is exactly what the
    presets invite. Each is submitted as its own capped flow, so a delivery
    matching four triggers starts four worker runs rather than four agent runs on
    the API's event loop.

    A delivery matching nothing answers 202, the same as one that fired
    everything: among verified deliveries the response gives nothing away.

    Each fire is a job queued in this request's transaction, so every matched
    trigger is queued or - if the commit fails - none is, and the 202 goes out
    only once they are.
    """
    headers = dict(request.headers)
    body = await request.body()
    await service.queue_app_fires(body=body, headers=headers)
    return Response(status_code=status.HTTP_202_ACCEPTED)


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

    A matched delivery is queued as a `fire-trigger` job - the same capped,
    isolated door the scheduled heartbeat uses - rather than run in this process.
    A burst of deliveries therefore queues capped worker runs instead of that many
    concurrent agent runs competing with request handling on the API's event
    loop. The job is one row in this request's transaction, well inside a
    provider's delivery timeout, and the 202 goes out only once it has committed.
    """
    headers = dict(request.headers)
    body = await request.body()
    await service.queue_event_fire(source, trigger_id, body=body, headers=headers)
    return Response(status_code=status.HTTP_202_ACCEPTED)
