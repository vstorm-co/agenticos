"""Prefect runner - starts a long-running server that hosts all flow deployments.

Run with:
    python -m app.worker.prefect_app

The process registers scheduled deployments with the Prefect server and polls for
work, and runs the minute-scale sweeps itself (`app/worker/sweeps.py`): as
deployments, each of their ticks was a process importing the whole application
(#2213).  Set PREFECT_API_URL to http://prefect-server:4200/api (self-hosted Docker)
or to your Prefect Cloud workspace URL + PREFECT_API_KEY for Cloud mode.

At most PREFECT_RUNNER_LIMIT runs execute at once; the rest queue.  Each run is a
separate process that imports the whole application, so an uncapped runner meeting
a backlog is an out-of-memory kill rather than a slow afternoon.  Scheduled
sweeps also run one tick at a time each, so a host that falls behind skips ticks
rather than running every one of them - see `_ONE_AT_A_TIME`.

The runner also serves its own health endpoint, so that a container orchestrator
can tell a runner that is polling from one that has stopped.  Where it listens is
Prefect's decision, not this module's - PREFECT_RUNNER_SERVER_HOST and
PREFECT_RUNNER_SERVER_PORT, `localhost:8080` unless something sets them, which
every compose file here does.  See `main` for why it is not optional.
"""

import asyncio
import logging
from datetime import timedelta

from prefect import aserve
from prefect.client.schemas.objects import ConcurrencyLimitConfig, ConcurrencyLimitStrategy
from prefect.client.schemas.schedules import IntervalSchedule

from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.logging import setup_logging
from app.services.sandbox_workspace import retry_pending_destroys
from app.worker.sweeps import Sweep, run_sweeps
from app.worker.tasks.approval_tasks import approval_expiry_sweep_flow
from app.worker.tasks.invitation_tasks import invitation_expiry_sweep_flow
from app.worker.tasks.mcp_tasks import mcp_connection_sweep_flow
from app.worker.tasks.notification_tasks import (
    deliver_due_notifications,
    notification_retention_sweep_flow,
)
from app.worker.tasks.rag_tasks import (
    check_scheduled_syncs_flow,
    dispatch_due_syncs,
    ingest_document_flow,
    retention_sweep_flow,
    sync_collection_flow,
    sync_single_source_flow,
)
from app.worker.tasks.report_tasks import (
    monthly_usage_report_flow,
    weekly_usage_report_flow,
)
from app.worker.tasks.run_tasks import stale_run_sweep_flow
from app.worker.tasks.teardown_tasks import (
    external_state_cleanup_flow,
    teardown_reservation_sweep_flow,
)
from app.worker.tasks.trigger_tasks import (
    check_agent_triggers,
    poll_portal_grants,
    run_scheduled_trigger_flow,
    sweep_sandbox_operations_flow,
)

logger = logging.getLogger(__name__)

SWEEPS = (
    # Fire the agent triggers that have come due.
    Sweep("agent-triggers-check", 60, check_agent_triggers),
    # Read the connected accounts nobody pushes to. Its own sweep rather than work
    # inside the trigger heartbeat: the two fail independently - a Gmail outage must
    # not stop a cron schedule firing - and one tick of each is a different amount
    # of work.
    Sweep("portal-poll", 60, poll_portal_grants),
    # Send queued notifications: a pending delivery waits at most one tick.
    Sweep("notification-delivery-sweep", 60, deliver_due_notifications),
    # Start the sync check when a source is due; the syncs stay a flow run.
    Sweep("rag-sync-check", 60, dispatch_due_syncs),
    # Destroy the remote sandboxes a deleted conversation or project left behind
    # (#2209). Each tombstone carries its own backoff, so most ticks find none due.
    Sweep("sandbox-destroy-retry", 60, retry_pending_destroys),
)
"""The minute-scale work, in this process - see `app/worker/sweeps.py`."""

RETIRED_DEPLOYMENTS = (
    "agent-triggers-check/agent-triggers-check",
    "portal-poll/portal-poll",
    "notification-delivery-sweep/notification-delivery-sweep",
)
"""The deployments `SWEEPS` replaced (#2213), by their "<flow>/<deployment>" handle."""

_UNSCHEDULED = ("rag-sync-check/rag-sync-check",)
"""Deployments that kept their name but lost their schedule when their sweep took it."""


async def retire_minute_deployments() -> None:
    """Remove what Prefect still schedules for the work `SWEEPS` now does.

    A deployment and its schedule live in Prefect's database, not in this code,
    and registering the deployments that remain does not touch the ones that do
    not: left there, the server would go on creating a run a minute for each that
    nothing serves - the Late backlog `SWEEPS` exists to end. Missing is fine;
    anything else is logged, and the worker starts regardless.
    """
    from prefect.client.orchestration import get_client
    from prefect.exceptions import ObjectNotFound

    async with get_client() as client:
        for name in RETIRED_DEPLOYMENTS + _UNSCHEDULED:
            try:
                deployment = await client.read_deployment_by_name(name)
                if name in RETIRED_DEPLOYMENTS:
                    await client.delete_deployment(deployment.id)
                    logger.info("retired_deployment", extra={"deployment": name})
                    continue
                for schedule in await client.read_deployment_schedules(deployment.id):
                    await client.delete_deployment_schedule(deployment.id, schedule.id)
            except ObjectNotFound:
                continue
            except Exception:
                logger.warning(
                    "retiring_deployment_failed", extra={"deployment": name}, exc_info=True
                )


# The scheduled sweeps here work over current state, so a tick that arrives
# while the previous one is still running has nothing of its own to do. Without
# a limit those ticks queue: on 2026-10-17 the production host fell behind, each
# queued tick was another process importing the application on a saturated CPU,
# which made every tick slower still, and ~1,650 Late runs had piled up eight
# hours later with the API's workers starved into restarts.
#
# `CANCEL_NEW` makes the server refuse the surplus tick at the move to Pending,
# which the runner proposes before it starts a process, so a refused tick costs
# one API call. While a tick holds the slot the server also cancels the next one
# at the move to Late. When the runner's own slots are full of other work, no
# tick holds the slot and Late ticks still collect; once the runner has room the
# first of them runs and the rest are refused the same way, without a process
# each. A run whose process died holds its slot only until its lease lapses
# (300s by default); the engine renews the lease while the run is alive.
_ONE_AT_A_TIME = ConcurrencyLimitConfig(
    limit=1, collision_strategy=ConcurrencyLimitStrategy.CANCEL_NEW
)


def _every(seconds: float) -> IntervalSchedule:
    """The interval a deployment declares, never faster than the configured floor.

    `WORKER_MIN_INTERVAL_SECONDS` is `0` on a deployment, so this is the
    declared interval and nothing else. It exists for the machine that is also
    running an editor: every run here is a separate Python process that imports
    the whole application - see the setting's own note for the measurement. The
    in-process sweeps (`SWEEPS`) do not take it: they import nothing per tick.

    A floor rather than a multiplier, so raising it lengthens only what is
    already faster than it: the daily sweeps stay daily whatever it is set to,
    which a multiplier would silently turn into weeks.
    """
    return IntervalSchedule(
        interval=timedelta(seconds=max(seconds, settings.WORKER_MIN_INTERVAL_SECONDS))
    )


async def main() -> None:
    """Register all deployments and serve them."""
    # The worker runs ingestion, syncs and reports - the code most likely to log a
    # connector 401 or an embedding-key failure - in a process that never set the
    # PII redaction up, so those lines reached the aggregator verbatim (#440).
    setup_logging()
    deployments = []
    deployments.append(await ingest_document_flow.ato_deployment(name="ingest-document"))
    deployments.append(await sync_single_source_flow.ato_deployment(name="sync-single-source"))
    deployments.append(await sync_collection_flow.ato_deployment(name="sync-collection"))
    # On-demand: started by the `rag-sync-check` sweep when a source is due. One at
    # a time, so a sweep that comes round while the last batch still syncs is
    # refused rather than starting a second.
    deployments.append(
        await check_scheduled_syncs_flow.ato_deployment(
            name="rag-sync-check", concurrency_limit=_ONE_AT_A_TIME
        )
    )
    # On-demand: one fired run per due trigger, submitted by the trigger sweep.
    deployments.append(
        await run_scheduled_trigger_flow.ato_deployment(name="run-scheduled-trigger")
    )
    # On-demand: the external cleanup a committed delete leaves - a purged org's
    # tables and files (#1274), a dropped RAG collection's (#1349) - submitted after
    # the delete commits so it survives the request process dying mid-cleanup. The
    # deployment name stays `org-purge-cleanup` (its #1274 name) so an upgrade does
    # not strand runs queued under the old identifier; the flow it serves is general.
    deployments.append(await external_state_cleanup_flow.ato_deployment(name="org-purge-cleanup"))
    # Daily: drop sandbox operations past the retention window. The window is
    # thirty days, so the hour a row leaves is nobody's business - and a delete over
    # a month-old boundary is cheap when it runs once rather than hourly.
    deployments.append(
        await sweep_sandbox_operations_flow.ato_deployment(
            name="sandbox-log-sweep",
            schedules=[_every(86400)],
            concurrency_limit=_ONE_AT_A_TIME,
        )
    )
    # Every 15 minutes: often enough that a dead grant is noticed within one
    # coffee break, rare enough that a healthy fleet costs one query an hour
    # times four. Tokens are still refreshed on use; this is about finding the
    # ones that no longer can be.
    deployments.append(
        await mcp_connection_sweep_flow.ato_deployment(
            name="mcp-connection-sweep",
            schedules=[_every(900)],
            concurrency_limit=_ONE_AT_A_TIME,
        )
    )
    # Hourly, against a threshold measured in days: precision here buys nothing,
    # and an approval expiring 40 minutes late has cost nobody anything. One
    # query an hour, which on the ordinary sweep returns no rows and stops.
    deployments.append(
        await approval_expiry_sweep_flow.ato_deployment(
            name="approval-expiry-sweep",
            schedules=[_every(3600)],
            concurrency_limit=_ONE_AT_A_TIME,
        )
    )
    # Hourly for the same reason as the approval sweep: the invitation TTL is
    # measured in days, so an invitation expiring 40 minutes late costs nothing.
    deployments.append(
        await invitation_expiry_sweep_flow.ato_deployment(
            name="invitation-expiry-sweep",
            schedules=[_every(3600)],
            concurrency_limit=_ONE_AT_A_TIME,
        )
    )
    # Hourly like the sweeps above, and for the same arithmetic: the ceiling is
    # measured in hours, so a crashed run reaped 40 minutes late costs nothing -
    # what matters is that it is reaped at all, because nothing else ever will.
    deployments.append(
        await stale_run_sweep_flow.ato_deployment(
            name="stale-run-sweep",
            schedules=[_every(3600)],
            concurrency_limit=_ONE_AT_A_TIME,
        )
    )
    # Hourly, against a threshold measured in hours: a teardown reservation whose
    # durable drop was lost to the commit-to-dispatch gap - or failed for good -
    # blocks its collection name with nothing left to reattempt it. This reaps them,
    # dropping the table and freeing the name (#1364).
    deployments.append(
        await teardown_reservation_sweep_flow.ato_deployment(
            name="teardown-reservation-sweep",
            schedules=[_every(3600)],
            concurrency_limit=_ONE_AT_A_TIME,
        )
    )
    # Daily: apply every organization's retention policy. Every period is
    # measured in days, so the hour a row leaves is nobody's business, and an
    # hourly sweep would ask every tenant the same question twenty-four times
    # for one answer. It works a backlog off over several days rather than
    # blocking the runner for an hour on the first pass (#1420).
    deployments.append(
        await retention_sweep_flow.ato_deployment(
            name="retention-sweep",
            schedules=[_every(86400)],
            concurrency_limit=_ONE_AT_A_TIME,
        )
    )
    # Usage reports. An interval rather than a cron because the schedule only
    # has to be *roughly* weekly - what matters is that the number arrives
    # regularly, and an interval survives a restart without needing a timezone
    # decided for every deployment.
    #
    # No `_ONE_AT_A_TIME` here: a report covers the period its run's scheduled
    # time names, so a tick cancelled for overlapping would be a week or a month
    # nobody is ever sent.
    deployments.append(
        await weekly_usage_report_flow.ato_deployment(
            name="weekly-usage-report",
            schedules=[_every(7 * 86_400)],
        )
    )
    deployments.append(
        await monthly_usage_report_flow.ato_deployment(
            name="monthly-usage-report",
            schedules=[_every(30 * 86_400)],
        )
    )
    # Daily, matching the sandbox-log sweep above: drop notifications past their
    # retention window. Read ones age out in ninety days; anything, read or
    # not, ages out in a year. `announcements` themselves are untouched - only
    # the per-recipient deliveries a broadcast fanned out to.
    deployments.append(
        await notification_retention_sweep_flow.ato_deployment(
            name="notification-retention-sweep",
            schedules=[_every(86400)],
            concurrency_limit=_ONE_AT_A_TIME,
        )
    )
    logger.info(
        "Starting Prefect runner with %d deployments, at most %d run(s) at once",
        len(deployments),
        settings.PREFECT_RUNNER_LIMIT,
    )
    # `limit` is not optional in practice. `aserve` declares it `Optional[int] = None`
    # and hands that straight to `Runner(limit=...)`, where `None` means *no cap* -
    # whereas constructing a `Runner` without the argument would fall back to
    # Prefect's own default of five. So calling `aserve` and saying nothing is how
    # this runner ended up with no ceiling at all: after three days of downtime it
    # picked up the backlog of `rag-sync-check` runs and started 71 processes at
    # once, 6 GiB on a 7.75 GiB host, and the kernel OOM-killed the API container.
    #
    # `webserver` is what makes this container's health status mean something.
    # It starts Prefect's runner webserver on a daemon thread, serving `/health`
    # on PREFECT_RUNNER_SERVER_HOST:PREFECT_RUNNER_SERVER_PORT - the compose files
    # pin those to 127.0.0.1:8080, reachable by a probe inside the container and by
    # nothing else, which matters because the same server also exposes `/shutdown`.
    # The endpoint answers 503 once `last_polled` is older than
    # PREFECT_RUNNER_SERVER_MISSED_POLLS_TOLERANCE * PREFECT_RUNNER_POLL_FREQUENCY
    # (20s by default), so a process that is alive but no longer polling reads as
    # unhealthy rather than as fine. Before this, the runner inherited the API's
    # HTTP probe from the shared image and was unhealthy from the second it
    # started, which is a status nobody can act on.
    await retire_minute_deployments()
    redis = RedisClient()
    await redis.connect()
    try:
        async with asyncio.TaskGroup() as group:
            sweeping = group.create_task(run_sweeps(SWEEPS, redis))
            await aserve(*deployments, limit=settings.PREFECT_RUNNER_LIMIT, webserver=True)
            # The runner stopped - through its `/shutdown` endpoint, say - so nothing
            # would run what the sweeps submit: they stop with it, and the process exits.
            sweeping.cancel()
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
