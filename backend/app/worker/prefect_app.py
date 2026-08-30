"""Prefect runner - starts a long-running server that hosts all flow deployments.

Run with:
    python -m app.worker.prefect_app

The process registers scheduled deployments with the Prefect server and polls for
work.  Set PREFECT_API_URL to http://prefect-server:4200/api (self-hosted Docker)
or to your Prefect Cloud workspace URL + PREFECT_API_KEY for Cloud mode.

At most PREFECT_RUNNER_LIMIT runs execute at once; the rest queue.  Each run is a
separate process that imports the whole application, so an uncapped runner meeting
a backlog is an out-of-memory kill rather than a slow afternoon.

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
from prefect.client.schemas.schedules import IntervalSchedule

from app.core.config import settings
from app.core.logging import setup_logging
from app.worker.tasks.approval_tasks import approval_expiry_sweep_flow
from app.worker.tasks.invitation_tasks import invitation_expiry_sweep_flow
from app.worker.tasks.mcp_tasks import mcp_connection_sweep_flow
from app.worker.tasks.rag_tasks import (
    check_scheduled_syncs_flow,
    ingest_document_flow,
    sync_collection_flow,
    sync_single_source_flow,
)
from app.worker.tasks.report_tasks import (
    monthly_usage_report_flow,
    weekly_usage_report_flow,
)
from app.worker.tasks.run_tasks import stale_run_sweep_flow
from app.worker.tasks.teardown_tasks import org_purge_cleanup_flow, teardown_sweep_flow
from app.worker.tasks.trigger_tasks import (
    check_agent_triggers_flow,
    poll_portal_grants_flow,
    run_scheduled_trigger_flow,
    sweep_sandbox_operations_flow,
)

logger = logging.getLogger(__name__)


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
    deployments.append(
        await check_scheduled_syncs_flow.ato_deployment(
            name="rag-sync-check",
            schedules=[IntervalSchedule(interval=60)],
        )
    )
    # On-demand: one fired run per due trigger, submitted by the heartbeat below.
    deployments.append(
        await run_scheduled_trigger_flow.ato_deployment(name="run-scheduled-trigger")
    )
    # On-demand: the external cleanup of a deleted org, submitted after its purge
    # commits so it survives the request process dying mid-cleanup (#1274).
    deployments.append(await org_purge_cleanup_flow.ato_deployment(name="org-purge-cleanup"))
    # Every 5 minutes: re-dispatch the teardowns nothing finished. The half
    # `spawn_after_commit` cannot cover - a process that died between the purge's
    # commit and the hand-off - because the intent row survives that and nothing
    # else would ever look at it (#1269). On a fleet with nothing outstanding
    # this is one indexed query returning no rows.
    deployments.append(
        await teardown_sweep_flow.ato_deployment(
            name="teardown-sweep",
            schedules=[IntervalSchedule(interval=300)],
        )
    )
    # Every minute: fire the agent triggers that have come due.
    deployments.append(
        await check_agent_triggers_flow.ato_deployment(
            name="agent-triggers-check",
            schedules=[IntervalSchedule(interval=60)],
        )
    )
    # Daily: drop sandbox operations past the retention window. The window is
    # thirty days, so the hour a row leaves is nobody's business - and a delete over
    # a month-old boundary is cheap when it runs once rather than hourly.
    deployments.append(
        await sweep_sandbox_operations_flow.ato_deployment(
            name="sandbox-log-sweep",
            schedules=[IntervalSchedule(interval=86400)],
        )
    )
    # Every minute: read the connected accounts nobody pushes to. A separate
    # deployment rather than work inside the trigger heartbeat, because the two
    # fail independently - a Gmail outage must not stop a cron schedule firing -
    # and because one tick of each is a different amount of work.
    deployments.append(
        await poll_portal_grants_flow.ato_deployment(
            name="portal-poll",
            schedules=[IntervalSchedule(interval=60)],
        )
    )
    # Every 15 minutes: often enough that a dead grant is noticed within one
    # coffee break, rare enough that a healthy fleet costs one query an hour
    # times four. Tokens are still refreshed on use; this is about finding the
    # ones that no longer can be.
    deployments.append(
        await mcp_connection_sweep_flow.ato_deployment(
            name="mcp-connection-sweep",
            schedules=[IntervalSchedule(interval=900)],
        )
    )
    # Hourly, against a threshold measured in days: precision here buys nothing,
    # and an approval expiring 40 minutes late has cost nobody anything. One
    # query an hour, which on the ordinary sweep returns no rows and stops.
    deployments.append(
        await approval_expiry_sweep_flow.ato_deployment(
            name="approval-expiry-sweep",
            schedules=[IntervalSchedule(interval=3600)],
        )
    )
    # Hourly for the same reason as the approval sweep: the invitation TTL is
    # measured in days, so an invitation expiring 40 minutes late costs nothing.
    deployments.append(
        await invitation_expiry_sweep_flow.ato_deployment(
            name="invitation-expiry-sweep",
            schedules=[IntervalSchedule(interval=3600)],
        )
    )
    # Hourly like the sweeps above, and for the same arithmetic: the ceiling is
    # measured in hours, so a crashed run reaped 40 minutes late costs nothing -
    # what matters is that it is reaped at all, because nothing else ever will.
    deployments.append(
        await stale_run_sweep_flow.ato_deployment(
            name="stale-run-sweep",
            schedules=[IntervalSchedule(interval=3600)],
        )
    )
    # Usage reports. An interval rather than a cron because the schedule only
    # has to be *roughly* weekly - what matters is that the number arrives
    # regularly, and an interval survives a restart without needing a timezone
    # decided for every deployment.
    deployments.append(
        await weekly_usage_report_flow.ato_deployment(
            name="weekly-usage-report",
            schedules=[IntervalSchedule(interval=timedelta(days=7))],
        )
    )
    deployments.append(
        await monthly_usage_report_flow.ato_deployment(
            name="monthly-usage-report",
            schedules=[IntervalSchedule(interval=timedelta(days=30))],
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
    await aserve(*deployments, limit=settings.PREFECT_RUNNER_LIMIT, webserver=True)


if __name__ == "__main__":
    asyncio.run(main())
