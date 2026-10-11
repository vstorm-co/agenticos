"""A person's decision a workflow run is waiting on - what a `human.approval` step asks.

A tool approval (`ToolApproval`) is a gated call inside an agent run, and it
belongs to that run. This is a step of a workflow asking a person to approve or
reject what the run is about to do, with no agent behind it, so it belongs to
the step's `NodeRun` instead - one row per `NodeRun`, which is what makes the
step's every dispatch find the same request rather than open another.

The request is written with what it asks - a title and the details the step
bound - so the approver decides on exactly what the run will act on. A decision
cannot be revisited: the step reads it once, when it wakes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


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

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name="ck_workflow_approval_status",
        ),
        # The queue: one organization's pending requests.
        Index("ix_workflow_approvals_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowApproval({self.title!r} on node run {self.node_run_id}: {self.status})>"
