"""Session database model for tracking user sessions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Session(Base):
    """User session model for tracking active login sessions."""

    __tablename__ = "sessions"
    __table_args__ = (
        # Every read of a user's sessions is "this user's, most recently used
        # first" - the devices list, its page count, and the admin drawer's
        # last-seen. Nothing prunes this table (a refresh deactivates the row it
        # used and inserts another), so on a long-lived account the leading
        # column alone left Postgres sorting a year of rows to answer with one
        # (#1256). `id` is in it because `last_used_at` ties on two sign-ins in
        # the same moment and the page order has to be total.
        Index(
            "sessions_user_id_last_used_at_idx",
            "user_id",
            sa_text("last_used_at DESC"),
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # No index of its own: the composite above leads on this column, so a
    # single-column one is a second index Postgres would never choose and every
    # insert would still maintain.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user = relationship("User", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<Session(id={self.id}, user_id={self.user_id}, device={self.device_name})>"
