"""Source coverage reports - one per agent and dataset."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.dataset import Dataset
from app.db.models.key_coverage_report import CoverageStatus, KeyCoverageReport


async def get_for(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, dataset_id: UUID
) -> KeyCoverageReport | None:
    return await db.scalar(
        select(KeyCoverageReport).where(
            KeyCoverageReport.organization_id == organization_id,
            KeyCoverageReport.agent_id == agent_id,
            KeyCoverageReport.dataset_id == dataset_id,
        )
    )


async def get(
    db: AsyncSession, report_id: UUID, *, organization_id: UUID
) -> KeyCoverageReport | None:
    return await db.scalar(
        select(KeyCoverageReport).where(
            KeyCoverageReport.id == report_id,
            KeyCoverageReport.organization_id == organization_id,
        )
    )


async def replace(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID,
    dataset_id: UUID,
    dataset_version: int,
    requested_by_user_id: UUID | None,
    created_by_api_key_id: UUID | None,
) -> KeyCoverageReport:
    """A new running report for an agent and dataset, in place of the one they had."""
    await db.execute(
        delete(KeyCoverageReport).where(
            KeyCoverageReport.organization_id == organization_id,
            KeyCoverageReport.agent_id == agent_id,
            KeyCoverageReport.dataset_id == dataset_id,
        )
    )
    report = KeyCoverageReport(
        organization_id=organization_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        requested_by_user_id=requested_by_user_id,
        created_by_api_key_id=created_by_api_key_id,
        status=CoverageStatus.RUNNING.value,
        items=[],
        unseen_sources=0,
        judged_sources=[],
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)
    return report


async def finish(
    db: AsyncSession,
    report_id: UUID,
    *,
    organization_id: UUID,
    status: CoverageStatus,
    finished_at: datetime,
    items: Sequence[dict[str, JsonValue]] = (),
    unseen_sources: int = 0,
    judged_sources: Sequence[UUID] = (),
    error: str | None = None,
    run_id: UUID | None = None,
) -> bool:
    """End a report that is still running. Answers whether it was.

    A report replaced while its job ran is gone, and the job's verdicts with it.
    """
    ended = await db.scalar(
        update(KeyCoverageReport)
        .where(
            KeyCoverageReport.id == report_id,
            KeyCoverageReport.organization_id == organization_id,
            KeyCoverageReport.status == CoverageStatus.RUNNING.value,
        )
        .values(
            status=status.value,
            items=list(items),
            unseen_sources=unseen_sources,
            judged_sources=[str(source) for source in judged_sources],
            error=error,
            run_id=run_id,
            finished_at=finished_at,
        )
        .returning(KeyCoverageReport.id)
    )
    await db.flush()
    return ended is not None


async def ready_for_agent(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, dataset_ids: Sequence[UUID]
) -> list[KeyCoverageReport]:
    """The agent's ready reports over these datasets, made for the versions current now.

    A report on an earlier agent version judged sources the agent may since have
    gained, and one on an earlier dataset version keys the dataset may since have changed.
    """
    if not dataset_ids:
        return []
    result = await db.scalars(
        select(KeyCoverageReport)
        .join(Agent, Agent.current_version_id == KeyCoverageReport.agent_version_id)
        .join(
            Dataset,
            (Dataset.id == KeyCoverageReport.dataset_id)
            & (Dataset.latest_version == KeyCoverageReport.dataset_version),
        )
        .where(
            KeyCoverageReport.organization_id == organization_id,
            KeyCoverageReport.agent_id == agent_id,
            KeyCoverageReport.dataset_id.in_(dataset_ids),
            KeyCoverageReport.status == CoverageStatus.READY.value,
            Agent.id == agent_id,
        )
    )
    return list(result.all())
