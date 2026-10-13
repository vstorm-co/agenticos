"""Knowledge gap repository (PostgreSQL async): recorded searches and their topics."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge_gap import KnowledgeSearch
from app.schemas.knowledge_gap import KnowledgeSearchRecord


async def record_searches(
    db: AsyncSession,
    records: Sequence[KnowledgeSearchRecord],
    *,
    organization_id: UUID,
    run_id: UUID,
    conversation_id: UUID | None,
) -> None:
    """Insert a run's searches in one statement."""
    if not records:
        return
    await db.execute(
        insert(KnowledgeSearch),
        [
            {
                "organization_id": organization_id,
                "run_id": run_id,
                "conversation_id": conversation_id,
                "agent_id": record.agent_id,
                "knowledge_base_ids": list(record.knowledge_base_ids),
                "query": record.query,
                "result_count": record.result_count,
                "top_similarity": record.top_similarity,
            }
            for record in records
        ],
    )
