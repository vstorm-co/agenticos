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


async def _dispatch(trigger_id: str) -> None:
    """Submit one due trigger's run as its own flow run, and return.

    `timeout=0` is what makes this submit-and-return: `run_deployment` enqueues
    the run and does not wait for it, so a tick's cost is one API call per due
    trigger rather than the sum of the runs it starts. A separate flow run is also
    what keeps each fired agent run capped by `PREFECT_RUNNER_LIMIT` and isolated
    from the heartbeat.
    """
    # `run_deployment` is sync-compatible: its stub unions the coroutine it
    # returns in an async context with the `FlowRun` a sync caller gets, and ty
    # cannot tell which applies. Awaiting it is correct here.
    await run_deployment(  # ty: ignore[invalid-await]
        name=_RUN_TRIGGER_DEPLOYMENT,
        parameters={"trigger_id": trigger_id},
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
    dispatched = 0
    for trigger in triggers:
        try:
            await _dispatch(str(trigger.id))
        except Exception:
            # The claims already committed, so a trigger whose dispatch fails has its
            # `next_fire_at` advanced with no run - a missed fire for that one trigger.
            # Isolate each dispatch so a single failed `run_deployment` (a transient
            # Prefect API error) does not abort the loop and cost the rest of the batch
            # their fire too; the failure is logged, and the next tick fires this
            # trigger again on its new schedule.
            logger.exception("agent_trigger_dispatch_failed", extra={"trigger_id": str(trigger.id)})
        else:
            dispatched += 1
    logger.info("agent_triggers_check", extra={"dispatched": dispatched, "claimed": len(triggers)})


@flow(name="run-scheduled-trigger", log_prints=True)
async def run_scheduled_trigger_flow(trigger_id: str) -> None:
    """One fired run: run the agent this trigger schedules, as its creator."""
    from app.services.agent_trigger import AgentTriggerService

    async with get_worker_db_context() as db:
        await AgentTriggerService(db).fire(UUID(trigger_id))
