"""Knowledge gaps - what agents searched their knowledge bases for and did not find.

`knowledge_searches` holds one row per search an agent made during a run: the
query, the collections searched, how many passages came back and the best
cosine similarity among them. Every search is kept, not only the misses, so a
change to what counts as a miss applies to the searches already made.

A search is user content - the model phrased it from somebody's question - so it
lives exactly as long as the run and the conversation it came from: both foreign
keys cascade, and run retention, conversation deletion and a person's erasure
take it with them.

`knowledge_gap_topics` groups the misses of one knowledge base by meaning, in
that collection's own embedding space, and `knowledge_gap_members` says which
searches a topic holds. A search over two collections is a member of one topic
in each, because their embedding models need not agree. Topics are assigned
incrementally and keep their ids, so a person's decision about one - dismissing
it - is still about the same questions after more arrive.

A topic copies no question. Its name, its count and its examples are read from
the searches it still holds, so when those go with their conversation the topic
has nothing left to say about anybody, and the next grouping pass removes it -
with the draft a model or a person wrote for it, the one text a topic keeps of
its own. A document a person adds from a topic stays in its knowledge base.

A miss need not come from retrieval. When a model reads an answer and finds the
agent said it did not know, or a reader's thumbs-down comment says what was
missing, the answer is recorded as a row here of that `signal`, holding the
person's question as its query, and is grouped like any other miss.
`knowledge_gap_classifications` remembers every answer read that way for each
knowledge base, whatever the verdict, so none is paid for twice, with the
classifier's one-sentence reason - the only text it holds, which goes with the
answer.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GapSignal(StrEnum):
    """What says a question went unanswered."""

    RETRIEVAL = "retrieval"
    """The search found nothing close enough; a miss only below the threshold."""
    ANSWER = "answer"
    """The agent's answer said it did not know."""
    RATING = "rating"
    """A reader rated the answer down, saying what was missing."""


class KnowledgeSearch(Base):
    """One knowledge search made by an agent during a run, or an answer read as a miss."""

    __tablename__ = "knowledge_searches"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The agent that searched, which for a delegate is the delegate, not the run's agent.
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Not foreign keys: a deleted knowledge base leaves an id nothing matches, and
    # its topics go with it.
    knowledge_base_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    top_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=GapSignal.RETRIEVAL.value,
        server_default=GapSignal.RETRIEVAL.value,
    )
    # The answer a classified miss was read from; none for a search.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_knowledge_searches_knowledge_base_ids",
            "knowledge_base_ids",
            postgresql_using="gin",
        ),
        Index(
            "uq_knowledge_searches_message_id",
            "message_id",
            "knowledge_base_ids",
            unique=True,
            postgresql_where=text("message_id IS NOT NULL"),
        ),
        CheckConstraint(
            "signal IN ('retrieval', 'answer', 'rating')", name="ck_knowledge_search_signal"
        ),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeSearch(id={self.id}, run={self.run_id}, top={self.top_similarity})>"


class TopicStatus(StrEnum):
    """Whether a topic still asks for content."""

    OPEN = "open"
    DISMISSED = "dismissed"
    """A person decided it needs nothing. It keeps absorbing its questions, so it
    does not come back as a new topic the next time one is asked."""
    COVERED = "covered"
    """A person added its content to the knowledge base as a document. It keeps
    absorbing its questions like a dismissed topic; once that document is
    deleted, it reads as open again."""


class DraftAuthor(StrEnum):
    """Who wrote a topic's draft: what a person's erasure may take and what it must leave."""

    MODEL = "model"
    PERSON = "person"


class KnowledgeGapTopic(Base):
    """Questions one knowledge base could not answer, grouped by meaning."""

    __tablename__ = "knowledge_gap_topics"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The mean of the members' embeddings. Only comparable with vectors of
    # `embedding_model`: a knowledge base moved to another model starts new topics.
    centroid: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TopicStatus.OPEN.value, server_default="open"
    )
    dismissed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Never added to a knowledge base by the platform; a person checks it and adds a document.
    draft_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_evidence_run_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    draft_evidence_input_hashes: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(64)), nullable=True
    )
    # `{"kind": "document" | "question", "id": ...}`, each verified when it was recorded.
    draft_sources: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    draft_unverified: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # How many different people asked the questions a model's draft was written
    # from; a draft from one person's questions is shown with that warning.
    draft_askers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    drafted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # `model` or `person`, set with the draft's text: its run may be gone with
    # retention while the text stays the model's.
    draft_author: Mapped[str | None] = mapped_column(String(16), nullable=True)
    draft_already_covered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    covered_by_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("rag_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    covered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    covered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'dismissed', 'covered')", name="ck_knowledge_gap_topic_status"
        ),
        CheckConstraint(
            "(draft_content IS NULL) = (draft_author IS NULL) "
            "AND (draft_author IS NULL OR draft_author IN ('model', 'person'))",
            name="ck_knowledge_gap_draft_author",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeGapTopic(id={self.id}, kb={self.knowledge_base_id}, status={self.status})>"
        )


class KnowledgeGapMember(Base):
    """One search held by one topic."""

    __tablename__ = "knowledge_gap_members"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_gap_topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    search_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_searches.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<KnowledgeGapMember(topic={self.topic_id}, search={self.search_id})>"


class KnowledgeGapClassification(Base):
    """One answer a model read for one knowledge base's gaps, and what it decided."""

    __tablename__ = "knowledge_gap_classifications"

    message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # A `GapSignal` other than retrieval, `none`, or `refused` - a rightful refusal of a
    # request outside the agent's rules, whose run's misses are then no gap either.
    signal: Mapped[str] = mapped_column(String(16), nullable=False)
    # User content - a model's words on somebody's answer - so it goes with the answer.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "signal IN ('answer', 'rating', 'none', 'refused')", name="ck_classification_signal"
        ),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeGapClassification(message={self.message_id}, signal={self.signal})>"
