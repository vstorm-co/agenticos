"""Knowledge gaps: the questions a knowledge base could not answer, grouped into topics.

Agents record every knowledge search they make (see
`app.agents.capabilities.knowledge`). A search that returned nothing, or nothing
as similar to the query as `KNOWLEDGE_GAP_MIN_SIMILARITY`, is a *miss*. Misses
are grouped per knowledge base by the meaning of the query, in that
collection's own embedding space, into topics a person can act on: add the
missing document, or turn the questions into dataset cases to check it.

Grouping embeds queries but asks no model to write anything, so it runs for
every organization, like ingestion embeddings do.

A model is asked only on request, as the person asking: to draft a topic's
missing passage, or to read a knowledge base's recent answers - and the
thumbs-down comments on them - for the questions it could not answer, which
retrieval alone does not see.

A document reaches a knowledge base only when a person with edit access to it
adds a topic's content, drafted or their own. The drafter is shown the
questions with what identifies people taken out, and content that still repeats
a number or code from them, or holds personal data, is added only once that
person confirms it.
"""

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import numpy as np
import numpy.typing as npt
from pydantic_ai_harness.guardrails.detectors import redact_secrets
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.knowledge._log import MAX_QUERY_CHARS
from app.agents.spec import AgentSpec
from app.agents.system_agents import KNOWLEDGE_GAP_CLASSIFIER, KNOWLEDGE_GAP_DRAFTER
from app.core.audit import current_impersonator, record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    IdentifyingContentError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm, Scope
from app.core.phone import phone_text_error
from app.db.locks import LockScope, hold_subject
from app.db.models.context import ContextFile
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import (
    DraftAuthor,
    GapSignal,
    KnowledgeGapTopic,
    KnowledgeSearch,
    TopicStatus,
)
from app.db.models.rag_document import RAGDocument
from app.repositories import (
    agent_repo,
    context_repo,
    knowledge_base_repo,
    knowledge_gap_repo,
    member_repo,
)
from app.repositories.knowledge_gap import (
    REFUSED,
    CandidateRow,
    DraftingRow,
    QuestionRow,
    TopicRow,
    Verdict,
)
from app.schemas.knowledge_gap import (
    MAX_DRAFT_SOURCES,
    ClassifiedAnswer,
    DecidedStatusLiteral,
    KnowledgeGapAgent,
    KnowledgeGapCasesAdded,
    KnowledgeGapClassification,
    KnowledgeGapCollectionCount,
    KnowledgeGapContent,
    KnowledgeGapContentAdd,
    KnowledgeGapDocument,
    KnowledgeGapDraft,
    KnowledgeGapDraftRead,
    KnowledgeGapFlag,
    KnowledgeGapQuestion,
    KnowledgeGapReport,
    KnowledgeGapSource,
    KnowledgeGapSourceRead,
    KnowledgeGapTopicDetail,
    KnowledgeGapTopicList,
    KnowledgeGapTopicRead,
    TopicStatusLiteral,
)
from app.services.access import AGENT, CONTEXT, resolve_access
from app.services.collection_access import readable_kb, writable_kb
from app.services.context import ContextService
from app.services.dataset import DatasetService
from app.services.embedding_resolution import ResolvedEmbeddings, embeddings_for_collection
from app.services.ml import pii
from app.services.rag.vectorstore import BaseVectorStore, embedder_for
from app.services.rag_document import RAGDocumentService
from app.services.system_agent_runner import SystemAgentRunner

logger = logging.getLogger(__name__)

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

DRAFT_CONTEXT_FILES = 10
"""The most of the agents' context files a drafting model is shown."""

DRAFT_CONTEXT_CHARS = 4_000
"""How much of each context file a drafting model is shown."""


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


def _require_open(row: TopicRow) -> None:
    """Refuse writing a topic's content unless it is open: dismissing or covering it was a
    decision, which reopening undoes first."""
    if row.status != TopicStatus.OPEN.value:
        raise BadRequestError(
            message="Reopen this topic before you write its content",
            details={"topic_id": row.topic.id, "status": row.status},
        )


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


_TOKEN = re.compile(r"[^\W_][\w-]*")

_NUMBER = "[number]"


def _identifying(token: str) -> bool:
    """Whether a token reads like an order, account or ticket number rather than a fact.

    Four digits or more, or three with a letter: `7781`, `ORD-123`. A figure a
    policy states - `30` days, `$500` - is shorter, and is kept.
    """
    digits = sum(character.isdigit() for character in token)
    return digits >= 4 or (digits >= 3 and any(character.isalpha() for character in token))


def _personal_data_out(text: str) -> str:
    """Text with credentials and the personal data the detectors find taken out."""
    return pii.scan(_redacted(text)).redacted_text


def _private(text: str) -> str:
    """People's text as a drafting model is shown it, with what identifies them taken out.

    Credentials, the personal data the detectors find - e-mail addresses,
    phone, card and account numbers - and every identifying number or code.
    Applied to what the drafter reads, never to what a person writes.
    """
    found = _personal_data_out(text)
    return _TOKEN.sub(
        lambda match: _NUMBER if _identifying(match.group(0)) else match.group(0), found
    )


def _identifying_tokens(texts: list[str]) -> dict[str, str]:
    """Each identifying token in these texts, by its lower case, as first written."""
    found: dict[str, str] = {}
    for text in texts:
        for token in _TOKEN.findall(text):
            if _identifying(token):
                found.setdefault(token.lower(), token)
    return found


def _flags(text: str, *, sources: list[str], known: list[str]) -> list[KnowledgeGapFlag]:
    """What in content for a knowledge base may identify somebody.

    Personal data the detectors find, wherever it came from, and each
    identifying number or code the content repeats from `sources` - people's
    questions, answers and comments - unless `known`, the agents' context
    files, states it too.
    """
    categories = (
        None
        if phone_text_error(text, pii.PHONE_REGIONS) is None
        else [name for name in pii.known_categories() if name != pii.PHONE]
    )
    report = pii.scan(text, categories=categories)
    flags = [
        KnowledgeGapFlag(kind="personal_data", value=entry.category, count=entry.count)
        for entry in report.counts
        if entry.count
    ]
    written = Counter(token.lower() for token in _TOKEN.findall(text) if _identifying(token))
    shared = written.keys() & _identifying_tokens(sources).keys()
    shared -= _identifying_tokens(known).keys()
    first = _identifying_tokens([text])
    flags.extend(
        KnowledgeGapFlag(kind="shared", value=first[token], count=written[token])
        for token in sorted(shared)
    )
    return flags


_BLANK = re.compile(r"\{\{([^{}]{1,200})\}\}")


def _blanks(text: str) -> list[str]:
    """The details content still asks somebody to fill in, each written `{{...}}`."""
    return list(dict.fromkeys(blank.strip() for blank in _BLANK.findall(text) if blank.strip()))


_UNSAFE_NAME = re.compile(r"[^\w-]+")


def _filename(title: str) -> str:
    stem = _UNSAFE_NAME.sub("-", title.lower()).strip("-_")[:80].strip("-_")
    return f"{stem or 'knowledge-gap'}.md"


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
    knowledge_base: str,
    material: list[DraftingRow],
    documents: list[RAGDocument],
    context_files: list[ContextFile],
) -> str:
    """The questions a draft is for, and the documents and context files it may cite, numbered.

    The rules are here rather than only in the drafter's instructions, which
    the organization may edit: what reaches a knowledge base reaches everybody
    its agents answer.
    """
    parts = [
        f'The knowledge base "{knowledge_base}" could not answer these questions. Draft the '
        "passage that would answer them, as general knowledge for everybody who asks - never "
        "about one person, order or case.\n"
        "- Write consistently with the context files below: they are rules the agent already "
        "follows. When a context file or a document already answers the questions, set "
        "`already_covered`, cite it, and say in the content which one answers them instead of "
        "repeating it.\n"
        "- Where the answer needs a fact you are not given - a figure, a date, a name, a rule "
        "- write `{{what to fill in}}` in its place, such as {{refund window in days}}. Never "
        "invent one, and never use square brackets for it.\n"
        f"- What identified people was replaced with [redacted:...] and {_NUMBER}; leave it "
        "out.\n"
        "In `questions`, list the numbers of the questions your draft answers; in `documents` "
        "and `context_files`, the numbers of those below your draft builds on or that answer "
        "the questions. Cite only numbers listed here.",
    ]
    if context_files:
        parts.append(
            "## Context files the agent reads\n"
            + "\n\n".join(
                f"### Context file {n}: {file.name}\n{_clip(file.content, DRAFT_CONTEXT_CHARS)}"
                for n, file in enumerate(context_files, start=1)
            )
        )
    if documents:
        parts.append(
            "## Documents the agent found\n"
            + "\n".join(f"{n}. {doc.filename}" for n, doc in enumerate(documents, start=1))
        )
    for number, row in enumerate(material, start=1):
        parts.append(
            f"## Question {number}\n"
            f"Asked: {_private(_clip(row.question, 1_000))}\n"
            f"Searched for: {_private(_clip(row.search.query, 500))}\n"
            f"Found: {_personal_data_out(_clip(row.found, 2_000))}\n"
            f"Answered: {_private(_clip(row.answer, 1_500))}\n"
            f"Reader's comment: {_private(_clip(row.down_rating_comment, 500))}"
        )
    return "\n\n".join(parts)


def _classification_prompt(knowledge_base: str, candidates: list[CandidateRow]) -> str:
    """The answers a classifying model reads, each numbered, and how to label each.

    The rules are here rather than only in the classifier's instructions, which
    the organization may edit: they decide what is stored as a gap.
    """
    parts = [
        f'An agent answered these questions; the knowledge base "{knowledge_base}" is '
        "one of the places it looks things up. Find the answers that show this knowledge "
        "base is missing content. Label every answer, citing it by its number:\n"
        "- `did_not_know`: the answer says, in any words or language, that the agent "
        "does not know, could not find the information, or has nothing on it.\n"
        "- `missing_information`: the answer does not say so, but a reader's comment "
        "says the information it needed was missing, outdated or incomplete - content "
        "to add or bring up to date.\n"
        "- `refused`: the question asked for what the agent's rules or purpose do not allow - "
        "to ignore its instructions, grant an exception, or help with something it is not "
        "for - and the answer rightly refused. A question the agent should answer, refused "
        "because it had no information, is `did_not_know`, not `refused`.\n"
        "- `no_gap`: anything else. An answer that applied a policy or a rule wrongly is "
        "`no_gap`: the rule was there and the agent misused it. So is a comment about "
        "that, about tone, length or format, or saying the answer should have refused, "
        "and so is a refusal of something the rules allow.",
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


_VERDICTS: dict[str, tuple[str, GapSignal | None]] = {
    "did_not_know": (GapSignal.ANSWER.value, GapSignal.ANSWER),
    "missing_information": (GapSignal.RATING.value, GapSignal.RATING),
    "no_gap": ("none", None),
    "refused": (REFUSED, None),
}
"""What each of the classifying model's labels is remembered as, and the miss it records."""


def _verdicts(candidates: list[CandidateRow], answers: list[ClassifiedAnswer]) -> list[Verdict]:
    """The verdicts on the candidates the model numbered, the first one each.

    A number that names no candidate is dropped, and a candidate the model
    skipped gets no verdict, so it waits for the next check rather than being
    remembered as read. A run whose search already missed records no second
    miss: it is counted once, and the verdict is remembered.
    """
    decided: dict[int, ClassifiedAnswer] = {}
    for answer in answers:
        if 1 <= answer.number <= len(candidates):
            decided.setdefault(answer.number, answer)
    verdicts: list[Verdict] = []
    for number, answer in sorted(decided.items()):
        candidate = candidates[number - 1]
        verdict, signal = _VERDICTS[answer.signal]
        verdicts.append(
            Verdict(
                candidate=candidate,
                verdict=verdict,
                signal=None if candidate.missed else signal,
                query=(candidate.question or candidate.answer)[:MAX_QUERY_CHARS],
            )
        )
    return verdicts


def _covering(document: RAGDocument) -> KnowledgeGapDocument:
    return KnowledgeGapDocument(id=document.id, filename=document.filename, status=document.status)


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
        covered = {
            row.topic.id: document_id
            for row in rows
            if row.status == TopicStatus.COVERED.value
            and (document_id := row.topic.covered_by_document_id) is not None
        }
        documents = await knowledge_gap_repo.documents_by_id(
            self.db, list(covered.values()), organization_id=ctx.organization_id
        )
        covering = {topic_id: _covering(documents[doc]) for topic_id, doc in covered.items()}
        return [
            KnowledgeGapTopicRead(
                id=row.topic.id,
                knowledge_base_id=row.topic.knowledge_base_id,
                knowledge_base_name=bases[row.topic.knowledge_base_id].name,
                status=TopicStatus(row.status).value,
                label=row.queries[0] if row.queries else "",
                question_count=row.question_count,
                asker_count=row.asker_count,
                last_asked_at=row.last_asked_at,
                examples=_distinct(row.queries, keep=EXAMPLES),
                agents=[agents[a] for a in row.agent_ids if a in agents],
                dismissed_at=row.topic.dismissed_at,
                covered_at=row.topic.covered_at
                if row.status == TopicStatus.COVERED.value
                else None,
                covered_by=covering.get(row.topic.id),
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
        row = await self._row(ctx, topic)
        questions = await knowledge_gap_repo.list_questions(
            self.db,
            topic.id,
            organization_id=ctx.organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            agent_id=None,
            limit=TOPIC_QUESTIONS,
        )
        agents = await self._agents(ctx, sorted({q.search.agent_id for q in questions}))
        [summary] = await self._reads(ctx, [row])
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
            draft=await self._draft_read(ctx, topic, row, questions if summary.can_edit else None),
        )

    async def _row(self, ctx: AuthContext, topic: KnowledgeGapTopic) -> TopicRow:
        """What a topic's searches add up to now.

        Raises:
            NotFoundError: When every question it held is gone, or no longer
                counts as a miss.
        """
        rows, _ = await knowledge_gap_repo.list_topics(
            self.db,
            organization_id=ctx.organization_id,
            knowledge_base_ids=[topic.knowledge_base_id],
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            status=None,
            agent_id=None,
            topic_id=topic.id,
            skip=0,
            limit=1,
        )
        if not rows:
            raise NotFoundError(message="Topic not found", details={"topic_id": topic.id})
        return rows[0]

    async def _context_files(self, ctx: AuthContext, agent_ids: list[UUID]) -> list[ContextFile]:
        """The enabled context files these agents' published versions read, as the caller may.

        An agent reads its context files whoever runs it; a draft quotes them back
        to the caller, so only the files the caller may view are taken.
        """
        agents = await agent_repo.get_many(self.db, agent_ids, organization_id=ctx.organization_id)
        bound: list[UUID] = []
        for agent_id in sorted(agents):
            version_id = agents[agent_id].current_version_id
            version = (
                await agent_repo.get_version(
                    self.db, version_id, organization_id=ctx.organization_id
                )
                if version_id is not None
                else None
            )
            if version is not None:
                bound.extend(AgentSpec.model_validate(version.spec).context_ids)
        resolved = await ContextService(self.db).resolve_for_agent(ctx, list(dict.fromkeys(bound)))
        readable = [
            file
            for file in resolved
            if await resolve_access(self.db, ctx, file, Perm.CONTEXT_VIEW, resource_type=CONTEXT)
        ]
        return readable[:DRAFT_CONTEXT_FILES]

    async def _flags(
        self, ctx: AuthContext, row: TopicRow, questions: list[QuestionRow], text: str
    ) -> list[KnowledgeGapFlag]:
        sources = await knowledge_gap_repo.source_texts(self.db, questions)
        known = [file.content for file in await self._context_files(ctx, row.agent_ids)]
        return _flags(text, sources=sources, known=known)

    async def draft(self, ctx: AuthContext, topic_id: UUID) -> KnowledgeGapTopicDetail:
        """Ask the drafting agent for the passage a topic's questions need, and keep it.

        One run of the organization's seeded knowledge-gap drafter, as the caller:
        refused while the organization has AI assistance switched off, metered
        against the drafter's and the organization's budgets, and listed in
        Activity. It is shown the topic's newest questions, the answers they got,
        what each search returned and what readers said - with what identifies
        people taken out - and the context files of the agents that were asked,
        those the caller may read. What it writes is kept on the topic as a
        draft for a person; nothing is added to the knowledge base. It replaces
        the topic's draft, so it takes what dismissing does: a caller who may
        change the topic's knowledge base.

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
        context_files = await self._context_files(
            ctx, list(dict.fromkeys(row.search.agent_id for row in material))
        )
        result = await SystemAgentRunner(self.db).run(
            ctx,
            key=KNOWLEDGE_GAP_DRAFTER.key,
            prompt=_drafting_prompt(kb.name, material, documents, context_files),
            output_type=KnowledgeGapDraft,
        )
        cited_documents, unknown_documents = _cited(result.output.documents, documents)
        cited_questions, unknown_questions = _cited(
            result.output.questions, [row.search for row in material]
        )
        cited_context, unknown_context = _cited(result.output.context_files, context_files)
        await self.record_draft(
            ctx,
            KnowledgeGapReport(
                topic_id=topic.id,
                title=result.output.title,
                content=result.output.content,
                sources=[
                    *(KnowledgeGapSource(kind="document", id=doc.id) for doc in cited_documents),
                    *(KnowledgeGapSource(kind="question", id=s.id) for s in cited_questions),
                    *(KnowledgeGapSource(kind="context", id=f.id) for f in cited_context),
                ],
                already_covered=result.output.already_covered,
            ),
            run_id=result.run.id,
            unverified=unknown_documents + unknown_questions + unknown_context,
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
        question must be one of the topic's searches, a context file must be one
        the caller may read. One that is not is left
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
        context_files = await self._readable_context(
            ctx, [source_id for kind, source_id in named if kind == "context"]
        )
        verified = [
            {"kind": kind, "id": str(source_id)}
            for kind, source_id in named
            if (kind == "document" and source_id in documents)
            or (kind == "question" and source_id in questions)
            or (kind == "context" and source_id in context_files)
        ]
        await knowledge_gap_repo.update_topic(
            self.db,
            topic=topic,
            update_data={
                "draft_title": _redacted(report.title),
                "draft_content": _redacted(report.content),
                "draft_sources": verified[:MAX_DRAFT_SOURCES],
                "draft_unverified": unverified + len(named) - len(verified),
                "draft_already_covered": report.already_covered,
                "draft_author": DraftAuthor.MODEL.value,
                "draft_run_id": run_id,
                "drafted_by_user_id": ctx.user_id,
                "drafted_at": datetime.now(UTC),
            },
        )

    async def _readable_context(
        self, ctx: AuthContext, context_ids: list[UUID]
    ) -> dict[UUID, ContextFile]:
        """The organization's context files among these ids that the caller may read."""
        found = await context_repo.get_many(
            self.db, context_ids, organization_id=ctx.organization_id
        )
        return {
            file_id: file
            for file_id, file in found.items()
            if await resolve_access(self.db, ctx, file, Perm.CONTEXT_VIEW, resource_type=CONTEXT)
        }

    async def _draft_read(
        self,
        ctx: AuthContext,
        topic: KnowledgeGapTopic,
        row: TopicRow,
        asked: list[QuestionRow] | None,
    ) -> KnowledgeGapDraftRead | None:
        """A topic's draft, with each source named - and left out if it is gone since.

        With what is still to fill in, and what may identify somebody when the
        topic's questions are `asked`: only somebody who may add it is shown that.
        """
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
        context_files = await self._readable_context(
            ctx, [UUID(s["id"]) for s in topic.draft_sources if s["kind"] == "context"]
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
            elif source["kind"] == "context" and source_id in context_files:
                sources.append(
                    KnowledgeGapSourceRead(
                        kind="context", id=source_id, label=context_files[source_id].name
                    )
                )
        title = topic.draft_title or ""
        return KnowledgeGapDraftRead(
            title=title,
            content=topic.draft_content,
            sources=sources,
            unverified=topic.draft_unverified,
            drafted_at=topic.drafted_at,
            run_id=topic.draft_run_id,
            already_covered=topic.draft_already_covered,
            blanks=_blanks(f"{title}\n{topic.draft_content}"),
            flags=[]
            if asked is None
            else await self._flags(ctx, row, asked, f"{title}\n{topic.draft_content}"),
        )

    async def save_content(
        self, ctx: AuthContext, topic_id: UUID, data: KnowledgeGapContent
    ) -> KnowledgeGapTopicDetail:
        """Keep what a person wrote, or kept of a draft, as the topic's content.

        Nothing is added to the knowledge base. It replaces the draft's text, so
        it takes what drafting does: a caller who may change the topic's
        knowledge base. Any credential the text holds is redacted; nothing else
        a person writes is changed.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a topic in a knowledge base the caller may not change.
            BadRequestError: For a topic that is not open: reopen it first.
        """
        _require_runs_view(ctx)
        topic = await self._topic(ctx, topic_id, edit=True)
        _require_open(await self._row(ctx, topic))
        await self._keep(ctx, topic, data)
        return await self.read(ctx, topic.id)

    async def _keep(
        self, ctx: AuthContext, topic: KnowledgeGapTopic, data: KnowledgeGapContent
    ) -> KnowledgeGapTopic:
        """Replace a topic's draft text with a person's.

        A model's draft kept as it was stays the model's, with its run and its
        sources. Changed, it is the person's: what the model cited and found no
        longer speaks for it.
        """
        title, content = _redacted(data.title), _redacted(data.content)
        if (title, content) == (topic.draft_title, topic.draft_content):
            return topic
        return await knowledge_gap_repo.update_topic(
            self.db,
            topic=topic,
            update_data={
                "draft_title": title,
                "draft_content": content,
                "draft_sources": [],
                "draft_unverified": 0,
                "draft_already_covered": False,
                "draft_author": DraftAuthor.PERSON.value,
                "draft_run_id": None,
                "drafted_by_user_id": ctx.user_id,
                "drafted_at": datetime.now(UTC),
            },
        )

    async def add_content(
        self,
        ctx: AuthContext,
        topic_id: UUID,
        data: KnowledgeGapContentAdd,
        *,
        vector_store: BaseVectorStore,
    ) -> KnowledgeGapTopicDetail:
        """Add a topic's content to its knowledge base as a document, and mark the topic covered.

        The content is kept as the topic's draft and uploaded as a Markdown
        document through the same path a file upload takes - the budget, the
        embedding model and the parsing queue - recorded as added from the
        topic by the caller. Adding changes the knowledge base, so it takes a
        caller who may change it, by their role or a grant on it, and it is
        audited.

        Content still asking for a detail to fill in, written `{{...}}`, is
        refused. So is content flagged as possibly identifying somebody -
        personal data, or a number or code it repeats from people's questions -
        unless the caller confirms each flag it holds now, with at least as many
        matches: one that appeared since the caller looked - a new category, or
        more of one - is not confirmed by having confirmed the others.
        A topic covered by a document already takes no second one.

        Raises:
            AuthorizationError: For a caller without `runs:view` across the organization.
            NotFoundError: For a topic in a knowledge base the caller may not
                change, or one with no questions left.
            AlreadyExistsError: For a topic a document covers already.
            BadRequestError: For a dismissed topic; naming `title` or `content`, for a
                detail still to fill in, or for content with more digits than the
                phone number check reads.
            IdentifyingContentError: For a flag the caller did not confirm.
        """
        _require_runs_view(ctx)
        topic = await self._topic(ctx, topic_id, edit=True)
        kb = await self._knowledge_base(ctx, topic.knowledge_base_id, edit=True)
        # Held to the commit, so two additions at once find the first one's document.
        topic = await knowledge_gap_repo.lock_topic(self.db, topic)
        row = await self._row(ctx, topic)
        if row.status == TopicStatus.COVERED.value:
            raise AlreadyExistsError(
                message="A document covers this topic already; reopen it to add another",
                details={"topic_id": topic.id, "document_id": topic.covered_by_document_id},
            )
        _require_open(row)
        for field, value in (("title", data.title), ("content", data.content)):
            blanks = _blanks(value)
            if blanks:
                raise refused_field(
                    field, f"Fill in or remove what is still to fill in: {', '.join(blanks)}"
                )
        text = f"{data.title}\n{data.content}"
        if phone_text_error(text, pii.PHONE_REGIONS) is not None:
            raise refused_field(
                "content",
                "This holds more digits than can be checked for phone numbers; split it "
                "into smaller documents.",
            )
        questions = await knowledge_gap_repo.list_questions(
            self.db,
            topic.id,
            organization_id=ctx.organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            agent_id=None,
            limit=None,
        )
        flags = await self._flags(ctx, row, questions, text)
        confirmed = {(flag.kind, flag.value): flag.count for flag in data.confirmed}
        if any(confirmed.get((flag.kind, flag.value), 0) < flag.count for flag in flags):
            raise IdentifyingContentError(
                details={"flags": [flag.model_dump(mode="json") for flag in flags]}
            )
        topic = await self._keep(ctx, topic, data)
        title, content = topic.draft_title or "", topic.draft_content or ""
        uploaded = await RAGDocumentService(self.db).dispatch_upload(
            ctx=ctx,
            collection=kb,
            file_data=f"# {title}\n\n{content}\n".encode(),
            filename=_filename(title),
            replace=False,
            vector_store=vector_store,
            organization_id=ctx.organization_id,
            knowledge_base_id=kb.id,
            knowledge_gap_topic_id=topic.id,
        )
        document_id = UUID(uploaded.id)
        await knowledge_gap_repo.update_topic(
            self.db,
            topic=topic,
            update_data={
                "status": TopicStatus.COVERED.value,
                "covered_by_document_id": document_id,
                "covered_by_user_id": ctx.user_id,
                "covered_at": datetime.now(UTC),
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="knowledge_gap.content_added",
            target_type="knowledge_gap_topic",
            target_id=str(topic.id),
            details={
                "knowledge_base_id": str(kb.id),
                "document_id": str(document_id),
                "flags": len(flags),
                "confirmed_identifying": bool(flags),
            },
        )
        return await self.read(ctx, topic.id)

    async def set_status(
        self, ctx: AuthContext, topic_id: UUID, status: DecidedStatusLiteral
    ) -> KnowledgeGapTopicDetail:
        """Dismiss a topic that needs no content, or reopen one - a covered one too.

        A dismissed topic keeps taking the questions that belong to it, so it
        does not come back as a new topic the next time one is asked. Either
        leaves the topic no longer covered; the document stays in the
        knowledge base.

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
                "covered_by_document_id": None,
                "covered_by_user_id": None,
                "covered_at": None,
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
        # Imported here: the task module imports this service.
        from app.worker.tasks.knowledge_gap_tasks import group_knowledge_gaps

        spawn_after_commit(
            self.db,
            group_knowledge_gaps(
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
        # Imported here: the task module imports this service.
        from app.worker.tasks.knowledge_gap_tasks import classify_knowledge_gaps

        spawn_after_commit(
            self.db,
            classify_knowledge_gaps(
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
            threshold=settings.KNOWLEDGE_GAP_TOPIC_SIMILARITY,
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
