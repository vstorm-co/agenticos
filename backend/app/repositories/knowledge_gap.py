"""Knowledge gap repository (PostgreSQL async): recorded searches and their topics.

A *miss* is a search that returned nothing, or whose best passage was less
similar to the query than the threshold the caller passes. The threshold is a
setting rather than stored, so changing it reclassifies the searches already
made.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    ScalarSelect,
    SQLColumnExpression,
    Text,
    and_,
    any_,
    delete,
    distinct,
    exists,
    func,
    insert,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Message, ToolCall
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import KnowledgeGapMember, KnowledgeGapTopic, KnowledgeSearch
from app.db.models.message_rating import MessageRating
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


class TopicRow(NamedTuple):
    """A topic and what its searches add up to under the filters it was read with."""

    topic: KnowledgeGapTopic
    question_count: int
    last_asked_at: datetime
    queries: list[str]
    agent_ids: list[UUID]


class QuestionRow(NamedTuple):
    search: KnowledgeSearch
    question: str | None
    answer_message_id: UUID | None
    down_rating_comment: str | None


_EXAMPLE_POOL = 12
"""How many of a topic's oldest queries are read to pick its examples from."""


def _members(
    *, organization_id: UUID, threshold: float, agent_id: UUID | None
) -> list[ColumnElement[bool]]:
    """The searches a topic is reported with: this organization's, still misses, by `agent_id`."""
    conditions = [KnowledgeSearch.organization_id == organization_id, is_miss(threshold)]
    if agent_id is not None:
        conditions.append(KnowledgeSearch.agent_id == agent_id)
    return conditions


async def list_topics(
    db: AsyncSession,
    *,
    organization_id: UUID,
    knowledge_base_ids: Sequence[UUID],
    threshold: float,
    status: str | None,
    agent_id: UUID | None,
    skip: int,
    limit: int,
    topic_id: UUID | None = None,
) -> tuple[list[TopicRow], int]:
    """Topics of these knowledge bases, the most asked first, with how many there are."""
    question_count = func.count(KnowledgeSearch.id)
    last_asked_at = func.max(KnowledgeSearch.created_at)
    grouped = (
        select(
            KnowledgeGapTopic,
            question_count.label("question_count"),
            last_asked_at.label("last_asked_at"),
            func.array_agg(
                aggregate_order_by(KnowledgeSearch.query, KnowledgeSearch.created_at),
                type_=ARRAY(Text),
            )[1:_EXAMPLE_POOL].label("queries"),
            func.array_agg(distinct(KnowledgeSearch.agent_id), type_=ARRAY(PG_UUID())).label(
                "agent_ids"
            ),
        )
        .join(KnowledgeGapMember, KnowledgeGapMember.topic_id == KnowledgeGapTopic.id)
        .join(KnowledgeSearch, KnowledgeSearch.id == KnowledgeGapMember.search_id)
        .where(
            KnowledgeGapTopic.organization_id == organization_id,
            KnowledgeGapTopic.knowledge_base_id.in_(list(knowledge_base_ids)),
            *_members(organization_id=organization_id, threshold=threshold, agent_id=agent_id),
        )
        .group_by(KnowledgeGapTopic.id)
    )
    if status is not None:
        grouped = grouped.where(KnowledgeGapTopic.status == status)
    if topic_id is not None:
        grouped = grouped.where(KnowledgeGapTopic.id == topic_id)
    total = (await db.execute(select(func.count()).select_from(grouped.subquery()))).scalar_one()
    result = await db.execute(
        grouped.order_by(question_count.desc(), last_asked_at.desc(), KnowledgeGapTopic.id)
        .offset(skip)
        .limit(limit)
    )
    return [
        TopicRow(
            topic=row[0],
            question_count=row[1],
            last_asked_at=row[2],
            queries=list(row[3] or []),
            agent_ids=[agent for agent in row[4] or [] if agent is not None],
        )
        for row in result.all()
    ], total


async def count_ungrouped(
    db: AsyncSession,
    *,
    organization_id: UUID,
    knowledge_base_ids: Sequence[UUID],
    threshold: float,
    agent_id: UUID | None,
) -> int:
    """Misses in these knowledge bases that the next grouping pass has still to place."""
    if not knowledge_base_ids:
        return 0
    result = await db.execute(
        select(func.count(KnowledgeSearch.id)).where(
            *_members(organization_id=organization_id, threshold=threshold, agent_id=agent_id),
            or_(*(_ungrouped_in(kb_id) for kb_id in knowledge_base_ids)),
        )
    )
    return result.scalar_one()


async def get_topic(
    db: AsyncSession, topic_id: UUID, *, organization_id: UUID
) -> KnowledgeGapTopic | None:
    result = await db.execute(
        select(KnowledgeGapTopic).where(
            KnowledgeGapTopic.id == topic_id, KnowledgeGapTopic.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


def _answer_of(run_id: SQLColumnExpression[UUID]) -> ScalarSelect[UUID]:
    return (
        select(Message.id)
        .where(Message.run_id == run_id, Message.role == "assistant")
        .order_by(Message.ordinal.desc())
        .limit(1)
        .scalar_subquery()
    )


async def list_questions(
    db: AsyncSession,
    topic_id: UUID,
    *,
    organization_id: UUID,
    threshold: float,
    agent_id: UUID | None,
    limit: int,
) -> list[QuestionRow]:
    """A topic's searches, newest first, each with what the person asked and the answer.

    The question and the answer are read from the run's own turns, so a run
    with no conversation - the HTTP API - has neither.
    """
    question = (
        select(Message.content)
        .where(Message.run_id == KnowledgeSearch.run_id, Message.role == "user")
        .order_by(Message.ordinal)
        .limit(1)
        .scalar_subquery()
    )
    comment = (
        select(MessageRating.comment)
        .join(Message, Message.id == MessageRating.message_id)
        .where(
            Message.run_id == KnowledgeSearch.run_id,
            Message.role == "assistant",
            MessageRating.rating == -1,
            MessageRating.comment.is_not(None),
        )
        .order_by(MessageRating.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(KnowledgeSearch, question, _answer_of(KnowledgeSearch.run_id), comment)
        .join(KnowledgeGapMember, KnowledgeGapMember.search_id == KnowledgeSearch.id)
        .where(
            KnowledgeGapMember.topic_id == topic_id,
            *_members(organization_id=organization_id, threshold=threshold, agent_id=agent_id),
        )
        .order_by(KnowledgeSearch.created_at.desc(), KnowledgeSearch.id)
        .limit(limit)
    )
    return [
        QuestionRow(
            search=row[0], question=row[1], answer_message_id=row[2], down_rating_comment=row[3]
        )
        for row in result.all()
    ]


async def knowledge_bases_with_topics(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID | None
) -> list[UUID]:
    """The knowledge bases holding a topic - one this agent's searches are in, when named."""
    query = (
        select(distinct(KnowledgeGapTopic.knowledge_base_id))
        .join(KnowledgeGapMember, KnowledgeGapMember.topic_id == KnowledgeGapTopic.id)
        .join(KnowledgeSearch, KnowledgeSearch.id == KnowledgeGapMember.search_id)
        .where(KnowledgeGapTopic.organization_id == organization_id)
    )
    if agent_id is not None:
        query = query.where(KnowledgeSearch.agent_id == agent_id)
    result = await db.execute(query)
    return list(result.scalars().all())


class DraftingRow(NamedTuple):
    """One question as a drafting model is shown it."""

    search: KnowledgeSearch
    question: str | None
    answer: str | None
    found: str | None
    down_rating_comment: str | None


async def drafting_material(
    db: AsyncSession,
    topic_id: UUID,
    *,
    organization_id: UUID,
    threshold: float,
    limit: int,
) -> list[DraftingRow]:
    """A topic's newest questions with the answer each got and what its search returned.

    What the search returned is read back from the transcript's tool call, so a
    run with no conversation contributes its query alone.
    """
    rows = await list_questions(
        db,
        topic_id,
        organization_id=organization_id,
        threshold=threshold,
        agent_id=None,
        limit=limit,
    )
    answer_ids = [row.answer_message_id for row in rows if row.answer_message_id]
    answers: dict[UUID, str] = {}
    if answer_ids:
        result = await db.execute(
            select(Message.id, Message.content).where(Message.id.in_(answer_ids))
        )
        answers = {row[0]: row[1] for row in result.all()}
    found: dict[UUID, str] = {}
    run_ids = [row.search.run_id for row in rows]
    if run_ids:
        result = await db.execute(
            select(Message.run_id, ToolCall.args["query"].astext, ToolCall.result)
            .join(Message, Message.id == ToolCall.message_id)
            .where(Message.run_id.in_(run_ids), ToolCall.result.is_not(None))
        )
        by_query = {(row[0], row[1]): row[2] for row in result.all()}
        found = {
            row.search.id: by_query[(row.search.run_id, row.search.query)]
            for row in rows
            if (row.search.run_id, row.search.query) in by_query
        }
    return [
        DraftingRow(
            search=row.search,
            question=row.question,
            answer=answers.get(row.answer_message_id) if row.answer_message_id else None,
            found=found.get(row.search.id),
            down_rating_comment=row.down_rating_comment,
        )
        for row in rows
    ]


async def member_search_ids(
    db: AsyncSession, topic_id: UUID, *, organization_id: UUID
) -> set[UUID]:
    result = await db.execute(
        select(KnowledgeGapMember.search_id)
        .join(KnowledgeSearch, KnowledgeSearch.id == KnowledgeGapMember.search_id)
        .where(
            KnowledgeGapMember.topic_id == topic_id,
            KnowledgeSearch.organization_id == organization_id,
        )
    )
    return set(result.scalars().all())
