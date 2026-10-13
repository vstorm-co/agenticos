"""Knowledge gaps - what agents searched their knowledge bases for and did not find.

`knowledge_searches` holds one row per search an agent made during a run: the
query, the collections searched, how many passages came back and the best
cosine similarity among them. Every search is kept, not only the misses, so a
change to what counts as a miss applies to the searches already made.

A search is user content - the model phrased it from somebody's question - so it
lives exactly as long as the run and the conversation it came from: both foreign
keys cascade, and run retention, conversation deletion and a person's erasure
take it with them.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
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
