"""Scope bindings and execution links; task contents live in Virtual Table records."""

from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TaskBoard(Base, TimestampMixin):
    __tablename__ = "task_boards"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_kind", "scope_id", name="uq_task_board_scope"),
        CheckConstraint(
            "scope_kind IN ('private', 'project', 'group', 'organization')",
            name="ck_task_board_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scope_kind: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    column_ids: Mapped[dict[str, str]] = mapped_column(JSONB)
    status_ids: Mapped[dict[str, str]] = mapped_column(JSONB)
    table_id: Mapped[UUID] = mapped_column(
        ForeignKey("virtual_tables.id", ondelete="CASCADE"), unique=True
    )


class TaskLink(Base, TimestampMixin):
    __tablename__ = "task_links"

    record_id: Mapped[UUID] = mapped_column(
        ForeignKey("virtual_table_records.id", ondelete="CASCADE"), primary_key=True
    )
    board_id: Mapped[UUID] = mapped_column(
        ForeignKey("task_boards.id", ondelete="CASCADE"), index=True
    )
    creator_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    outcome_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outcomes.id", ondelete="SET NULL"), unique=True
    )
    execution_hash: Mapped[str | None] = mapped_column(String(64))
    trigger_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_triggers.id", ondelete="SET NULL"), unique=True
    )
