"""User database model."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Boolean, DateTime, String, text
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


class UserRole(StrEnum):
    """User role enumeration.

    Roles hierarchy (higher includes lower permissions):
    - ADMIN: Full system access, can manage users and settings
    - USER: Standard user access
    """

    ADMIN = "admin"
    USER = "user"


class User(Base, TimestampMixin):
    """User model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), default=UserRole.USER.value, nullable=False)
    is_app_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
        "Session", back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def user_role(self) -> UserRole:
        """Get role as enum."""
        return UserRole(self.role)

    def has_role(self, required_role: UserRole) -> bool:
        """Check if user has the required role or higher.

        Admin role has access to everything.
        """
        if self.role == UserRole.ADMIN.value:
            return True
        return self.role == required_role.value

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
