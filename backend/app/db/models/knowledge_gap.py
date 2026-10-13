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

A topic copies no text. Its name, its count and its examples are read from the
searches it still holds, so when those go with their conversation the topic has
nothing left to say about anybody, and the next grouping pass removes it.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeSearch(Base):
    """One knowledge search made by an agent during a run."""

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
    # `None` when nothing came back.
    top_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_knowledge_searches_knowledge_base_ids",
            "knowledge_base_ids",
            postgresql_using="gin",
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
    # `embedding_model`: a collection moved to another model starts new topics.
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('open', 'dismissed')", name="ck_knowledge_gap_topic_status"),
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
