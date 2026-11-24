"""An activation awaiting its particular computer before any model/effect starts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RoutineDeviceWait(Base, TimestampMixin):
    __tablename__ = "routine_device_waits"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_triggers.id", ondelete="CASCADE"), nullable=False
    )
    # Preserve the original paired-session ID even after that session is revoked.
    device_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    intent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_event: Mapped[bool] = mapped_column(Boolean, nullable=False)
    event_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The full event payload parked beside its rendered context (#14): the
    # GitHub delivery's `GithubTriggerOutput`-shaped dict, so a fire that waits
    # for its computer still hands the run the whole payload when it wakes -
    # the job queue carries it on the direct path, this row on the waiting one.
    # SQL NULL on a scheduled wait, an event without payload, and after redaction.
    # JSON null would fail the terminal-state redaction constraint below.
    event_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="waiting", server_default="waiting"
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    last_failed_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    admission_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting', 'started', 'cancelled', 'expired', 'failed')",
            name="ck_routine_device_wait_status",
        ),
        CheckConstraint(
            "status IN ('waiting', 'failed') OR (event_context IS NULL AND event_payload IS NULL)",
            name="ck_routine_device_wait_redacted",
        ),
        CheckConstraint("admission_failures >= 0", name="ck_routine_device_wait_failures"),
        Index("ix_routine_device_wait_trigger_status", "trigger_id", "status"),
        Index(
            "ix_routine_device_wait_finished",
            "organization_id",
            "finished_at",
            "id",
            postgresql_where=text("status != 'waiting'"),
        ),
        Index(
            "ix_routine_device_wait_pending",
            "created_at",
            "id",
            postgresql_where=text("status = 'waiting'"),
        ),
        Index(
            "uq_routine_device_wait_schedule",
            "trigger_id",
            unique=True,
            postgresql_where=text("status = 'waiting' AND NOT is_event"),
        ),
    )

    def __repr__(self) -> str:
        return f"<RoutineDeviceWait(id={self.id}, status={self.status})>"
