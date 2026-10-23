"""Knowledge gap repository (PostgreSQL async): recorded searches and their topics.

A *miss* is a search that returned nothing, or whose best passage was less
similar to the query than the threshold the caller passes. The threshold is a
setting rather than stored, so changing it reclassifies the searches already
made.
"""

from collections.abc import Mapping, Sequence
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
    case,
    cast,
    delete,
    distinct,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.agent import AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Message, ToolCall
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import (
    GapSignal,
    KnowledgeGapClassification,
    KnowledgeGapMember,
    KnowledgeGapTopic,
    KnowledgeSearch,
    TopicStatus,
)
from app.db.models.message_rating import MessageRating
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.schemas.knowledge_gap import KnowledgeSearchRecord

REFUSED = "refused"
"""The verdict on an answer that rightly refused a request outside the agent's rules."""


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
    """The searches that found nothing close enough to the query, and the answers read as misses.

    Neither counts in a run whose answer a model read as a rightful refusal of
    a request outside the agent's rules, in a knowledge base it searched: the
    question was not one any content should answer.
    """
    answered = aliased(Message)
    refused = exists().where(
        KnowledgeGapClassification.signal == REFUSED,
        KnowledgeGapClassification.knowledge_base_id == any_(KnowledgeSearch.knowledge_base_ids),
        answered.id == KnowledgeGapClassification.message_id,
        answered.run_id == KnowledgeSearch.run_id,
    )
    return and_(
        or_(
            KnowledgeSearch.signal != GapSignal.RETRIEVAL.value,
            KnowledgeSearch.result_count == 0,
            KnowledgeSearch.top_similarity < threshold,
        ),
        ~refused,
    )


def _status() -> ColumnElement[str]:
    """A topic's status, reading a covered topic as open again once its document is gone,
    or failed to ingest - nothing of it can be retrieved then. A retry that succeeds
    covers it again."""
    failed = exists().where(
        RAGDocument.id == KnowledgeGapTopic.covered_by_document_id,
        RAGDocument.status == DocumentStatus.ERROR.value,
    )
    return case(
        (
            and_(
                KnowledgeGapTopic.status == TopicStatus.COVERED.value,
                or_(KnowledgeGapTopic.covered_by_document_id.is_(None), failed),
            ),
            TopicStatus.OPEN.value,
        ),
        else_=KnowledgeGapTopic.status,
    )


def _asker() -> ColumnElement[str]:
    """Who asked a run's question, as far as the run can tell.

    A channel turn is its sender's, since the run's member is the binding's
    creator - the member a linked chat account belongs to, so one person
    asking in a channel and in the console is one asker. A run that ran as a
    surface's publisher for somebody nobody knows, or with nobody at all, is
    one anonymous asker however many there were.
    """
    return case(
        (
            ChannelIdentity.user_id.is_not(None),
            literal("user:") + cast(ChannelIdentity.user_id, Text),
        ),
        (
            AgentRun.channel_identity_id.is_not(None),
            literal("channel:") + cast(AgentRun.channel_identity_id, Text),
        ),
        (
            and_(
                AgentRun.user_id.is_not(None), AgentRun.initiated_by_publisher_fallback.is_(False)
            ),
            literal("user:") + cast(AgentRun.user_id, Text),
        ),
        else_=literal("anonymous"),
    )


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
    # `execute` is typed to return `Result`, which has no `rowcount`; a DML
    # statement actually returns a `CursorResult`, which does (see `resource_grant`).
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


class TopicRow(NamedTuple):
    """A topic and what its searches add up to under the filters it was read with."""

    topic: KnowledgeGapTopic
    status: str
    """The topic's status as read: a covered topic whose document is gone is open."""
    question_count: int
    asker_count: int
    """Distinct people who asked, every anonymous asker counted as one."""
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
            _status().label("status"),
            question_count.label("question_count"),
            func.count(distinct(_asker())).label("asker_count"),
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
        .join(AgentRun, AgentRun.id == KnowledgeSearch.run_id)
        .outerjoin(ChannelIdentity, ChannelIdentity.id == AgentRun.channel_identity_id)
        .where(
            KnowledgeGapTopic.organization_id == organization_id,
            KnowledgeGapTopic.knowledge_base_id.in_(list(knowledge_base_ids)),
            *_members(organization_id=organization_id, threshold=threshold, agent_id=agent_id),
        )
        .group_by(KnowledgeGapTopic.id)
    )
    if status is not None:
        grouped = grouped.where(_status() == status)
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
            status=row[1],
            question_count=row[2],
            asker_count=row[3],
            last_asked_at=row[4],
            queries=list(row[5] or []),
            agent_ids=[agent for agent in row[6] or [] if agent is not None],
        )
        for row in result.all()
    ], total


async def topics_per_knowledge_base(
    db: AsyncSession,
    *,
    organization_id: UUID,
    knowledge_base_ids: Sequence[UUID],
    threshold: float,
    status: str | None,
    agent_id: UUID | None,
) -> list[tuple[UUID, int, int]]:
    """`(knowledge base, topics, questions)` for each base holding a topic, most asked first."""
    per_topic = (
        select(
            KnowledgeGapTopic.knowledge_base_id.label("knowledge_base_id"),
            func.count(KnowledgeSearch.id).label("questions"),
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
        per_topic = per_topic.where(_status() == status)
    topics = per_topic.subquery()
    questions = func.sum(topics.c.questions)
    result = await db.execute(
        select(topics.c.knowledge_base_id, func.count(), questions)
        .group_by(topics.c.knowledge_base_id)
        .order_by(questions.desc(), topics.c.knowledge_base_id)
    )
    return [(row[0], row[1], int(row[2])) for row in result.all()]


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


async def lock_topic(db: AsyncSession, topic: KnowledgeGapTopic) -> KnowledgeGapTopic:
    """Hold a topic's row to the end of the transaction, read afresh once held."""
    result = await db.execute(
        select(KnowledgeGapTopic)
        .where(KnowledgeGapTopic.id == topic.id)
        .with_for_update()
        .execution_options(populate_existing=True)
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
    limit: int | None,
) -> list[QuestionRow]:
    """A topic's searches, newest first, each with what the person asked and the answer.

    `None` reads every one of them.

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


async def knowledge_bases_with_misses(
    db: AsyncSession, *, organization_id: UUID, threshold: float, agent_id: UUID | None
) -> list[UUID]:
    """The knowledge bases a miss searched - one of this agent's misses, when named.

    A topic only ever holds misses in its own knowledge base, so this covers
    every base with a topic to show and every base whose misses still wait for
    their first grouping pass.
    """
    searched = func.unnest(KnowledgeSearch.knowledge_base_ids, type_=PG_UUID())
    result = await db.execute(
        select(distinct(searched)).where(
            *_members(organization_id=organization_id, threshold=threshold, agent_id=agent_id)
        )
    )
    return list(result.scalars().all())


class DraftingRow(NamedTuple):
    """One question as a drafting model is shown it."""

    search: KnowledgeSearch
    question: str | None
    answer: str | None
    found: str | None
    down_rating_comment: str | None


async def topic_versions(
    db: AsyncSession, topic_id: UUID, *, organization_id: UUID
) -> set[UUID | None]:
    """The agent versions that ran a topic's searches; none for a run with no version."""
    result = await db.execute(
        select(distinct(AgentRun.agent_version_id))
        .join(KnowledgeSearch, KnowledgeSearch.run_id == AgentRun.id)
        .join(KnowledgeGapMember, KnowledgeGapMember.search_id == KnowledgeSearch.id)
        .where(
            KnowledgeGapMember.topic_id == topic_id,
            KnowledgeSearch.organization_id == organization_id,
        )
    )
    return set(result.scalars().all())


async def drafting_material(
    db: AsyncSession,
    topic_id: UUID,
    *,
    organization_id: UUID,
    threshold: float,
    limit: int,
    knowledge_tools: Mapping[UUID | None, frozenset[str]],
) -> list[DraftingRow]:
    """A topic's newest questions with the answer each got and what its search returned.

    What the search returned is read back from the transcript's tool call, so a
    run with no conversation contributes its query alone. `knowledge_tools`
    names the knowledge search tool as each agent version called it, keyed by
    version - `None` for a run with none, and for a version not listed.
    """
    rows = await list_questions(
        db,
        topic_id,
        organization_id=organization_id,
        threshold=threshold,
        agent_id=None,
        limit=limit,
    )
    answers = await _answers(db, rows)
    found = await _found(
        db,
        list(dict.fromkeys(row.search.run_id for row in rows)),
        organization_id=organization_id,
        knowledge_tools=knowledge_tools,
    )
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


async def _found(
    db: AsyncSession,
    run_ids: Sequence[UUID],
    *,
    organization_id: UUID,
    knowledge_tools: Mapping[UUID | None, frozenset[str]],
) -> dict[UUID, str]:
    """What each search of these runs returned, by the search's id.

    Only the knowledge tool's own calls count: another tool taking a `query`
    argument - a web search, a CRM lookup - returned nothing from the knowledge
    base. A run's searches with one query take its calls with that query in
    order, and only when there are as many of each: a call that failed or was cut
    short leaves those searches with nothing rather than with another's result.
    """
    if not run_ids:
        return {}
    versions = dict(
        (
            await db.execute(
                select(AgentRun.id, AgentRun.agent_version_id).where(AgentRun.id.in_(list(run_ids)))
            )
        )
        .tuples()
        .all()
    )
    calls = await db.execute(
        select(Message.run_id, ToolCall.tool_name, ToolCall.args["query"].astext, ToolCall.result)
        .join(Message, Message.id == ToolCall.message_id)
        .where(Message.run_id.in_(list(run_ids)))
        .order_by(ToolCall.started_at, ToolCall.id)
    )
    results: dict[tuple[UUID, str], list[str | None]] = {}
    for run_id, tool_name, query, result in calls.tuples().all():
        version = versions.get(run_id)
        names = knowledge_tools.get(version, knowledge_tools[None])
        if tool_name in names and query is not None:
            results.setdefault((run_id, query), []).append(result)
    searches = await db.execute(
        select(KnowledgeSearch.id, KnowledgeSearch.run_id, KnowledgeSearch.query)
        .where(
            KnowledgeSearch.organization_id == organization_id,
            KnowledgeSearch.run_id.in_(list(run_ids)),
            KnowledgeSearch.signal == GapSignal.RETRIEVAL.value,
        )
        .order_by(KnowledgeSearch.created_at, KnowledgeSearch.id)
    )
    searched: dict[tuple[UUID, str], list[UUID]] = {}
    for search_id, run_id, query in searches.tuples().all():
        searched.setdefault((run_id, query), []).append(search_id)
    found: dict[UUID, str] = {}
    for key, search_ids in searched.items():
        returned = results.get(key, [])
        if len(returned) != len(search_ids):
            continue
        for search_id, result in zip(search_ids, returned, strict=True):
            if result is not None:
                found[search_id] = result
    return found


async def _answers(db: AsyncSession, rows: Sequence[QuestionRow]) -> dict[UUID, str]:
    answer_ids = [row.answer_message_id for row in rows if row.answer_message_id]
    if not answer_ids:
        return {}
    result = await db.execute(select(Message.id, Message.content).where(Message.id.in_(answer_ids)))
    return {row[0]: row[1] for row in result.all()}


async def source_texts(db: AsyncSession, rows: Sequence[QuestionRow]) -> list[str]:
    """What people's conversations put into these questions of a topic.

    Each question as asked and as searched, the answer it got and a reader's
    thumbs-down comment - what a passage written for the topic must not repeat.
    """
    answers = await _answers(db, rows)
    texts = (
        (
            row.question,
            row.search.query,
            answers.get(row.answer_message_id) if row.answer_message_id else None,
            row.down_rating_comment,
        )
        for row in rows
    )
    return [text for group in texts for text in group if text]


async def documents_by_id(
    db: AsyncSession, document_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, RAGDocument]:
    """The organization's documents among these ids."""
    if not document_ids:
        return {}
    result = await db.execute(
        select(RAGDocument).where(
            RAGDocument.organization_id == organization_id,
            RAGDocument.id.in_(list(document_ids)),
        )
    )
    return {document.id: document for document in result.scalars().all()}


async def member_queries(
    db: AsyncSession, topic_id: UUID, *, organization_id: UUID
) -> dict[UUID, str]:
    """The searches a topic holds, each with its query."""
    result = await db.execute(
        select(KnowledgeSearch.id, KnowledgeSearch.query)
        .join(KnowledgeGapMember, KnowledgeGapMember.search_id == KnowledgeSearch.id)
        .where(
            KnowledgeGapMember.topic_id == topic_id,
            KnowledgeSearch.organization_id == organization_id,
        )
    )
    return {row[0]: row[1] for row in result.all()}


async def documents_named(
    db: AsyncSession,
    knowledge_base_id: UUID,
    filenames: Sequence[str],
    *,
    organization_id: UUID,
    limit: int,
) -> list[RAGDocument]:
    """A knowledge base's documents carrying any of these file names, oldest first."""
    if not filenames:
        return []
    result = await db.execute(
        select(RAGDocument)
        .where(
            RAGDocument.organization_id == organization_id,
            RAGDocument.knowledge_base_id == knowledge_base_id,
            RAGDocument.filename.in_(list(filenames)),
        )
        .order_by(RAGDocument.filename, RAGDocument.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def documents_in(
    db: AsyncSession,
    knowledge_base_id: UUID,
    document_ids: Sequence[UUID],
    *,
    organization_id: UUID,
) -> dict[UUID, RAGDocument]:
    """The documents among these ids that belong to this knowledge base."""
    if not document_ids:
        return {}
    result = await db.execute(
        select(RAGDocument).where(
            RAGDocument.organization_id == organization_id,
            RAGDocument.knowledge_base_id == knowledge_base_id,
            RAGDocument.id.in_(list(document_ids)),
        )
    )
    return {document.id: document for document in result.scalars().all()}


def _closer(search: KnowledgeSearch, best: tuple[int, float | None] | None) -> bool:
    if best is None:
        return True
    return search.top_similarity is not None and (
        best[1] is None or search.top_similarity > best[1]
    )


CANDIDATE_COMMENTS = 5
"""How many of an answer's thumbs-down comments a classifying model is shown."""


class CandidateRow(NamedTuple):
    """An answer a model has still to read for a knowledge gap, with what it is shown."""

    message_id: UUID
    run_id: UUID
    agent_id: UUID
    conversation_id: UUID
    asker_id: UUID | None
    """Who started the run, whose question a miss read from it keeps."""
    question: str | None
    answer: str
    comments: list[str]
    """The newest thumbs-down comments, at most :data:`CANDIDATE_COMMENTS`."""
    result_count: int
    top_similarity: float | None
    """What the run's best search found, or nothing for a run that searched none."""
    missed: bool
    """Whether a search of the run already missed in the knowledge base, so counts already."""


def _down_rated_with_comment(message_id: SQLColumnExpression[UUID]) -> ColumnElement[bool]:
    return and_(
        MessageRating.message_id == message_id,
        MessageRating.rating == -1,
        func.length(func.trim(func.coalesce(MessageRating.comment, ""))) > 0,
    )


def _candidates(
    knowledge_base_id: UUID, *, organization_id: UUID, since: datetime
) -> tuple[Any, Any]:
    """The runs and their last answers that are candidates for one knowledge base.

    An answer is a candidate when its run is a person's - never an eval's,
    whose questions were replayed or generated, nor a builder's test of a
    draft, nor a delegate's - finished, still has its starter and a kept
    conversation, and either
    searched the knowledge base without missing or was rated down with a
    comment by an agent version that binds it. A run that already missed on the
    base is a candidate too, so that a rightful refusal of a request outside the
    agent's rules takes its misses out of the gaps. An answer is read once for
    each knowledge base, and again only if it read as `none` there and a newer
    thumbs-down with a comment has arrived since.
    """
    answer = aliased(Message)
    searched = exists().where(
        KnowledgeSearch.run_id == AgentRun.id,
        KnowledgeSearch.signal == GapSignal.RETRIEVAL.value,
        any_(KnowledgeSearch.knowledge_base_ids) == knowledge_base_id,
    )
    binds = exists().where(
        AgentVersion.id == AgentRun.agent_version_id,
        AgentVersion.spec["collection_ids"].contains([str(knowledge_base_id)]),
    )
    rated = exists().where(_down_rated_with_comment(answer.id))
    read = exists().where(
        KnowledgeGapClassification.message_id == answer.id,
        KnowledgeGapClassification.knowledge_base_id == knowledge_base_id,
    )
    reread = exists().where(
        KnowledgeGapClassification.message_id == answer.id,
        KnowledgeGapClassification.knowledge_base_id == knowledge_base_id,
        KnowledgeGapClassification.signal == "none",
        exists().where(
            _down_rated_with_comment(answer.id),
            func.coalesce(MessageRating.updated_at, MessageRating.created_at)
            > KnowledgeGapClassification.classified_at,
        ),
    )
    conditions = (
        AgentRun.organization_id == organization_id,
        AgentRun.surface != RunSurface.EVAL.value,
        AgentRun.status == RunStatus.COMPLETED.value,
        AgentRun.is_test.is_(False),
        AgentRun.parent_run_id.is_(None),
        AgentRun.user_id.is_not(None),
        AgentRun.conversation_id.is_not(None),
        AgentRun.started_at >= since,
        answer.id == _answer_of(AgentRun.id),
        or_(searched, and_(rated, binds)),
        or_(~read, reread),
    )
    return answer, conditions


async def classification_candidates(
    db: AsyncSession,
    knowledge_base_id: UUID,
    *,
    organization_id: UUID,
    threshold: float,
    since: datetime,
    limit: int,
) -> list[CandidateRow]:
    """The newest answers in one knowledge base's runs that a model has still to read."""
    answer, conditions = _candidates(
        knowledge_base_id, organization_id=organization_id, since=since
    )
    question = (
        select(Message.content)
        .where(Message.run_id == AgentRun.id, Message.role == "user")
        .order_by(Message.ordinal)
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(
            answer.id,
            AgentRun.id,
            AgentRun.agent_id,
            answer.conversation_id,
            AgentRun.user_id,
            question,
            answer.content,
        )
        .select_from(AgentRun)
        .join(answer, answer.run_id == AgentRun.id)
        .where(*conditions)
        .order_by(AgentRun.started_at.desc(), AgentRun.id)
        .limit(limit)
    )
    rows = result.all()
    run_ids = [row[1] for row in rows]
    message_ids = [row[0] for row in rows]
    comments: dict[UUID, list[str]] = {}
    best: dict[UUID, tuple[int, float | None]] = {}
    missed: set[UUID] = set()
    if rows:
        rated = await db.execute(
            select(MessageRating.message_id, func.trim(MessageRating.comment, type_=Text))
            .where(_down_rated_with_comment(MessageRating.message_id))
            .where(MessageRating.message_id.in_(message_ids))
            .order_by(func.coalesce(MessageRating.updated_at, MessageRating.created_at).desc())
        )
        for message_id, comment in rated.all():
            kept = comments.setdefault(message_id, [])
            if len(kept) < CANDIDATE_COMMENTS:
                kept.append(comment)
        searches = await db.execute(
            select(KnowledgeSearch).where(
                KnowledgeSearch.organization_id == organization_id,
                KnowledgeSearch.run_id.in_(run_ids),
                KnowledgeSearch.signal == GapSignal.RETRIEVAL.value,
                any_(KnowledgeSearch.knowledge_base_ids) == knowledge_base_id,
            )
        )
        for search in searches.scalars().all():
            if _closer(search, best.get(search.run_id)):
                best[search.run_id] = (search.result_count, search.top_similarity)
            if search.result_count == 0 or (
                search.top_similarity is not None and search.top_similarity < threshold
            ):
                missed.add(search.run_id)
    return [
        CandidateRow(
            message_id=row[0],
            run_id=row[1],
            agent_id=row[2],
            conversation_id=row[3],
            asker_id=row[4],
            question=row[5],
            answer=row[6],
            comments=comments.get(row[0], []),
            result_count=best.get(row[1], (0, None))[0],
            top_similarity=best.get(row[1], (0, None))[1],
            missed=row[1] in missed,
        )
        for row in rows
    ]


async def count_unchecked(
    db: AsyncSession, knowledge_base_id: UUID, *, organization_id: UUID, since: datetime
) -> int:
    """How many answers in one knowledge base's runs a model has still to read."""
    answer, conditions = _candidates(
        knowledge_base_id, organization_id=organization_id, since=since
    )
    result = await db.execute(
        select(func.count(answer.id))
        .select_from(AgentRun)
        .join(answer, answer.run_id == AgentRun.id)
        .where(*conditions)
    )
    return result.scalar_one()


class Verdict(NamedTuple):
    """What a model decided about one candidate."""

    candidate: CandidateRow
    verdict: str
    """What the answer is remembered as: a `GapSignal` other than retrieval, `none` or `refused`."""
    signal: GapSignal | None
    """`ANSWER` or `RATING` for a miss to record, None for none - as for a run already missed."""
    query: str
    """What a miss is grouped by: the person's question, bounded as a search's query is."""


async def still_asked(
    db: AsyncSession, candidates: Sequence[CandidateRow], *, organization_id: UUID
) -> set[UUID]:
    """The candidates' answers that still exist, in runs still started by the same person.

    An answer whose conversation went, or whose run lost its starter to an
    erasure, has nobody's question left to record.
    """
    if not candidates:
        return set()
    result = await db.execute(
        select(Message.id, AgentRun.user_id)
        .join(AgentRun, AgentRun.id == Message.run_id)
        .where(
            AgentRun.organization_id == organization_id,
            Message.id.in_([candidate.message_id for candidate in candidates]),
        )
    )
    starters = {row[0]: row[1] for row in result.all()}
    return {
        candidate.message_id
        for candidate in candidates
        if candidate.message_id in starters and starters[candidate.message_id] == candidate.asker_id
    }


async def record_classifications(
    db: AsyncSession,
    verdicts: Sequence[Verdict],
    knowledge_base_id: UUID,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> int:
    """Remember each answer as read for one knowledge base, and record its misses there.

    A miss belongs to the knowledge base that was checked alone: the caller's
    access to it is what the check rested on.

    Returns:
        How many misses were recorded.
    """
    if not verdicts:
        return 0
    statement = pg_insert(KnowledgeGapClassification).values(
        [
            {
                "message_id": verdict.candidate.message_id,
                "knowledge_base_id": knowledge_base_id,
                "organization_id": organization_id,
                "signal": verdict.verdict,
                "run_id": run_id,
            }
            for verdict in verdicts
        ]
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[
                KnowledgeGapClassification.message_id,
                KnowledgeGapClassification.knowledge_base_id,
            ],
            set_={
                "signal": statement.excluded.signal,
                "run_id": statement.excluded.run_id,
                "classified_at": func.now(),
            },
        )
    )
    refused_runs = [v.candidate.run_id for v in verdicts if v.verdict == REFUSED]
    if refused_runs:
        # A refusal takes the run's searches out of the gaps; out of their topics too, so
        # a topic left with nothing is removed and no centroid keeps drawing on them.
        await db.execute(
            delete(KnowledgeGapMember).where(
                KnowledgeGapMember.search_id.in_(
                    select(KnowledgeSearch.id).where(
                        KnowledgeSearch.organization_id == organization_id,
                        KnowledgeSearch.run_id.in_(refused_runs),
                        any_(KnowledgeSearch.knowledge_base_ids) == knowledge_base_id,
                    )
                )
            )
        )
    misses = [verdict for verdict in verdicts if verdict.signal is not None]
    if not misses:
        return 0
    result = await db.execute(
        pg_insert(KnowledgeSearch)
        .values(
            [
                {
                    "organization_id": organization_id,
                    "run_id": verdict.candidate.run_id,
                    "agent_id": verdict.candidate.agent_id,
                    "conversation_id": verdict.candidate.conversation_id,
                    "knowledge_base_ids": [knowledge_base_id],
                    "query": verdict.query,
                    "result_count": verdict.candidate.result_count,
                    "top_similarity": verdict.candidate.top_similarity,
                    "signal": verdict.signal.value,
                    "message_id": verdict.candidate.message_id,
                }
                for verdict in misses
                if verdict.signal is not None
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[KnowledgeSearch.message_id, KnowledgeSearch.knowledge_base_ids],
            index_where=KnowledgeSearch.message_id.is_not(None),
        )
    )
    await db.flush()
    # `execute` is typed to return `Result`, which has no `rowcount`; a DML
    # statement actually returns a `CursorResult`, which does (see `resource_grant`).
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]
