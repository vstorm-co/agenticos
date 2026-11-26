"""Judging which of a dataset's keys an agent's sources cover - one job per report.

The report searches every knowledge base the agent binds for every key label
before the source coverage agent reads the results, which takes longer than a
request may wait (:mod:`app.services.key_coverage`).
"""

from app.worker.jobs import ReportKeyCoverage


async def report_key_coverage(job: ReportKeyCoverage) -> None:
    """Judge the report's keys against the agent's published sources."""
    from app.services.key_coverage import report_key_coverage as judge

    await judge(job.report_id, job.organization_id)


async def settle_lost_report(job: ReportKeyCoverage, reason: str) -> None:
    """A report whose job ended for good without the handler ending it."""
    del reason
    from app.services.key_coverage import settle_lost

    await settle_lost(job.report_id, job.organization_id)
