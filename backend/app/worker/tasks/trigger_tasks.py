"""Agent triggers - the heartbeat that fires scheduled runs, and the run itself.

Two flows, mirroring the scheduled-sync pair but diverging from it where a run is
not a sync (see `docs/design/heartbeat-triggers-plan.md`, sections 3 and 4):

* `check_agent_triggers_flow` is the heartbeat, one `IntervalSchedule(60)`
  deployment. Each tick claims the triggers due now - `FOR UPDATE SKIP LOCKED`,
  so a tick that outruns its own 60-second window cannot be double-claimed by the
  next - and submits one run per claimed trigger through `run_deployment` without
  awaiting it, so a slow agent run never holds the tick open. `check_scheduled_syncs_flow`
  gathers-and-awaits its children instead; copying it here would block the tick.
* `run_scheduled_trigger_flow` is one fired run, as its own flow run so it is
  capped by `PREFECT_RUNNER_LIMIT` and isolated from the tick that scheduled it.
  The work is `AgentTriggerService.fire`, which runs the agent as the trigger's
  creator through the ordinary run path.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from prefect import flow
from prefect.deployments import run_deployment

from app.db.session import get_worker_db_context

logger = logging.getLogger(__name__)

# The heartbeat submits each due trigger's run as this deployment, addressed by
# its "<flow-name>/<deployment-name>" handle. Both halves are registered together
# in `app/worker/prefect_app.py`; they match by design.
_RUN_TRIGGER_DEPLOYMENT = "run-scheduled-trigger/run-scheduled-trigger"


async def dispatch_trigger_fire(
    trigger_id: str,
    *,
    event_context: str | None = None,
    claimed_at: datetime | None = None,
) -> None:
    """Submit one trigger's run as its own flow run, and return.

    `timeout=0` is what makes this submit-and-return: `run_deployment` enqueues
    the run and does not wait for it, so a caller's cost is one API call rather
    than the run it starts. A separate flow run is also what keeps each fired
    agent run capped by `PREFECT_RUNNER_LIMIT` and isolated from whatever
    dispatched it.

    Both doors reach the fire through here: the scheduled heartbeat below (with no
    `event_context`) and an inbound event delivery (`trigger_webhooks`, carrying
    the rendered context). Routing the event path through the same capped flow is
    why a burst of deliveries - five issues opened in a minute - starts capped
    worker flow runs rather than that many concurrent agent runs inside the API
    process, competing with request handling for its event loop.

    `claimed_at` is the `fire_in_flight_since` the scheduled claim stamped, handed
    to the fire as its claim ticket so it clears only the marker its own claim set -
    the guard against a fire that outran the lease clearing a newer claim's marker.
    Only the scheduled heartbeat sets it; an event delivery has no claim behind it.
    It rides across the Prefect boundary as an ISO string, the shape a flow
    parameter takes.
    """
    # `run_deployment` is sync-compatible: its stub unions the coroutine it
    # returns in an async context with the `FlowRun` a sync caller gets, and ty
    # cannot tell which applies. Awaiting it is correct here.
    await run_deployment(  # ty: ignore[invalid-await]
        name=_RUN_TRIGGER_DEPLOYMENT,
        parameters={
            "trigger_id": trigger_id,
            "event_context": event_context,
            "claimed_at": None if claimed_at is None else claimed_at.isoformat(),
        },
        timeout=0,
    )


@flow(name="agent-triggers-check", log_prints=True)
async def check_agent_triggers_flow() -> None:
    """Heartbeat: claim the triggers due now and submit a run for each."""
    from app.services.agent_trigger import AgentTriggerService

    # The one clock for the whole tick: `claim_and_advance` stamps every claimed
    # trigger's `fire_in_flight_since` with exactly this `now`, so it is each fire's
    # claim ticket - handed back as `claimed_at` so the fire clears only the marker
    # its own claim set.
    now = datetime.now(UTC)
    async with get_worker_db_context() as db:
        triggers = await AgentTriggerService(db).claim_and_advance(now=now)
    # Dispatched after the claim's transaction commits, so every submitted run
    # sees the advanced `next_fire_at` and the tick's own work is durable before
    # any of it is handed on.
    dispatched = 0
    for trigger in triggers:
        try:
            await dispatch_trigger_fire(str(trigger.id), claimed_at=now)
        except Exception:
            # Isolate each dispatch so a single failed `run_deployment` (a transient
            # Prefect API error) does not abort the loop and cost the rest of the
            # batch their fire too. The marker is deliberately left set: a submit that
            # raised may still have created the child flow - `run_deployment` can
            # enqueue the run on the Prefect API and then lose or time out the
            # response - so clearing it here would let the next tick submit a second
            # fire on top of an accepted-but-queued one, duplicating the spend and its
            # side effects (#589). Leaving it set means `FIRE_LEASE`, not this loop,
            # governs re-dispatch: a genuinely lost submit waits out the lease rather
            # than risking a double fire.
            logger.exception("agent_trigger_dispatch_failed", extra={"trigger_id": str(trigger.id)})
        else:
            dispatched += 1
    logger.info("agent_triggers_check", extra={"dispatched": dispatched, "claimed": len(triggers)})


@flow(name="portal-poll", log_prints=True)
async def poll_portal_grants_flow() -> None:
    """Heartbeat: read the connected accounts nobody pushes to, and fire what arrived.

    The third flow, and the one that makes a polled portal a delivery mechanism
    rather than a second kind of trigger. Gmail pushes nothing without a Cloud
    Pub/Sub topic and a registration that expires weekly, so this asks - once a
    minute, one request per connected mailbox - and hands whatever it finds to the
    same match-then-fire path a webhook delivery takes.

    The shape is the sibling heartbeat's, for the same reasons: grants are claimed
    `FOR UPDATE SKIP LOCKED` with `polled_at` advanced under the lock, so a tick
    that outruns its own minute cannot be double-claimed by the next; and each
    fire is submitted through `run_deployment` without being awaited, so one slow
    agent run never holds the tick open.

    **The cursor advances only after the fires are dispatched, in the same
    transaction.** In the other order a crash between the two loses every message
    the poll read - the cursor says they were handled and nothing handled them.
    Advancing after means a crash *re-reads* them, which the delivery-id claim then
    dedups: at-least-once, with the duplicate suppressed, rather than at-most-once
    with a silent hole.
    """
    from app.services.agent_trigger import AgentTriggerService
    from app.services.mcp_connection import McpConnectionService
    from app.services.portal_catalog import CATALOG, DeliveryMode

    polled_keys = [entry.key for entry in CATALOG if entry.delivery is DeliveryMode.POLLING]
    if not polled_keys:
        return
    dispatched = 0
    async with get_worker_db_context() as db:
        grants = await McpConnectionService(db).claim_grants_to_poll(portal_keys=polled_keys)
        for grant in grants:
            source = _polled_source(grant.portal_key)
            if source is None:
                continue
            read = await McpConnectionService(db).poll_grant(grant)
            if read is None:
                continue
            decisions = await AgentTriggerService(db).prepare_polled_fires(
                organization_id=grant.organization_id,
                event_source=source,
                events=read.events,
            )
            for decision in decisions:
                try:
                    await dispatch_trigger_fire(
                        str(decision.trigger_id), event_context=decision.event_context
                    )
                except Exception:
                    # Isolated like the scheduled loop's, and for the same reason: a
                    # transient Prefect error on one fire must not cost the rest of
                    # the batch theirs. The delivery claim is left standing - a
                    # submit that raised may still have enqueued the run.
                    logger.exception(
                        "portal_poll_dispatch_failed",
                        extra={"trigger_id": str(decision.trigger_id)},
                    )
                else:
                    dispatched += 1
            await McpConnectionService(db).store_poll_cursor(grant, cursor=read.cursor)
    logger.info("portal_poll", extra={"dispatched": dispatched})


@flow(name="sandbox-log-sweep", log_prints=True)
async def sweep_sandbox_operations_flow() -> None:
    """Drop sandbox operations older than the retention window.

    A sandbox is reaped half an hour after it goes idle and its files may be swept
    by the service's own TTL, so a log that outlived the answer to "what happened
    here" by years would be a growing table nobody reads. Daily rather than hourly:
    the window is thirty days, so the exact hour a row leaves is not a fact anybody
    depends on, and a delete over a month-old boundary is cheap when it runs once.
    """
    from datetime import timedelta

    from app.db.models.sandbox_operation import OPERATION_RETENTION_DAYS
    from app.repositories import sandbox_operation_repo

    cutoff = datetime.now(UTC) - timedelta(days=OPERATION_RETENTION_DAYS)
    async with get_worker_db_context() as db:
        removed = await sandbox_operation_repo.delete_older_than(db, cutoff=cutoff)
    logger.info("sandbox_log_swept", extra={"removed": removed, "days": OPERATION_RETENTION_DAYS})


def _polled_source(portal_key: str | None) -> str | None:
    """The `event_source` a portal's presets fire through, or `None` for no portal.

    Read off the catalog rather than assumed from the key, because they are not the
    same word: the portal is `google` and the source is `gmail`.
    """
    from app.services.portal_catalog import get_portal

    portal = None if portal_key is None else get_portal(portal_key)
    return None if portal is None else portal.event_source


@flow(name="run-scheduled-trigger", log_prints=True)
async def run_scheduled_trigger_flow(
    trigger_id: str, event_context: str | None = None, claimed_at: str | None = None
) -> None:
    """One fired run: run the agent this trigger fires, as its creator.

    Reached by the heartbeat with no `event_context` (a scheduled fire) and by an
    inbound event delivery with the rendered context (an event fire), so both kinds
    run in this one capped, isolated flow rather than the event kind running in the
    API process.

    `claimed_at` is the `fire_in_flight_since` the scheduled claim stamped,
    round-tripped as an ISO string and handed back to `fire` as this fire's claim
    ticket, so the marker is cleared only while it still belongs to this claim - a
    fire that outran the lease must not clear the marker a newer claim set. Only the
    scheduled path sets it; an event or manually triggered fire has none and leaves
    any marker for the lease.
    """
    from app.services.agent_trigger import AgentTriggerService

    parsed = None if claimed_at is None else datetime.fromisoformat(claimed_at)
    async with get_worker_db_context() as db:
        await AgentTriggerService(db).fire(
            UUID(trigger_id), event_context=event_context, claimed_at=parsed
        )
