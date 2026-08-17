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


async def dispatch_trigger_fire(trigger_id: str, *, event_context: str | None = None) -> None:
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
    """
    # `run_deployment` is sync-compatible: its stub unions the coroutine it
    # returns in an async context with the `FlowRun` a sync caller gets, and ty
    # cannot tell which applies. Awaiting it is correct here.
    await run_deployment(  # ty: ignore[invalid-await]
        name=_RUN_TRIGGER_DEPLOYMENT,
        parameters={"trigger_id": trigger_id, "event_context": event_context},
        timeout=0,
    )


@flow(name="agent-triggers-check", log_prints=True)
async def check_agent_triggers_flow() -> None:
    """Heartbeat: claim the triggers due now and submit a run for each."""
    from app.services.agent_trigger import AgentTriggerService

    async with get_worker_db_context() as db:
        triggers = await AgentTriggerService(db).claim_and_advance(now=datetime.now(UTC))
    # Dispatched after the claim's transaction commits, so every submitted run
    # sees the advanced `next_fire_at` and the tick's own work is durable before
    # any of it is handed on.
    for trigger in triggers:
        await dispatch_trigger_fire(str(trigger.id))
    logger.info("agent_triggers_check", extra={"dispatched": len(triggers)})


@flow(name="run-scheduled-trigger", log_prints=True)
async def run_scheduled_trigger_flow(trigger_id: str, event_context: str | None = None) -> None:
    """One fired run: run the agent this trigger fires, as its creator.

    Reached by the heartbeat with no `event_context` (a scheduled fire) and by an
    inbound event delivery with the rendered context (an event fire), so both
    kinds run in this one capped, isolated flow rather than the event kind running
    in the API process.
    """
    from app.services.agent_trigger import AgentTriggerService

    async with get_worker_db_context() as db:
        await AgentTriggerService(db).fire(UUID(trigger_id), event_context=event_context)
