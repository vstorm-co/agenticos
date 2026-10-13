"""Case scores - what the scorers concluded about one run's answer to one case.

A score is written once, by the scorers, and never rewritten by them: the judge's
opinion stays as the judge gave it. A person's verdict is kept beside it in its
own columns and decides the outcome when there is one, so overriding the judge
never erases what the judge said.

Each row keeps the scoring configuration it was computed with, because a
dataset's configuration is not versioned and may change after the score.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CaseScore(Base):
    """One run's answer scored against one case revision."""

    __tablename__ = "case_scores"

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
    case_revision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dataset_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    # `SET NULL`: the score outlives the run it read - a deleted conversation or
    # person takes the run, and the verdict on the case stays.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scoring: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    review_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none"
    )
    human_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    human_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "review_state IN ('none', 'pending', 'done')", name="ck_case_score_review_state"
        ),
        Index("ix_case_scores_dataset_created", "dataset_id", "created_at"),
        Index("ix_case_scores_org_review", "organization_id", "review_state"),
    )

    def __repr__(self) -> str:
        return f"<CaseScore(case={self.case_id}, run={self.run_id}, passed={self.passed})>"
