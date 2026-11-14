"""What a step's Quick Log wrote when it settled: one line of a workflow's own log.

A Quick Log is a setting on a step (`NodeInstance.quick_log`), not a node. Each
settled run of the step writes one row, in the transaction that settles it, so
the entry commits or rolls back with the step it describes. The row belongs to
its run and goes with it when run retention deletes the run. The step's label is
a snapshot, so an entry still reads right after the step is renamed or removed.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    case,
    cast,
    false,
    func,
    literal,
    literal_column,
    select,
)
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column

from app.db.base import Base
from app.db.models.workflow import WorkflowVersion
from app.db.models.workflow_run import WorkflowRun

MAX_LOG_MESSAGE_CHARS = 2000
"""The longest rendered message kept: a template is 500 characters, but the output
fields it reads are not, so the text is cut here."""


class WorkflowLogEntry(Base):
    """One settled step run's log line."""

    __tablename__ = "workflow_log_entries"

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
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The step in the graph; no foreign key, a step can be deleted from a later draft.
    node_instance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    step_label: Mapped[str] = mapped_column(String(128), nullable=False)
    # The immutable run graph distinguishes a default name from a custom label,
    # including older lines. Eager selection avoids serialization-time I/O.
    step_definition_id: Mapped[str | None] = column_property(
        select(
            func.jsonb_path_query_first(
                case(
                    (WorkflowRun.workflow_version_id.is_(None), WorkflowRun.draft_graph_snapshot),
                    else_=WorkflowVersion.graph,
                ),
                cast(
                    literal(
                        "$.nodes[*] ? (@.id == $node_id && "
                        '(!exists(@.label) || @.label == null || @.label == "")).definition_id'
                    ),
                    JSONPATH,
                ),
                func.jsonb_build_object("node_id", cast(node_instance_id, String)),
            ).op("#>>", return_type=String)(literal_column("'{}'::text[]"))
        )
        .select_from(WorkflowRun)
        .outerjoin(
            WorkflowVersion,
            (WorkflowVersion.id == WorkflowRun.workflow_version_id)
            & (WorkflowVersion.organization_id == WorkflowRun.organization_id),
        )
        .where(WorkflowRun.id == run_id, WorkflowRun.organization_id == organization_id)
        .correlate_except(WorkflowRun, WorkflowVersion)
        .scalar_subquery()
    )
    # The port the step left by, or `error`; several ports are joined with a comma.
    outcome: Mapped[str] = mapped_column(String(256), nullable=False)
    # The step's settled status: `succeeded` or `failed`.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_test: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    """The order lines were written in: the database numbers them as they are inserted, so
    it holds where `created_at` cannot (a clock that steps back, two lines in one instant)."""

    __table_args__ = (
        Index(
            "ix_workflow_log_entries_org_workflow_created",
            "organization_id",
            "workflow_id",
            created_at.desc(),
        ),
        Index("ix_workflow_log_entries_run", "run_id"),
        Index("ix_workflow_log_entries_run_seq", "run_id", "seq"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowLogEntry({self.step_label!r} -> {self.outcome!r} in run {self.run_id})>"
