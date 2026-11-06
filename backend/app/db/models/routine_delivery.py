"""One durable console handoff for a routine's resumed final answer."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RoutineDelivery(Base, TimestampMixin):
    __tablename__ = "routine_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'delivered', 'unavailable', 'run_log', 'no_answer')",
            name="ck_routine_delivery_status",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Retain the origin when a routine is removed; the worker records unavailable.
    trigger_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<RoutineDelivery(run_id={self.run_id}, status={self.status})>"
