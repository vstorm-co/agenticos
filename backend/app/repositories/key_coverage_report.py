"""Source coverage reports - one per agent and dataset."""

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import delete, func, select, type_coerce, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.context import ContextFile
from app.db.models.dataset import Dataset
from app.db.models.key_coverage_report import CoverageStatus, KeyCoverageReport
from app.db.models.mcp_connection import McpConnection
from app.db.models.rag_document import RAGDocument
from app.db.models.skill import Skill


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
        source_marks={},
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
    source_marks: Mapping[UUID, str] | None = None,
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
            source_marks={str(source): mark for source, mark in (source_marks or {}).items()},
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
    """The agent's complete ready reports over these datasets, for the versions current now.

    A report with a source it could not read cannot say that no source holds a key.

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
            KeyCoverageReport.unseen_sources == 0,
            Agent.id == agent_id,
        )
    )
    return list(result.all())


async def source_marks(
    db: AsyncSession, *, organization_id: UUID, source_ids: Collection[UUID]
) -> dict[UUID, str]:
    """What each of these sources holds now, as a mark that changes when it does.

    A knowledge base by how many documents it has and the newest change to one, so
    a removal counts as much as an addition; a context file or skill by its last
    edit; an MCP server by the tools it last listed - not by when it was last
    probed, which moves on every health check. One query per kind of source.
    """
    if not source_ids:
        return {}
    ids = list(source_ids)
    marks: dict[UUID, str] = {}
    documents = await db.execute(
        select(
            # `type_coerce` states what the `IN` guarantees and the nullable column cannot.
            type_coerce(RAGDocument.knowledge_base_id, PG_UUID(as_uuid=True)),
            func.count(RAGDocument.id),
            func.max(func.coalesce(RAGDocument.updated_at, RAGDocument.created_at)),
        )
        .where(
            RAGDocument.organization_id == organization_id,
            RAGDocument.knowledge_base_id.in_(ids),
        )
        .group_by(RAGDocument.knowledge_base_id)
    )
    for knowledge_base_id, count, newest in documents.all():
        marks[knowledge_base_id] = f"{count}:{newest.isoformat()}"
    for model in (ContextFile, Skill):
        edited = await db.execute(
            select(model.id, func.coalesce(model.updated_at, model.created_at)).where(
                model.organization_id == organization_id, model.id.in_(ids)
            )
        )
        marks.update((row_id, changed.isoformat()) for row_id, changed in edited.all())
    servers = await db.execute(
        select(McpConnection.id, McpConnection.last_tools).where(
            McpConnection.organization_id == organization_id, McpConnection.id.in_(ids)
        )
    )
    for server_id, tools in servers.all():
        listed = json.dumps(tools, sort_keys=True, default=str)
        marks[server_id] = hashlib.sha256(listed.encode()).hexdigest()
    return marks
