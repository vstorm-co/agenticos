"""User database model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Boolean, DateTime, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.session import Session

# The column names of the opt-outs below, for code that resolves recipients and
# needs to say which preference applies. A Literal rather than an enum so a typo
# is a type error, not a runtime AttributeError inside a `finally` block.
NotificationPreference = Literal[
    "notify_budget_alerts",
    "notify_approval_requests",
    "notify_usage_reports",
]


class User(Base, TimestampMixin):
    """User model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # The one global privilege. Authorization inside an organization is a
    # membership row plus the permission catalog, never a column on the user -
    # see `app/core/permissions.py`. This flag is deliberately outside that: it
    # administers the *deployment*, so it is not scoped to a tenant.
    is_app_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The chosen default-avatar colour, slot 1..10 into the `--avatar-*` ramp;
    # null means auto (derived from the id). Only used when no picture is set.
    avatar_color: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Opt-outs for the lifecycle emails (budget alerts, approval requests,
    # usage reports). Consulted where recipients are resolved, in
    # NotificationService; transactional mail deliberately has no preference.
    # Default true: the emails exist because a run nobody was watching went
    # quiet, and an opt-in nobody has set yet is the same silence.
    notify_budget_alerts: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    notify_approval_requests: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    notify_usage_reports: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    sessions: Mapped[list["Session"]] = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Session.user_id",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"
