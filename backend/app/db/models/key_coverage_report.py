"""Which of a dataset's keys none of an agent's sources covers.

The source coverage agent reads the labels of the keys in a dataset version's
`keys` checks beside what the agent's published version can reach - its knowledge
bases, context files, skills and MCP servers - and says, key by key, whether a
source holds it. One report per agent and dataset; the next one replaces it.

**A report holds labels and source names, never a key's value.** A value is copied
from a reference document; the report is read by everyone who may view the agent
and the dataset, so it names what is missing without repeating it.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CoverageStatus(StrEnum):
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class KeyCoverageReport(Base):
    """One agent's coverage of one dataset's keys, or why it could not be judged."""

    __tablename__ = "key_coverage_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Kept after the key is deleted, so a queued job fails rather than regains the
    # issuer's console authority.
    created_by_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CoverageStatus.RUNNING.value
    )
    items: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Sources the agent binds that the requester could not see, so nothing of theirs was read.
    unseen_sources: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Every source the judge was shown: its reasons may draw on any of them, so a reader
    # who may not see one of them reads verdicts without reasons.
    judged_sources: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # What each source read held then, by id: a later read compares, so a report on
    # sources that changed since is out of date.
    source_marks: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Written by this platform, never a provider's message: everyone who may view
    # the report reads it.
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_id", "dataset_id", name="uq_key_coverage_report_pair"),
        CheckConstraint(
            "status IN ('running', 'ready', 'failed')", name="ck_key_coverage_report_status"
        ),
        CheckConstraint("unseen_sources >= 0", name="ck_key_coverage_report_unseen"),
    )

    def __repr__(self) -> str:
        return f"<KeyCoverageReport(agent={self.agent_id}, status={self.status})>"
