"""Knowledge gap repository (PostgreSQL async): recorded searches and their topics.

A *miss* is a search that returned nothing, or whose best passage was less
similar to the query than the threshold the caller passes. The threshold is a
setting rather than stored, so changing it reclassifies the searches already
made.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    SQLColumnExpression,
    and_,
    any_,
    delete,
    exists,
    func,
    insert,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import KnowledgeGapMember, KnowledgeGapTopic, KnowledgeSearch
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


def is_miss(threshold: float) -> ColumnElement[bool]:
    """The searches that found nothing close enough to the query."""
    return or_(KnowledgeSearch.result_count == 0, KnowledgeSearch.top_similarity < threshold)


def _ungrouped_in(knowledge_base_id: UUID | SQLColumnExpression[UUID]) -> ColumnElement[bool]:
    """Searched `knowledge_base_id`, and not yet a member of any of its topics."""
    return and_(
        any_(KnowledgeSearch.knowledge_base_ids) == knowledge_base_id,
        ~exists(
            select(KnowledgeGapMember.search_id)
            .join(KnowledgeGapTopic, KnowledgeGapTopic.id == KnowledgeGapMember.topic_id)
            .where(
                KnowledgeGapMember.search_id == KnowledgeSearch.id,
                KnowledgeGapTopic.knowledge_base_id == knowledge_base_id,
            )
        ),
    )


async def knowledge_bases_with_ungrouped_misses(
    db: AsyncSession, *, threshold: float
) -> list[tuple[UUID, UUID]]:
    """Every `(organization, knowledge base)` holding a miss no topic has taken yet.

    Unscoped by organization on purpose: the grouping pass runs for the whole
    deployment and then works each pair under its own organization. The
    knowledge base is matched within the search's organization, so an id that
    another organization's base happens to carry is never paired with it.
    """
    result = await db.execute(
        select(KnowledgeSearch.organization_id, KnowledgeBase.id)
        .join(
            KnowledgeBase,
            and_(
                KnowledgeBase.id == any_(KnowledgeSearch.knowledge_base_ids),
                KnowledgeBase.organization_id == KnowledgeSearch.organization_id,
            ),
        )
        .where(is_miss(threshold), _ungrouped_in(KnowledgeBase.id))
        .distinct()
        .order_by(KnowledgeSearch.organization_id, KnowledgeBase.id)
    )
    return [(row[0], row[1]) for row in result.all()]


async def ungrouped_misses(
    db: AsyncSession,
    knowledge_base_id: UUID,
    *,
    organization_id: UUID,
    threshold: float,
    limit: int,
) -> list[KnowledgeSearch]:
    """The oldest misses in a knowledge base that no topic of it has taken yet."""
    result = await db.execute(
        select(KnowledgeSearch)
        .where(
            KnowledgeSearch.organization_id == organization_id,
            is_miss(threshold),
            _ungrouped_in(knowledge_base_id),
        )
        .order_by(KnowledgeSearch.created_at, KnowledgeSearch.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def topics_in_space(
    db: AsyncSession, knowledge_base_id: UUID, *, organization_id: UUID, embedding_model: str
) -> list[tuple[KnowledgeGapTopic, int]]:
    """A knowledge base's topics on one embedding model, each with how many searches it holds."""
    members = (
        select(func.count())
        .select_from(KnowledgeGapMember)
        .where(KnowledgeGapMember.topic_id == KnowledgeGapTopic.id)
        .scalar_subquery()
    )
    result = await db.execute(
        select(KnowledgeGapTopic, members).where(
            KnowledgeGapTopic.organization_id == organization_id,
            KnowledgeGapTopic.knowledge_base_id == knowledge_base_id,
            KnowledgeGapTopic.embedding_model == embedding_model,
        )
    )
    return [(row[0], row[1]) for row in result.all()]


async def create_topic(
    db: AsyncSession,
    *,
    organization_id: UUID,
    knowledge_base_id: UUID,
    centroid: list[float],
    embedding_model: str,
) -> KnowledgeGapTopic:
    topic = KnowledgeGapTopic(
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        centroid=centroid,
        embedding_model=embedding_model,
    )
    db.add(topic)
    await db.flush()
    await db.refresh(topic)
    return topic


async def add_members(db: AsyncSession, placements: Sequence[tuple[UUID, UUID]]) -> None:
    """Put each `(topic, search)` pair into its topic."""
    if placements:
        await db.execute(
            insert(KnowledgeGapMember),
            [{"topic_id": topic, "search_id": search} for topic, search in placements],
        )


async def update_topic(
    db: AsyncSession, *, topic: KnowledgeGapTopic, update_data: dict[str, Any]
) -> KnowledgeGapTopic:
    for field, value in update_data.items():
        setattr(topic, field, value)
    await db.flush()
    await db.refresh(topic)
    return topic


async def delete_empty_topics(db: AsyncSession) -> int:
    """Remove every topic whose searches have all gone with their run or conversation.

    Unscoped by organization on purpose: a topic copies no text, so one with no
    searches left says nothing and belongs to nobody's view, in any organization.
    """
    result = await db.execute(
        delete(KnowledgeGapTopic).where(
            ~exists(
                select(KnowledgeGapMember.search_id).where(
                    KnowledgeGapMember.topic_id == KnowledgeGapTopic.id
                )
            )
        )
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]
