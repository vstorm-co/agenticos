"""Per–minerp-tenant Shop AI settings (FAQ curation, D3 B58)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ShopAiSettings(Base):
    __tablename__ = "shop_ai_settings"

    minerp_tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    default_faq_suggestion_kb_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
    )
    auto_draft_faq_min_occurrences: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    assistant_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    assistant_tone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assistant_custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    merchant_morning_digest_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ShopAiSettings(minerp_tenant_id={self.minerp_tenant_id})>"
