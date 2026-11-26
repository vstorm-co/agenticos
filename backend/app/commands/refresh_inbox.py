"""Explicit operator refresh of open generated Inbox proposals in one organization."""

import asyncio
from uuid import UUID

import click

from app.commands import command
from app.db.session import get_worker_db_context
from app.repositories import suggestion_repo
from app.services.proactive import ProactiveService


async def _refresh(organization_id: UUID, *, queue: bool) -> None:
    async with get_worker_db_context() as db:
        candidates = await suggestion_repo.open_generated_people(
            db, organization_id=organization_id
        )
        click.echo(
            f"{sum(candidates.values())} open generated proposals for {len(candidates)} people."
        )
        if not queue:
            click.echo(
                "Plan only. Add --queue to regenerate using the configured model and budgets."
            )
            return
        jobs = await ProactiveService(db).queue_open_refresh(organization_id)
        for job_id in jobs:
            click.echo(f"Queued {job_id}")


@command("refresh-inbox", help="Regenerate open proposals in one organization; defaults to a plan")
@click.option("--organization-id", type=click.UUID, required=True)
@click.option(
    "--queue", is_flag=True, help="Queue paid generation within existing organization budgets"
)
def refresh_inbox(organization_id: UUID, queue: bool) -> None:
    """Preserve decisions, findings and approvals; replace open proposals only after a valid reading."""
    asyncio.run(_refresh(organization_id, queue=queue))
