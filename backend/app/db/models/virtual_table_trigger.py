"""A workflow a table runs when a record is added (#1785).

Record writes already leave a `VirtualTableOutbox` row in the transaction that
creates the record - whichever surface wrote it: the console, the API, an agent's
table tool or a workflow's table step. A trigger is what reads those rows. It
names a table and a published workflow version, filters on the record as it was
created, maps its values onto the run's input, and runs as the member who set it
up. The record's author is only ever data the run can read, never whose
authority it runs with.

`activated_at` is the subscription boundary. A record committed before the
trigger was switched on - or while it was off - never starts it, which is what
keeps activation from replaying a backlog.

Every configuration write keeps an immutable `VirtualTableTriggerRevision`, and
every event a trigger judged keeps a `TableTriggerAdmission`: queued (a run),
filtered, blocked or failed, with a coarse reason and never the record's data.
`(trigger_id, outbox_event_id)` is unique, which is what makes each event admit
at most once per trigger however many consumers race for it.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
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

from app.db.base import Base, TimestampMixin


class AdmissionStatus(enum.StrEnum):
    QUEUED = "queued"
    FILTERED = "filtered"
    BLOCKED = "blocked"
    FAILED = "failed"


class AdmissionReason(enum.StrEnum):
    FILTER_MISMATCH = "filter_mismatch"
    PRE_ACTIVATION = "pre_activation"
    CYCLE = "cycle"
    DEPTH_LIMIT = "depth_limit"
    QUOTA = "quota"
    PERMISSION_DENIED = "permission_denied"
    UNAVAILABLE = "unavailable"


class VirtualTableTrigger(Base, TimestampMixin):
    """One table, one pinned workflow version, one member it runs as."""

    __tablename__ = "virtual_table_triggers"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_tables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # `RecordFilter`s by column id, all of which must hold on the creation snapshot.
    filters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # Payload key -> a column id, `@author` for the record's creator or `@record_id`.
    input_mapping: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    # Whoever set it up or last changed it - never someone they name. SET NULL
    # keeps the history; a null principal admits nothing (`FAILED`).
    execution_principal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The subscription boundary: an event committed before this never admits.
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "NOT is_active OR activated_at IS NOT NULL", name="ck_table_trigger_active_since"
        ),
    )


class VirtualTableTriggerRevision(Base):
    """One configuration a trigger had - never updated, so a past decision can
    always be traced to the filter, mapping, principal and version that made it."""

    __tablename__ = "virtual_table_trigger_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trigger_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_table_triggers.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    filters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    input_mapping: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    execution_principal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("trigger_id", "revision", name="uq_table_trigger_revision"),)


class TableTriggerAdmission(Base):
    """What one trigger decided about one added record."""

    __tablename__ = "table_trigger_admissions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_table_triggers.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL: the outbox's retention sweep deletes delivered rows, and the
    # decision outlives the row it was made about.
    outbox_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_table_outbox.id", ondelete="SET NULL"),
        nullable=True,
    )
    trigger_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("trigger_id", "outbox_event_id", name="uq_table_trigger_admission"),
        CheckConstraint(
            "status IN ('queued', 'filtered', 'blocked', 'failed')",
            name="ck_table_trigger_admission_status",
        ),
    )
