"""A step's evals: cases a model step is tried on, and the runs that tried them.

An eval case is one input a step that asks a model is expected to handle, and
what its answer should then say. Trying a step's cases starts one test run of
the step per case - the same request **Test step** makes, with the case's input
and the known output of the steps before it - and records which run tried which
case. Whether a case passed is read off its run when asked, never stored: a run
still going has no verdict yet, and the verdict is only ever what the run did.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WorkflowStepEval(Base, TimestampMixin):
    """One case a model step is tried on, and what its answer should say."""

    __tablename__ = "workflow_step_evals"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The step in the draft. A case outlives its step being deleted, and says
    # so, rather than vanishing with work somebody wrote.
    node_instance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Where the case sits among its step's, in the order they were written.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # What the test run starts with, and the known output of the steps before it,
    # by step id - **Test step**'s own two inputs.
    run_input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # `{kind, field, value}` - see `app.schemas.workflow_eval.EvalExpectation`.
    expectation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (Index("ix_workflow_step_eval_step", "workflow_id", "node_instance_id"),)


class WorkflowEvalRun(Base):
    """One try of a step's cases: which test run tried which case, as it stood."""

    __tablename__ = "workflow_eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_instance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    started_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # One entry a case: `{eval_id, name, expectation, workflow_run_id, refused}` -
    # the expectation as it was when tried, so editing a case later does not
    # change what an earlier try was judged by.
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_workflow_eval_run_step", "workflow_id", "node_instance_id", "created_at"),
    )
