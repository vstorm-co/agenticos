"""Checking the MCP catalog: does every listed server still answer, and how (#2103).

Re-run before a release with `--snapshot`, so a fresh deployment starts from what
the release was checked against, and on a deployment whenever its catalog should
be re-checked. What a listing did is recorded per listing; the console marks the
ones that answered as checked and stops offering registry listings that did not.
"""

import asyncio
from pathlib import Path

import click

from app.commands import command, info, success, warning
from app.db.session import get_db_context
from app.services import mcp_audit
from app.services.mcp_audit import CheckRow, Source

_SOURCES: dict[str, frozenset[Source]] = {
    "all": frozenset({"catalog", "registry"}),
    "catalog": frozenset({"catalog"}),
    "registry": frozenset({"registry"}),
}


def _summary(rows: list[CheckRow]) -> str:
    counted: dict[str, int] = {}
    for row in rows:
        counted[row.outcome.value] = counted.get(row.outcome.value, 0) + 1
    return ", ".join(f"{outcome} {count}" for outcome, count in sorted(counted.items()))


@command(
    "mcp-catalog-check", help="Call every MCP server the catalog lists and record what answers"
)
@click.option(
    "--source",
    type=click.Choice(["all", "catalog", "registry"]),
    default="all",
    help="The curated catalog, the registry mirror, or both.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Call only the first N registry listings - a quick look, which prunes nothing.",
)
@click.option("--concurrency", type=click.IntRange(min=1, max=128), default=24, show_default=True)
@click.option("--timeout", type=click.FloatRange(min=1), default=10.0, show_default=True)
@click.option(
    "--report",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write a Markdown report here, and every row as JSON beside it.",
)
@click.option(
    "--snapshot",
    is_flag=True,
    help="Also write the bundled snapshot a fresh deployment is seeded with.",
)
def mcp_catalog_check(
    source: str,
    limit: int | None,
    concurrency: int,
    timeout: float,
    report: Path | None,
    snapshot: bool,
) -> None:
    """Call each listed server without a credential and record what it did.

    A full run (both sources, no limit) also forgets checks of listings no longer
    listed. Nothing here signs in anywhere: whether a server's tools work once
    connected is the connection's own test.
    """
    sources = _SOURCES[source]

    async def _run() -> list[CheckRow]:
        async with get_db_context() as db:
            rows = await mcp_audit.check_listings(
                db, sources=sources, limit=limit, concurrency=concurrency, timeout=timeout
            )
            await mcp_audit.write_checks(db, rows, prune=source == "all" and limit is None)
        return rows

    info("Calling the listed servers - several minutes for the whole registry...")
    rows = asyncio.run(_run())
    success(f"Checked {len(rows)} listings: {_summary(rows)}")

    if report is not None:
        report.write_text(mcp_audit.report_markdown(rows), encoding="utf-8")
        report.with_suffix(".json").write_text(mcp_audit.report_json(rows), encoding="utf-8")
        info(f"Report: {report} (and {report.with_suffix('.json').name})")
    if snapshot:
        if source != "all" or limit is not None:
            warning("A snapshot is written only from a full run; skipped.")
        else:
            info(f"Snapshot: {mcp_audit.write_snapshot(rows)}")
