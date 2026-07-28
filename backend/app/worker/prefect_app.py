"""Prefect runner — starts a long-running server that hosts all flow deployments.

Run with:
    python -m app.worker.prefect_app

The process registers scheduled deployments with the Prefect server and polls for
work.  Set PREFECT_API_URL to http://prefect-server:4200/api (self-hosted Docker)
or to your Prefect Cloud workspace URL + PREFECT_API_KEY for Cloud mode.
"""

import asyncio
import logging
from datetime import timedelta

from prefect import aserve
from prefect.client.schemas.schedules import IntervalSchedule

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

logger = logging.getLogger(__name__)


async def main() -> None:
    """Register all deployments and serve them."""
    deployments = []
    # On-demand: triggered from API on file upload
    deployments.append(await ingest_document_flow.ato_deployment(name="ingest-document"))
    deployments.append(await sync_single_source_flow.ato_deployment(name="sync-single-source"))
    deployments.append(await sync_collection_flow.ato_deployment(name="sync-collection"))
    # Scheduled: check connector sources every minute
    deployments.append(
        await check_scheduled_syncs_flow.ato_deployment(
            name="rag-sync-check",
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
    # Usage reports. An interval rather than a cron because the schedule only
    # has to be *roughly* weekly — what matters is that the number arrives
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
    logger.info("Starting Prefect runner with %d deployments", len(deployments))
    await aserve(*deployments)


if __name__ == "__main__":
    asyncio.run(main())
