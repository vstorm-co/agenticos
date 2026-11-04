"""A person's decision a workflow run is waiting on - what a `human.approval` step asks.

A tool approval (`ToolApproval`) is a gated call inside an agent run, and it
belongs to that run. This is a step of a workflow asking a person to approve or
reject what the run is about to do, with no agent behind it, so it belongs to
the step's `NodeRun` instead - one row per `NodeRun`, which is what makes the
step's every dispatch find the same request rather than open another.

The request is written with what it asks - a title and the details the step
bound - so the approver decides on exactly what the run will act on. It also
holds what the approver may edit (the proposal) and the version they approved
(the final text, and whether it differs from the proposal), and how much the
approver changed it, measured once when it was decided. A decision
cannot be revisited: the step reads it once, when it wakes.
"""

import enum
import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

ProposalFormat = Literal["text", "markdown"]


class WorkflowApprovalStatus(enum.StrEnum):
    """Where a request stands.

    `EXPIRED` is a request nobody decided before its step's time ran out, and
    `CANCELLED` one whose run was cancelled while it waited: neither was
    decided by anybody, so `decided_by_user_id` stays null.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class WorkflowApproval(Base, TimestampMixin):
    """One step's request for a person's decision, and the decision."""

    __tablename__ = "workflow_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("node_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who may decide it, as user ids; empty means anyone holding
    # `approvals:decide` in the organization.
    approver_user_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WorkflowApprovalStatus.PENDING.value
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    editable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    proposal_format: Mapped[ProposalFormat] = mapped_column(
        String(16), nullable=False, default="text", server_default="text"
    )
    proposal_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    proposal: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Content kept for the run's retention; never written to the audit log.
    final: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # The share of the proposal the approver changed, 0 to 1, scored once when the
    # request was decided and never recomputed. Null: not an approved edit
    # decision, or decided before it was measured.
    edit_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The ways of approving the step offered when it asked, as `{id, label}` in the
    # order given; null when it offered none (every request before choices existed).
    choices: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    # The id of the one the approver took; null for a rejection, an expiry and a
    # request with no choices.
    choice: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name="ck_workflow_approval_status",
        ),
        CheckConstraint(
            "proposal_format IN ('text', 'markdown')",
            name="ck_workflow_approval_proposal_format",
        ),
        CheckConstraint(
            "edit_ratio IS NULL OR (edit_ratio >= 0 AND edit_ratio <= 1)",
            name="ck_workflow_approval_edit_ratio",
        ),
        Index(
            "ix_workflow_approvals_org_workflow_created",
            "organization_id",
            "workflow_id",
            "created_at",
        ),
        # The queue: one organization's pending requests.
        Index("ix_workflow_approvals_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowApproval({self.title!r} on node run {self.node_run_id}: {self.status})>"
