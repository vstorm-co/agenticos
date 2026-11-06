"""Bounded execution observations, independent of inbox acknowledgement state."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RoutineHealthObservation(Base):
    __tablename__ = "routine_health_observations"
    __table_args__ = (
        CheckConstraint(
            "(trigger_id IS NULL) <> (watch_id IS NULL)", name="ck_routine_health_parent"
        ),
        UniqueConstraint(
            "trigger_id", "activation_at", name="uq_routine_health_trigger_activation"
        ),
        UniqueConstraint("watch_id", "activation_at", name="uq_routine_health_watch_activation"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trigger_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_triggers.id", ondelete="CASCADE")
    )
    watch_id: Mapped[UUID | None] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    activation_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    healthy: Mapped[bool] = mapped_column(Boolean)
