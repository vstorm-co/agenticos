"""Customer question suggestions for merchant FAQ curation (D3 B56)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ShopFaqSuggestion(Base, TimestampMixin):
    __tablename__ = "shop_faq_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "minerp_tenant_id",
            "knowledge_base_id",
            "question_fingerprint",
            name="uq_shop_faq_suggestions_tenant_kb_fp",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    minerp_tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="widget")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    suggested_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_answer_auto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    suggested_answer_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
