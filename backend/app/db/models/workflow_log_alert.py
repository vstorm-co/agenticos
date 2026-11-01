"""Alert rules on a workflow's log, and the record of each time one fired.

A rule counts the lines a workflow's Quick Logs wrote in a window and, when enough of
them match, tells its audience. It is a setting of the workflow, so it goes with the
workflow and the organization. `last_fired_at` is what keeps a rule to one alert per
window; each alert also leaves a firing row, the rule's history.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

LOG_ALERT_WINDOWS = (5, 15, 30, 60, 240, 1440)
"""The windows, in minutes, a rule may count over."""


class WorkflowLogAlertRule(Base, TimestampMixin):
    """One rule: which log lines to count, over what window, and who hears of it."""

    __tablename__ = "workflow_log_alert_rules"

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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # The ports (or `error`) a line left by; a line counts when it left by any of them.
    outcomes: Mapped[list[str]] = mapped_column(PG_ARRAY(String(64)), nullable=False)
    # The step in the graph; no foreign key, a step can be deleted from a later draft.
    node_instance_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    message_contains: Mapped[str | None] = mapped_column(String(200), nullable=True)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # `admins`, `owner` and `chosen`, as an agent alert's audience names them.
    audience: Mapped[list[str]] = mapped_column(PG_ARRAY(String(16)), nullable=False)
    user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        PG_ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("threshold BETWEEN 1 AND 1000", name="ck_threshold"),
        CheckConstraint(
            "window_minutes IN (5, 15, 30, 60, 240, 1440)",
            name="ck_window",
        ),
        Index("ix_workflow_log_alert_rules_workflow", "organization_id", "workflow_id"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowLogAlertRule({self.name!r} on workflow {self.workflow_id})>"


class WorkflowLogAlertFiring(Base):
    """One time a rule fired: when, how many lines it counted, and from when."""

    __tablename__ = "workflow_log_alert_firings"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_log_alert_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_workflow_log_alert_firings_rule", "rule_id", fired_at.desc()),)

    def __repr__(self) -> str:
        return f"<WorkflowLogAlertFiring(rule {self.rule_id}, {self.count} lines)>"
