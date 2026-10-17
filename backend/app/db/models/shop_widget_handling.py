"""Live-agent handling state for storefront widget conversations."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ShopWidgetHandling(Base, TimestampMixin):
    """Per-widget-conversation handling mode (AI vs staff)."""

    __tablename__ = "shop_widget_handling"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    handling_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ai",
        server_default="ai",
        index=True,
    )
    claimed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    claimed_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ShopWidgetHandling(conversation_id={self.conversation_id}, mode={self.handling_mode})>"
