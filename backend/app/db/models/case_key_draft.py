"""Keys drafted from a case's reference answer, waiting for a person.

The key extractor reads the reference answer of one case revision and lists the
facts it holds, each as a label and a value. Nothing reaches the case until a
person takes the draft into the case's keys check and saves it.

**A draft is short-lived.** Its values are copied from the reference answer, so
it is deleted once it is used or dismissed, replaced by the next one for the same
case, deleted with its dataset, and deleted when its case is anonymised. One
nobody acts on is deleted `KEY_DRAFT_RETENTION_DAYS` after it was requested.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

KEY_DRAFT_RETENTION_DAYS = 7


class KeyDraftStatus(StrEnum):
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class CaseKeyDraft(Base):
    """The keys the extractor drafted for one case, or why it could not."""

    __tablename__ = "case_key_drafts"

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
    )
    # The case across its revisions, as `DatasetCase.case_id`.
    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # The revision whose reference answer was read.
    revision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dataset_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
        String(16), nullable=False, default=KeyDraftStatus.RUNNING.value
    )
    keys: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Written by this platform, never a provider's message: everyone who may edit
    # the dataset reads it.
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
        UniqueConstraint("dataset_id", "case_id", name="uq_case_key_draft_case"),
        CheckConstraint(
            "status IN ('running', 'ready', 'failed')", name="ck_case_key_draft_status"
        ),
    )

    def __repr__(self) -> str:
        return f"<CaseKeyDraft(case={self.case_id}, status={self.status})>"
