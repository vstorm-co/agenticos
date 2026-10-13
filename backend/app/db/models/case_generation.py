"""Generated test cases - drafted by the case generator, decided by a person.

A generation is one request to draft cases for a dataset: which agent they test,
which sources they come from, and the generator run that drafted them. What it
drafted waits in `case_proposals` until somebody accepts or dismisses it; nothing
reaches the dataset before that.

**A decision deletes the proposal.** An accepted one becomes a case in a new
dataset version, and that version is the record of it; a dismissed one leaves
nothing behind. A proposal taken from a conversation is a copy of what somebody
wrote, and keeping the ones nobody chose to keep would be keeping personal data
for no purpose. The generation keeps the counts.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.dataset import ToolOrderMode


class CaseOrigin(StrEnum):
    """What a generated case was drafted from - one per source a person can pick."""

    AGENT = "agent"
    """The agent's instructions, skills and tools."""

    KNOWLEDGE = "knowledge"
    """A passage of a document in the agent's knowledge base."""

    CONVERSATION = "conversation"
    """A question somebody asked the agent, paraphrased or made harder."""

    RED_TEAM = "red_team"
    """A request the agent should refuse."""


class GenerationStatus(StrEnum):
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class CaseGeneration(Base):
    """One request to draft cases for a dataset, and how it went."""

    __tablename__ = "case_generations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sources: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GenerationStatus.RUNNING.value
    )
    # Written by this platform, never a provider's or a library's message: it is
    # shown to everyone who may edit the dataset.
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The generator's run - its cost, its tokens and its place in Activity.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proposed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    accepted_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    dismissed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'ready', 'failed')", name="ck_case_generation_status"
        ),
        CheckConstraint("requested_count >= 1", name="ck_case_generation_requested_count"),
        CheckConstraint(
            "proposed_count >= 0 AND accepted_count >= 0 AND dismissed_count >= 0",
            name="ck_case_generation_counts",
        ),
    )

    def __repr__(self) -> str:
        return f"<CaseGeneration(dataset={self.dataset_id}, status={self.status})>"


class CaseProposal(Base):
    """One drafted case waiting for a person's decision.

    The content columns are a dataset case's, so accepting one copies them as
    they are. The provenance columns say what it was drafted from and are
    `SET NULL` for the same reason a case's are.
    """

    __tablename__ = "case_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("case_generations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    counter_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    order_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ToolOrderMode.ANY.value, server_default="any"
    )
    checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("rag_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "origin IN ('agent', 'knowledge', 'conversation', 'red_team')",
            name="ck_case_proposal_origin",
        ),
        CheckConstraint(
            "order_mode IN ('any', 'in_order', 'exact')", name="ck_case_proposal_order_mode"
        ),
    )

    def __repr__(self) -> str:
        return f"<CaseProposal(dataset={self.dataset_id}, origin={self.origin})>"
