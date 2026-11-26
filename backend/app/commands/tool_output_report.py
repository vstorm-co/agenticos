"""Estimate how much of an organization's model input is tool output sent again.

Read-only: it measures stored tool results and run manifests and prints sizes,
counts and estimates, never a result's or a request's content.

Example:
    agenticos cmd tool-output-report --org 5f2b... --from 2026-11-01 --to 2026-11-22
    agenticos cmd tool-output-report --org 5f2b... --from 2026-11-01 --to 2026-11-22 --json
"""

import asyncio
import json
from datetime import date, datetime
from uuid import UUID

import click

from app.commands import command
from app.core.exceptions import AppException
from app.db.session import get_db_context
from app.services.tool_output_report import (
    ToolOutputReport,
    ToolOutputReportService,
    as_json,
    render_text,
)

_DATE = click.DateTime(formats=["%Y-%m-%d"])


@command(
    "tool-output-report",
    help="Estimate how much of one organization's model input is tool output sent again",
)
@click.option(
    "--org", "organization_id", type=click.UUID, required=True, help="The organization to measure"
)
@click.option(
    "--from", "started_from", type=_DATE, required=True, help="First day of runs, YYYY-MM-DD"
)
@click.option("--to", "ended", type=_DATE, required=True, help="Last day of runs, YYYY-MM-DD")
@click.option("--include-eval", is_flag=True, help="Count eval runs too")
@click.option("--include-tests", is_flag=True, help="Count Builder test runs too")
@click.option(
    "--top",
    type=click.IntRange(min=1),
    default=20,
    show_default=True,
    help="How many agents, capabilities and tools each size table lists",
)
@click.option("--json", "as_json_output", is_flag=True, help="Print the figures as JSON")
def tool_output_report(
    organization_id: UUID,
    started_from: datetime,
    ended: datetime,
    include_eval: bool,
    include_tests: bool,
    top: int,
    as_json_output: bool,
) -> None:
    """Report result sizes, requests per run and the re-sent share, per agent."""
    try:
        report = asyncio.run(
            _build(
                organization_id,
                started_from=started_from.date(),
                ended=ended.date(),
                include_eval=include_eval,
                include_tests=include_tests,
                top=top,
            )
        )
    except AppException as exc:
        raise click.ClickException(exc.message) from exc
    click.echo(json.dumps(as_json(report), indent=2) if as_json_output else render_text(report))


async def _build(
    organization_id: UUID,
    *,
    started_from: date,
    ended: date,
    include_eval: bool,
    include_tests: bool,
    top: int,
) -> ToolOutputReport:
    async with get_db_context() as db:
        return await ToolOutputReportService(db).build(
            organization_id,
            started_from=started_from,
            ended=ended,
            include_eval=include_eval,
            include_tests=include_tests,
            top=top,
        )
