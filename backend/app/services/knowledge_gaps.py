"""Knowledge gaps: the questions a knowledge base could not answer, grouped into topics.

Agents record every knowledge search they make (see
`app.agents.capabilities.knowledge`). A search that returned nothing, or nothing
as similar to the query as `KNOWLEDGE_GAP_MIN_SIMILARITY`, is a *miss*. Misses
are grouped per knowledge base by the meaning of the query, in that
collection's own embedding space, into topics a person can act on: add the
missing document, or turn the questions into dataset cases to check it.

Grouping embeds queries but asks no model to write anything, so it runs for
every organization, like ingestion embeddings do. Nothing here ever adds a
document to a collection.

A model is asked only on request, as the person asking: to draft a topic's
missing passage, or to read a knowledge base's recent answers - and the
thumbs-down comments on them - for the questions it could not answer, which
retrieval alone does not see.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import numpy as np
import numpy.typing as npt
from pydantic_ai_harness.guardrails.detectors import redact_secrets
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.knowledge._log import MAX_QUERY_CHARS
from app.agents.system_agents import KNOWLEDGE_GAP_CLASSIFIER, KNOWLEDGE_GAP_DRAFTER
from app.core.audit import current_impersonator
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm, Scope
from app.db.locks import LockScope, hold_subject
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import GapSignal, KnowledgeGapTopic, KnowledgeSearch, TopicStatus
from app.db.models.rag_document import RAGDocument
from app.repositories import agent_repo, knowledge_base_repo, knowledge_gap_repo, member_repo
from app.repositories.knowledge_gap import CandidateRow, DraftingRow, TopicRow, Verdict
from app.schemas.knowledge_gap import (
    MAX_DRAFT_SOURCES,
    ClassifiedAnswer,
    KnowledgeGapAgent,
    KnowledgeGapCasesAdded,
    KnowledgeGapClassification,
    KnowledgeGapCollectionCount,
    KnowledgeGapDraft,
    KnowledgeGapDraftRead,
    KnowledgeGapQuestion,
    KnowledgeGapReport,
    KnowledgeGapSource,
    KnowledgeGapSourceRead,
    KnowledgeGapTopicDetail,
    KnowledgeGapTopicList,
    KnowledgeGapTopicRead,
    TopicStatusLiteral,
)
from app.services.access import AGENT, resolve_access
from app.services.collection_access import readable_kb, writable_kb
from app.services.dataset import DatasetService
from app.services.embedding_resolution import ResolvedEmbeddings, embeddings_for_collection
from app.services.rag.vectorstore import embedder_for
from app.services.system_agent_runner import SystemAgentRunner

logger = logging.getLogger(__name__)

TOPIC_SIMILARITY = 0.80
"""How similar a miss must be to a topic's centroid to join it, rather than start one."""

GROUPING_BATCH = 500
"""The most misses one knowledge base embeds in one pass; the rest wait for the next."""

TOPIC_QUESTIONS = 100
"""The most recent questions a topic's page lists."""

TOPIC_TO_DATASET = 200
"""The most recent answers one "Add to dataset" turns into cases."""

DRAFT_QUESTIONS = 20
"""The most recent questions a drafting model is shown."""

DRAFT_DOCUMENTS = 20
"""The most documents a drafting model is offered to cite."""

EXAMPLES = 3

CLASSIFY_WINDOW = timedelta(days=30)
"""How far back the answers a knowledge base's check reads go."""

CLASSIFY_BATCH = 20
"""The answers one classifying run reads."""

CLASSIFY_PER_REQUEST = 100
"""The most answers one check reads; the rest wait for the next."""

Vector = npt.NDArray[np.float64]


def _unit(values: list[float]) -> Vector:
    vector = np.asarray(values, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


@dataclass
class _Cluster:
    """A topic while a pass assigns to it: the stored row, or one still to be created."""

    centroid: Vector
    size: int
    topic: KnowledgeGapTopic | None
    searches: list[UUID]
    moved: bool = False

    def take(self, vector: Vector, search_id: UUID) -> None:
        self.centroid = (self.centroid * self.size + vector) / (self.size + 1)
        self.size += 1
        self.searches.append(search_id)
        self.moved = True


def _assign(
    misses: list[tuple[UUID, Vector]], clusters: list[_Cluster], *, threshold: float
) -> list[_Cluster]:
    """Put each miss into the nearest cluster at least `threshold` similar, or a new one.

    In order, so a miss can join a cluster an earlier miss of the same pass
    started. Vectors are unit length; a centroid is compared by direction.
    """
    for search_id, vector in misses:
        best: _Cluster | None = None
        if clusters:
            directions = np.vstack([_unit(c.centroid.tolist()) for c in clusters])
            scores = directions @ vector
            index = int(np.argmax(scores))
            if float(scores[index]) >= threshold:
                best = clusters[index]
        if best is None:
            clusters.append(
                _Cluster(centroid=vector, size=1, topic=None, searches=[search_id], moved=True)
            )
        else:
            best.take(vector, search_id)
    return clusters


def _require_runs_view(ctx: AuthContext) -> None:
    """Refuse a caller who may not read every run: a topic is made of people's questions."""
    if ctx.scope_for(Perm.RUNS_VIEW) < Scope.ALL:
        raise AuthorizationError(
            message="Knowledge gaps are read from people's questions, which takes runs:view",
            details={"required": [Perm.RUNS_VIEW.value]},
        )


def _distinct(queries: list[str], *, keep: int) -> list[str]:
    return list(dict.fromkeys(queries))[:keep]


def _redacted(text: str) -> str:
    verdict = redact_secrets(text)
    if verdict.action == "replace" and isinstance(verdict.replacement, str):
        return verdict.replacement
    return text


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return "-"
    return text if len(text) <= limit else f"{text[:limit]}..."


# How the knowledge capability names the document a passage came from.
_FOUND_SOURCE = re.compile(
    r"^\[\d+\] Source: (.+?)"
    r"(?:, page [^,\[(]+|, chunk [^,\[(]+| \[[^\]]*\]|, with surrounding text)* \(score: ",
    re.MULTILINE,
)


def _found_filenames(material: list[DraftingRow]) -> list[str]:
    """The file names the topic's searches returned passages from, first seen first."""
    names = (
        match.group(1) for row in material for match in _FOUND_SOURCE.finditer(row.found or "")
    )
    return list(dict.fromkeys(names))


def _drafting_prompt(
    knowledge_base: str, material: list[DraftingRow], documents: list[RAGDocument]
) -> str:
    """The questions a draft is for and the documents it may cite, each numbered."""
    parts = [
        f'The knowledge base "{knowledge_base}" could not answer these questions. '
        "Draft the passage that would answer them. In `questions`, list the numbers of "
        "the questions your draft answers; in `documents`, the numbers of the documents "
        "below whose content your draft builds on. Cite only numbers listed here.",
    ]
    if documents:
        parts.append(
            "## Documents the agent found\n"
            + "\n".join(f"{n}. {doc.filename}" for n, doc in enumerate(documents, start=1))
        )
    for number, row in enumerate(material, start=1):
        parts.append(
            f"## Question {number}\n"
            f"Asked: {_clip(row.question, 1_000)}\n"
            f"Searched for: {_clip(row.search.query, 500)}\n"
            f"Found: {_clip(row.found, 2_000)}\n"
            f"Answered: {_clip(row.answer, 1_500)}\n"
            f"Reader's comment: {_clip(row.down_rating_comment, 500)}"
        )
    return "\n\n".join(parts)


def _classification_prompt(knowledge_base: str, candidates: list[CandidateRow]) -> str:
    """The answers a classifying model reads, each numbered."""
    parts = [
        f'These answers were given from the knowledge base "{knowledge_base}". Classify '
        "every one of them, citing it by its number.",
    ]
    for number, candidate in enumerate(candidates, start=1):
        comments = "\n".join(f"- {_clip(comment, 600)}" for comment in candidate.comments)
        parts.append(
            f"## Answer {number}\n"
            f"Asked: {_clip(candidate.question, 600)}\n"
            f"Answered: {_clip(candidate.answer, 1_200)}\n"
            f"Comments of readers who rated it down:\n{comments or '(none)'}"
        )
    return "\n\n".join(parts)


def _verdicts(candidates: list[CandidateRow], answers: list[ClassifiedAnswer]) -> list[Verdict]:
    """The verdicts on the candidates the model numbered, the first one each.

    A number that names no candidate is dropped, and a candidate the model
    skipped gets no verdict, so it waits for the next check rather than being
    remembered as read.
    """
    decided: dict[int, ClassifiedAnswer] = {}
    for answer in answers:
        if 1 <= answer.number <= len(candidates):
            decided.setdefault(answer.number, answer)
    return [
        Verdict(
            candidate=candidates[number - 1],
            signal=None if answer.signal == "none" else GapSignal(answer.signal),
            query=(candidates[number - 1].question or candidates[number - 1].answer)[
                :MAX_QUERY_CHARS
            ],
        )
        for number, answer in sorted(decided.items())
    ]


def _cited[T](numbers: list[int], numbered: list[T]) -> tuple[list[T], int]:
    """What a model cited by number, and how many of its numbers named nothing."""
    distinct_numbers = list(dict.fromkeys(numbers))
    cited = [numbered[n - 1] for n in distinct_numbers if 1 <= n <= len(numbered)]
    return cited, len(distinct_numbers) - len(cited)


class KnowledgeGapService:
    """Finds, groups and reports what agents could not find in their knowledge bases."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _knowledge_base(
        self, ctx: AuthContext, knowledge_base_id: UUID, *, edit: bool = False
    ) -> KnowledgeBase:
        """The caller's organization's knowledge base, if they may read it - or change it."""
        kb = await knowledge_base_repo.get_by_id(self.db, knowledge_base_id)
        allowed = (
            kb is not None
            and kb.organization_id == ctx.organization_id
            and await (writable_kb if edit else readable_kb)(self.db, ctx, kb)
        )
        if kb is None or not allowed:
            raise NotFoundError(
                message="Knowledge base not found",
                details={"knowledge_base_id": knowledge_base_id},
            )
        return kb

    async def _agents(self, ctx: AuthContext, ids: list[UUID]) -> dict[UUID, KnowledgeGapAgent]:
        found = await agent_repo.get_many(self.db, ids, organization_id=ctx.organization_id)
        return {
            agent_id: KnowledgeGapAgent(
                id=agent_id,
                name=a.name,
                slug=a.slug,
                has_avatar=a.has_avatar,
                avatar_color=a.avatar_color,
            )
            for agent_id, a in found.items()
        }

    async def _reads(self, ctx: AuthContext, rows: list[TopicRow]) -> list[KnowledgeGapTopicRead]:
        agents = await self._agents(ctx, sorted({a for row in rows for a in row.agent_ids}))
        bases = await knowledge_base_repo.get_by_ids(
            self.db, sorted({row.topic.knowledge_base_id for row in rows})
        )
        writable = {kb_id for kb_id, kb in bases.items() if await writable_kb(self.db, ctx, kb)}
        return [
            KnowledgeGapTopicRead(
                id=row.topic.id,
                knowledge_base_id=row.topic.knowledge_base_id,
                knowledge_base_name=bases[row.topic.knowledge_base_id].name,
                status=TopicStatus(row.topic.status).value,
                label=row.queries[0] if row.queries else "",
                question_count=row.question_count,
                last_asked_at=row.last_asked_at,
                examples=_distinct(row.queries, keep=EXAMPLES),
                agents=[agents[a] for a in row.agent_ids if a in agents],
                dismissed_at=row.topic.dismissed_at,
                has_draft=row.topic.draft_content is not None,
                can_edit=row.topic.knowledge_base_id in writable,
            )
            for row in rows
        ]

    async def _list(
        self,
        ctx: AuthContext,
        knowledge_base_ids: list[UUID],
        *,
        agent_id: UUID | None,
        status: TopicStatusLiteral | None,
        skip: int,
        limit: int,
    ) -> KnowledgeGapTopicList:
        threshold = settings.KNOWLEDGE_GAP_MIN_SIMILARITY
        rows, total = await knowledge_gap_repo.list_topics(
            self.db,
            organization_id=ctx.organization_id,
            knowledge_base_ids=knowledge_base_ids,
            threshold=threshold,
            status=status,
            agent_id=agent_id,
            skip=skip,
            limit=limit,
        )
        ungrouped = await knowledge_gap_repo.count_ungrouped(
            self.db,
            organization_id=ctx.organization_id,
            knowledge_base_ids=knowledge_base_ids,
            threshold=threshold,
            agent_id=agent_id,
        )
        counts = await knowledge_gap_repo.topics_per_knowledge_base(
            self.db,
            organization_id=ctx.organization_id,
            knowledge_base_ids=knowledge_base_ids,
            threshold=threshold,
            status=status,
            agent_id=agent_id,
        )
        bases = await knowledge_base_repo.get_by_ids(self.db, [kb_id for kb_id, _, _ in counts])
        return KnowledgeGapTopicList(
            items=await self._reads(ctx, rows),
            total=total,
            by_knowledge_base=[
                KnowledgeGapCollectionCount(
                    knowledge_base_id=kb_id,
                    knowledge_base_name=bases[kb_id].name,
                    topics=topics,
                    questions=questions,
                )
                for kb_id, topics, questions in counts
            ],
            ungrouped=ungrouped,
        )

    async def list_for_knowledge_base(
        self,
        ctx: AuthContext,
        knowledge_base_id: UUID,
        *,
        status: TopicStatusLiteral | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> KnowledgeGapTopicList:
        """The questions one knowledge base could not answer, grouped, the most asked first.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a knowledge base the caller may not read.
        """
        _require_runs_view(ctx)
        kb = await self._knowledge_base(ctx, knowledge_base_id)
        listed = await self._list(
            ctx, [kb.id], agent_id=None, status=status, skip=skip, limit=limit
        )
        listed.can_regroup = await writable_kb(self.db, ctx, kb)
        listed.unchecked = await self._unchecked(ctx, kb.id)
        return listed

    async def _unchecked(self, ctx: AuthContext, knowledge_base_id: UUID) -> int:
        return await knowledge_gap_repo.count_unchecked(
            self.db,
            knowledge_base_id,
            organization_id=ctx.organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            since=datetime.now(UTC) - CLASSIFY_WINDOW,
        )

    async def _readable_with_misses(self, ctx: AuthContext, *, agent_id: UUID | None) -> list[UUID]:
        candidates = await knowledge_gap_repo.knowledge_bases_with_misses(
            self.db,
            organization_id=ctx.organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            agent_id=agent_id,
        )
        found = await knowledge_base_repo.get_by_ids(self.db, candidates)
        return [
            kb.id
            for kb in found.values()
            if kb.organization_id == ctx.organization_id and await readable_kb(self.db, ctx, kb)
        ]

    async def list_for_organization(
        self,
        ctx: AuthContext,
        *,
        status: TopicStatusLiteral | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> KnowledgeGapTopicList:
        """Every knowledge base's gaps the caller may read, the most asked first.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
        """
        _require_runs_view(ctx)
        readable = await self._readable_with_misses(ctx, agent_id=None)
        return await self._list(ctx, readable, agent_id=None, status=status, skip=skip, limit=limit)

    async def list_for_agent(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        status: TopicStatusLiteral | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> KnowledgeGapTopicList:
        """What one agent searched for and did not find, in the knowledge bases the caller reads.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For an agent the caller may not see.
        """
        _require_runs_view(ctx)
        agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if agent is None or not await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_VIEW, resource_type=AGENT
        ):
            raise NotFoundError(message="Agent not found", details={"agent_id": agent_id})
        readable = await self._readable_with_misses(ctx, agent_id=agent.id)
        return await self._list(
            ctx, readable, agent_id=agent.id, status=status, skip=skip, limit=limit
        )

    async def _topic(
        self, ctx: AuthContext, topic_id: UUID, *, edit: bool = False
    ) -> KnowledgeGapTopic:
        topic = await knowledge_gap_repo.get_topic(
            self.db, topic_id, organization_id=ctx.organization_id
        )
        if topic is None:
            raise NotFoundError(message="Topic not found", details={"topic_id": topic_id})
        try:
            await self._knowledge_base(ctx, topic.knowledge_base_id, edit=edit)
        except NotFoundError:
            raise NotFoundError(message="Topic not found", details={"topic_id": topic_id}) from None
        return topic

    async def read(self, ctx: AuthContext, topic_id: UUID) -> KnowledgeGapTopicDetail:
        """A topic with its most recent questions, each with the answer it got.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a topic in a knowledge base the caller may not read.
        """
        _require_runs_view(ctx)
        topic = await self._topic(ctx, topic_id)
        threshold = settings.KNOWLEDGE_GAP_MIN_SIMILARITY
        rows, _ = await knowledge_gap_repo.list_topics(
            self.db,
            organization_id=ctx.organization_id,
            knowledge_base_ids=[topic.knowledge_base_id],
            threshold=threshold,
            status=None,
            agent_id=None,
            topic_id=topic.id,
            skip=0,
            limit=1,
        )
        if not rows:
            # Every question it held is gone, or no longer counts as a miss.
            raise NotFoundError(message="Topic not found", details={"topic_id": topic_id})
        questions = await knowledge_gap_repo.list_questions(
            self.db,
            topic.id,
            organization_id=ctx.organization_id,
            threshold=threshold,
            agent_id=None,
            limit=TOPIC_QUESTIONS,
        )
        agents = await self._agents(ctx, sorted({q.search.agent_id for q in questions}))
        [summary] = await self._reads(ctx, rows)
        return KnowledgeGapTopicDetail(
            **summary.model_dump(),
            questions=[
                KnowledgeGapQuestion(
                    search_id=q.search.id,
                    query=q.search.query,
                    signal=GapSignal(q.search.signal).value,
                    question=q.question,
                    top_similarity=q.search.top_similarity,
                    result_count=q.search.result_count,
                    agent=agents.get(q.search.agent_id),
                    run_id=q.search.run_id,
                    conversation_id=q.search.conversation_id,
                    answer_message_id=q.answer_message_id,
                    down_rating_comment=q.down_rating_comment,
                    asked_at=q.search.created_at,
                )
                for q in questions
            ],
            draft=await self._draft_read(ctx, topic),
        )

    async def draft(self, ctx: AuthContext, topic_id: UUID) -> KnowledgeGapTopicDetail:
        """Ask the drafting agent for the passage a topic's questions need, and keep it.

        One run of the organization's seeded knowledge-gap drafter, as the caller:
        refused while the organization has AI assistance switched off, metered
        against the drafter's and the organization's budgets, and listed in
        Activity. It is shown the topic's newest questions, the answers they got,
        what each search returned and what readers said. What it writes is kept
        on the topic as a draft for a person; nothing is added to the knowledge
        base. It replaces the topic's draft, so it takes what dismissing does: a
        caller who may change the topic's knowledge base.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            AiAssistanceDisabledError: The organization switched AI assistance off.
            NotFoundError: For a topic in a knowledge base the caller may not
                change, or one with no questions left.
            SystemAgentUnavailableError: The drafter cannot run for this caller.
            SystemAgentRunError: The run ended without an answer, as a budget
                refusal does; it is recorded.
            SystemAgentOutputError: The drafter answered in a shape that could not
                be read.
        """
        _require_runs_view(ctx)
        topic = await self._topic(ctx, topic_id, edit=True)
        material = await knowledge_gap_repo.drafting_material(
            self.db,
            topic.id,
            organization_id=ctx.organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            limit=DRAFT_QUESTIONS,
        )
        if not material:
            raise NotFoundError(message="Topic not found", details={"topic_id": topic_id})
        kb = await self._knowledge_base(ctx, topic.knowledge_base_id, edit=True)
        documents = await knowledge_gap_repo.documents_named(
            self.db,
            kb.id,
            _found_filenames(material),
            organization_id=ctx.organization_id,
            limit=DRAFT_DOCUMENTS,
        )
        result = await SystemAgentRunner(self.db).run(
            ctx,
            key=KNOWLEDGE_GAP_DRAFTER.key,
            prompt=_drafting_prompt(kb.name, material, documents),
            output_type=KnowledgeGapDraft,
        )
        cited_documents, unknown_documents = _cited(result.output.documents, documents)
        cited_questions, unknown_questions = _cited(
            result.output.questions, [row.search for row in material]
        )
        await self.record_draft(
            ctx,
            KnowledgeGapReport(
                topic_id=topic.id,
                title=result.output.title,
                content=result.output.content,
                sources=[
                    *(KnowledgeGapSource(kind="document", id=doc.id) for doc in cited_documents),
                    *(KnowledgeGapSource(kind="question", id=s.id) for s in cited_questions),
                ],
            ),
            run_id=result.run.id,
            unverified=unknown_documents + unknown_questions,
        )
        return await self.read(ctx, topic.id)

    async def record_draft(
        self,
        ctx: AuthContext,
        report: KnowledgeGapReport,
        *,
        run_id: UUID | None = None,
        unverified: int = 0,
    ) -> None:
        """Keep proposed content on a topic, replacing any earlier draft.

        The one way a passage reaches a topic, whoever drafted it. Every source is
        verified first: a document must belong to the topic's knowledge base, a
        question must be one of the topic's searches. One that is not is left
        out and counted with `unverified` - which the caller passes for sources
        it could not even resolve - so the draft never shows a source nobody
        checked. At most :data:`MAX_DRAFT_SOURCES` are kept. Any credential the
        text repeats is redacted.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a topic in a knowledge base the caller may not change.
        """
        _require_runs_view(ctx)
        topic = await self._topic(ctx, report.topic_id, edit=True)
        named = list(dict.fromkeys((source.kind, source.id) for source in report.sources))
        questions = await knowledge_gap_repo.member_queries(
            self.db, topic.id, organization_id=ctx.organization_id
        )
        documents = await knowledge_gap_repo.documents_in(
            self.db,
            topic.knowledge_base_id,
            [source_id for kind, source_id in named if kind == "document"],
            organization_id=ctx.organization_id,
        )
        verified = [
            {"kind": kind, "id": str(source_id)}
            for kind, source_id in named
            if (kind == "document" and source_id in documents)
            or (kind == "question" and source_id in questions)
        ]
        await knowledge_gap_repo.update_topic(
            self.db,
            topic=topic,
            update_data={
                "draft_title": _redacted(report.title),
                "draft_content": _redacted(report.content),
                "draft_sources": verified[:MAX_DRAFT_SOURCES],
                "draft_unverified": unverified + len(named) - len(verified),
                "draft_run_id": run_id,
                "drafted_by_user_id": ctx.user_id,
                "drafted_at": datetime.now(UTC),
            },
        )

    async def _draft_read(
        self, ctx: AuthContext, topic: KnowledgeGapTopic
    ) -> KnowledgeGapDraftRead | None:
        """A topic's draft, with each source named - and left out if it is gone since."""
        if topic.draft_content is None or topic.drafted_at is None:
            return None
        questions = await knowledge_gap_repo.member_queries(
            self.db, topic.id, organization_id=ctx.organization_id
        )
        documents = await knowledge_gap_repo.documents_in(
            self.db,
            topic.knowledge_base_id,
            [UUID(s["id"]) for s in topic.draft_sources if s["kind"] == "document"],
            organization_id=ctx.organization_id,
        )
        sources: list[KnowledgeGapSourceRead] = []
        for source in topic.draft_sources:
            source_id = UUID(source["id"])
            if source["kind"] == "document" and source_id in documents:
                sources.append(
                    KnowledgeGapSourceRead(
                        kind="document", id=source_id, label=documents[source_id].filename
                    )
                )
            elif source["kind"] == "question" and source_id in questions:
                sources.append(
                    KnowledgeGapSourceRead(
                        kind="question", id=source_id, label=questions[source_id]
                    )
                )
        return KnowledgeGapDraftRead(
            title=topic.draft_title or "",
            content=topic.draft_content,
            sources=sources,
            unverified=topic.draft_unverified,
            drafted_at=topic.drafted_at,
            run_id=topic.draft_run_id,
        )

    async def set_status(
        self, ctx: AuthContext, topic_id: UUID, status: TopicStatusLiteral
    ) -> KnowledgeGapTopicDetail:
        """Dismiss a topic that needs no content, or reopen one.

        A dismissed topic keeps taking the questions that belong to it, so it
        does not come back as a new topic the next time one is asked.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a topic in a knowledge base the caller may not change.
        """
        _require_runs_view(ctx)
        topic = await self._topic(ctx, topic_id, edit=True)
        dismissed = status == TopicStatus.DISMISSED.value
        await knowledge_gap_repo.update_topic(
            self.db,
            topic=topic,
            update_data={
                "status": status,
                "dismissed_by_user_id": ctx.user_id if dismissed else None,
                "dismissed_at": datetime.now(UTC) if dismissed else None,
            },
        )
        return await self.read(ctx, topic.id)

    async def add_to_dataset(
        self, ctx: AuthContext, topic_id: UUID, dataset_id: UUID
    ) -> KnowledgeGapCasesAdded:
        """Turn a topic's questions into dataset cases, in one new version.

        Each case is the person's question and, as its counter-example, the
        answer the agent gave without the missing content - so once a document
        is added, an eval over the dataset shows whether the answers changed.
        The :data:`TOPIC_TO_DATASET` most recent answers are taken; a question
        asked over the HTTP API keeps no answer and is skipped.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a topic the caller may not read, or a dataset they
                may not edit.
        """
        _require_runs_view(ctx)
        topic = await self._topic(ctx, topic_id)
        questions = await knowledge_gap_repo.list_questions(
            self.db,
            topic.id,
            organization_id=ctx.organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            agent_id=None,
            limit=TOPIC_TO_DATASET,
        )
        message_ids = list(
            dict.fromkeys(q.answer_message_id for q in questions if q.answer_message_id)
        )
        unanswered = sum(1 for q in questions if q.answer_message_id is None)
        version, skipped = await DatasetService(self.db).add_from_messages(
            ctx, dataset_id, message_ids
        )
        return KnowledgeGapCasesAdded(
            dataset_id=dataset_id,
            version=None if version is None else version.number,
            added=len(message_ids) - skipped,
            skipped=skipped + unanswered,
        )

    async def regroup(self, ctx: AuthContext, knowledge_base_id: UUID) -> None:
        """Group a knowledge base's waiting misses now, rather than at the next scheduled pass.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a knowledge base the caller may not change.
        """
        _require_runs_view(ctx)
        kb = await self._knowledge_base(ctx, knowledge_base_id, edit=True)
        # Imported here: the flow module imports this service.
        from app.worker.tasks.knowledge_gap_tasks import group_knowledge_gaps_flow

        spawn_after_commit(
            self.db,
            group_knowledge_gaps_flow(
                organization_id=str(ctx.organization_id), knowledge_base_id=str(kb.id)
            ),
            name=f"group-knowledge-gaps-{kb.id}",
        )

    async def classify(self, ctx: AuthContext, knowledge_base_id: UUID) -> None:
        """Have a model read a knowledge base's recent answers for questions it could not answer.

        Every refusal is made here, before anything runs: the check reads
        other people's questions, answers and comments, so it takes `runs:view`
        across the organization, and records misses on the knowledge base, so it
        takes what dismissing does. The reading itself happens after the
        commit, in runs of the classifier as the caller - metered, checked
        against budgets and listed in Activity - :data:`CLASSIFY_BATCH` answers a
        run and at most :data:`CLASSIFY_PER_REQUEST` a request.

        It runs later with the caller's role rather than this request's
        limits, so it is started only by the caller in person: not through an
        API key, whose scopes the worker would not carry, nor by an
        administrator impersonating them.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the
                organization, or one asking through an API key or impersonation.
            NotFoundError: For a knowledge base the caller may not change.
            AiAssistanceDisabledError: The organization switched AI assistance off.
            SystemAgentUnavailableError: The classifier cannot run for this caller.
        """
        _require_runs_view(ctx)
        if ctx.api_key_id is not None or current_impersonator() is not None:
            raise AuthorizationError(
                message="Checking answers runs as you, so start it signed in as yourself",
                details={"knowledge_base_id": knowledge_base_id},
            )
        kb = await self._knowledge_base(ctx, knowledge_base_id, edit=True)
        await SystemAgentRunner(self.db).require_runnable(ctx, key=KNOWLEDGE_GAP_CLASSIFIER.key)
        # Imported here: the flow module imports this service.
        from app.worker.tasks.knowledge_gap_tasks import classify_knowledge_gaps_flow

        spawn_after_commit(
            self.db,
            classify_knowledge_gaps_flow(
                organization_id=str(ctx.organization_id),
                knowledge_base_id=str(kb.id),
                user_id=str(ctx.user_id),
            ),
            name=f"classify-knowledge-gaps-{kb.id}",
        )

    async def acting_as(self, *, organization_id: UUID, user_id: UUID) -> AuthContext | None:
        """Who a check runs as: the person who asked for it, with their role as it is now.

        None when they are no longer an active member, so a check never outlives
        the access that asked for it.
        """
        membership = await member_repo.get_active(
            self.db, organization_id=organization_id, user_id=user_id
        )
        if membership is None:
            return None
        return AuthContext(user_id=user_id, organization_id=organization_id, role=membership.role)

    async def classify_batch(self, ctx: AuthContext, knowledge_base_id: UUID) -> tuple[int, int]:
        """Read the next :data:`CLASSIFY_BATCH` answers in one run, and record its verdicts.

        The caller's access is checked again, since a check runs after the
        request that asked for it.

        Returns:
            How many answers were read, and how many of them were misses.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a knowledge base the caller may no longer change.
            AiAssistanceDisabledError: The organization switched AI assistance off.
            SystemAgentUnavailableError: The classifier cannot run for this caller.
            SystemAgentRunError: The run ended without an answer, as a budget
                refusal does; it is recorded.
            SystemAgentOutputError: The classifier answered in a shape that could
                not be read.
        """
        _require_runs_view(ctx)
        kb = await self._knowledge_base(ctx, knowledge_base_id, edit=True)
        candidates = await knowledge_gap_repo.classification_candidates(
            self.db,
            kb.id,
            organization_id=ctx.organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            since=datetime.now(UTC) - CLASSIFY_WINDOW,
            limit=CLASSIFY_BATCH,
        )
        if not candidates:
            return 0, 0
        result = await SystemAgentRunner(self.db).run(
            ctx,
            key=KNOWLEDGE_GAP_CLASSIFIER.key,
            prompt=_classification_prompt(kb.name, candidates),
            output_type=KnowledgeGapClassification,
        )
        verdicts = _verdicts(candidates, result.output.answers)
        # Taken in one order, after the model call, and held to the commit: an
        # erasure of an asker takes the same lock, so it either removed their
        # answer before this reads it or finds the miss to remove afterwards.
        for asker in sorted({v.candidate.asker_id for v in verdicts if v.candidate.asker_id}):
            await hold_subject(self.db, LockScope.PERSONAL_DATA_PER_USER, asker)
        kept = await knowledge_gap_repo.still_asked(
            self.db, [v.candidate for v in verdicts], organization_id=ctx.organization_id
        )
        misses = await knowledge_gap_repo.record_classifications(
            self.db,
            [v for v in verdicts if v.candidate.message_id in kept],
            kb.id,
            organization_id=ctx.organization_id,
            run_id=result.run.id,
        )
        return len(verdicts), misses

    async def waiting_to_be_grouped(self) -> list[tuple[UUID, UUID]]:
        """Every `(organization, knowledge base)` with a miss no topic has taken yet."""
        return await knowledge_gap_repo.knowledge_bases_with_ungrouped_misses(
            self.db, threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY
        )

    async def forget_empty_topics(self) -> int:
        """Remove the topics left with no searches, across the deployment."""
        return await knowledge_gap_repo.delete_empty_topics(self.db)

    async def group_pending(self, *, organization_id: UUID, knowledge_base_id: UUID) -> int:
        """Group up to :data:`GROUPING_BATCH` of a knowledge base's ungrouped misses.

        A knowledge base with no misses waiting costs a query and no embedding
        call. One whose embedding credential cannot be resolved is left as it
        is, and its misses wait for a pass that can embed them.

        A pass holds the knowledge base until its transaction ends, so a
        regroup that overlaps the scheduled pass waits and then finds the
        misses that pass placed already taken.

        Returns:
            How many misses were placed in a topic.
        """
        await hold_subject(self.db, LockScope.KNOWLEDGE_GAPS_PER_KNOWLEDGE_BASE, knowledge_base_id)
        misses = await knowledge_gap_repo.ungrouped_misses(
            self.db,
            knowledge_base_id,
            organization_id=organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            limit=GROUPING_BATCH,
        )
        if not misses:
            return 0
        kb = await knowledge_base_repo.get_by_id(self.db, knowledge_base_id)
        if kb is None or kb.organization_id != organization_id:
            return 0
        resolved = await embeddings_for_collection(kb.collection_name, organization_id)
        if resolved is None:
            logger.warning(
                "knowledge_gaps_not_grouped",
                extra={"knowledge_base_id": str(kb.id), "reason": "no embedding configuration"},
            )
            return 0

        vectors = await self._embed(kb.collection_name, resolved, misses)
        stored = await knowledge_gap_repo.topics_in_space(
            self.db,
            kb.id,
            organization_id=organization_id,
            embedding_model=kb.embedding_model,
        )
        width = len(next(iter(vectors.values())))
        clusters = _assign(
            [(search.id, vectors[search.query]) for search in misses],
            [
                _Cluster(
                    centroid=np.asarray(topic.centroid, dtype=np.float64),
                    size=max(size, 1),
                    topic=topic,
                    searches=[],
                )
                for topic, size in stored
                # A model whose width changed under the same name is another space.
                if len(topic.centroid) == width
            ],
            threshold=TOPIC_SIMILARITY,
        )

        placements: list[tuple[UUID, UUID]] = []
        for cluster in clusters:
            if not cluster.moved:
                continue
            centroid = cluster.centroid.tolist()
            if cluster.topic is None:
                topic = await knowledge_gap_repo.create_topic(
                    self.db,
                    organization_id=organization_id,
                    knowledge_base_id=kb.id,
                    centroid=centroid,
                    embedding_model=kb.embedding_model,
                )
            else:
                topic = await knowledge_gap_repo.update_topic(
                    self.db, topic=cluster.topic, update_data={"centroid": centroid}
                )
            placements.extend((topic.id, search_id) for search_id in cluster.searches)
        await knowledge_gap_repo.add_members(self.db, placements)
        return len(placements)

    @staticmethod
    async def _embed(
        collection_name: str, resolved: ResolvedEmbeddings, misses: list[KnowledgeSearch]
    ) -> dict[str, Vector]:
        """Each distinct query once, in one request, off the event loop."""
        embedder = embedder_for(collection_name, resolved)
        queries = list(dict.fromkeys(search.query for search in misses))
        embedded = await asyncio.to_thread(embedder.embed_queries, queries)
        return {query: _unit(vector) for query, vector in zip(queries, embedded, strict=True)}
